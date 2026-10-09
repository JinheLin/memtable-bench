#!/usr/bin/env python3
"""Run controlled screening, representative workloads, or range-scan length sweeps."""
import argparse
import csv
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import time

from benchmark_matrix import ENV, now, output
from adapter_policy import INDEXES, KNOWN_INDEXES, POLICY, eligible_indexes, validate_listing


def configuration(name, key=64, value=64, layout='random', prefix=0, groups=1):
    return dict(config_id=name, key_size=key, value_size=value, key_layout=layout,
                prefix_bytes=prefix, prefix_groups=groups, distribution='uniform',
                hotspot_placement='spread', insert_order='random', scan_length=100,
                read_percent=80)


def screening():
    configs = [configuration(f'key_k{k}', key=k) for k in (8, 16, 32, 64, 112)]
    configs += [configuration(f'prefix_p{p}', layout='global-prefix', prefix=p) for p in (8, 24, 56)]
    configs += [configuration(f'value_v{v}', value=v) for v in (8, 1024)]
    configs += [configuration(f'groups_g{g}', layout='group-prefix', prefix=24, groups=g)
                for g in (16, 1024)]
    configs += [configuration(f'interaction_k{k}_p{p}_v{v}', key=k, value=v,
                              layout='global-prefix' if p else 'random', prefix=p)
                for k, p, v in itertools.product((32, 112), (0, 24), (8, 1024))]
    assert len(configs) == 20
    return configs


def representative():
    return [configuration('random'), configuration('long_prefix', layout='global-prefix', prefix=56),
            configuration('groups', layout='group-prefix', prefix=24, groups=1024),
            configuration('large_value', value=1024)]


def range_scan(lengths):
    configs = []
    for name, layout, prefix in [('random', 'random', 0), ('prefix', 'global-prefix', 56)]:
        for length in lengths:
            config = configuration(f'range_{name}_l{length}', layout=layout, prefix=prefix)
            config['scan_length'] = length
            configs.append(config)
    return configs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=['screening', 'representative', 'range-scan'], default='screening')
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--keys', type=int, default=1000000)
    parser.add_argument('--ops', type=int, default=1000000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--cpus', help='Distinct physical CPUs on one NUMA node')
    parser.add_argument('--numa-node', type=int, default=0)
    parser.add_argument('--threads', default='1,4,16', help='Representative suite mixed workloads')
    parser.add_argument('--scan-lengths', default='1,10,100,1000,10000', help='Range-scan maximum rows per call')
    parser.add_argument('--scan-calls', type=int, default=1000, help='Same number of calls for every range-scan length')
    parser.add_argument('--indexes', default=','.join(INDEXES))
    parser.add_argument('--configs', help='Optional comma-separated subset of config_id values')
    parser.add_argument('--list-plan', action='store_true')
    args = parser.parse_args()
    lengths = [int(n) for n in args.scan_lengths.split(',')]
    if len(lengths) != len(set(lengths)) or min(args.scan_calls, *lengths) < 1:
        parser.error('positive scan counts and unique scan lengths required')
    configs = (screening() if args.suite == 'screening' else
               representative() if args.suite == 'representative' else range_scan(lengths))
    if args.configs:
        wanted = args.configs.split(',')
        missing = set(wanted) - {c['config_id'] for c in configs}
        if missing:
            parser.error(f'unknown configs: {sorted(missing)}')
        configs = [c for c in configs if c['config_id'] in wanted]
    indexes = args.indexes.split(',')
    if len(indexes) != len(set(indexes)) or set(indexes) - KNOWN_INDEXES:
        parser.error('indexes must be a unique subset of known adapters')
    threads = [int(t) for t in args.threads.split(',')]
    if len(threads) != len(set(threads)) or min(args.keys, args.ops, args.repeats, *threads) < 1:
        parser.error('positive counts and unique thread counts required')
    if args.keys < max(c['prefix_groups'] for c in configs):
        parser.error('keys must be >= the largest selected prefix group count')
    workloads = ([('single_uniform', 1, 1)] if args.suite == 'screening' else
                 [('range_uniform', 1, 1)] if args.suite == 'range-scan' else
                 [*[(f'mixed_t{t}', 2, t) for t in threads], ('lifecycle_uniform', 3, 1)])
    # Every adapter gets a one-worker mixed baseline even when --threads omits 1.
    if args.suite == 'representative' and 1 not in threads:
        workloads.insert(0, ('mixed_t1', 2, 1))
    scenario_indexes = {name: eligible_indexes(indexes, workers) for name, _, workers in workloads}
    planned = len(configs) * sum(map(len, scenario_indexes.values())) * args.repeats
    if args.list_plan:
        print(json.dumps(dict(suite=args.suite, configs=configs, workloads=workloads,
                              repeats=args.repeats, indexes=indexes, formal_processes=planned,
                              concurrency_policy=POLICY, scenario_indexes=scenario_indexes,
                              scan_calls=args.scan_calls if args.suite=='range-scan' else None), indent=2))
        return
    if not args.binary or not args.output or not args.cpus:
        parser.error('--binary, --output and --cpus required to run')
    cpus = [int(c) for c in args.cpus.split(',')]
    required_threads = max(w[2] for w in workloads if scenario_indexes[w[0]])
    if required_threads > len(cpus) or len(cpus) != len(set(cpus)):
        parser.error('one distinct physical CPU per worker required')
    topology = {int(fields[0]): tuple(map(int, fields[1:]))
                for line in output(['lscpu', '-p=CPU,CORE,SOCKET,NODE']).splitlines()
                if not line.startswith('#') for fields in [line.split(',')]}
    if any(c not in os.sched_getaffinity(0) or topology[c][2] != args.numa_node for c in cpus):
        parser.error('CPUs must be allowed and on the selected NUMA node')
    if len({topology[c][:2] for c in cpus}) != len(cpus):
        parser.error('SMT siblings are not allowed')
    binary = args.binary.resolve()
    repo = binary.parent.parent
    listing = output([str(binary), '--list-indexes'])
    validate_listing(listing, indexes)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'runs').mkdir()
    manifest = repo / 'source-manifest.json'
    source = json.loads(manifest.read_text()) if manifest.exists() else None
    if source:
        for name, digest in source['files'].items():
            if hashlib.sha256((repo / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f'source manifest differs: {name}')
        (root / 'source-manifest.json').write_text(manifest.read_text())
    pins = {name: output(['git', '-C', str(repo / 'vendor' / name), 'rev-parse', 'HEAD'])
            for name in ('rocksdb', 'btreeolc', 'unodb', 'wormhole')
            if (repo / 'vendor' / name).exists()}
    meta = dict(status='running', suite=args.suite, started_at=now(), source=source,
                binary=str(binary), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                compiler=output(['g++', '--version']).splitlines()[0], kernel=output(['uname', '-a']),
                cpu_topology=output(['lscpu']), numa=output(['numactl', '--hardware']),
                memory=output(['free', '-h']), cpu_governor=Path(f'/sys/devices/system/cpu/cpu{cpus[0]}/cpufreq/scaling_governor').read_text().strip(),
                load_before=Path('/proc/loadavg').read_text().strip(), dependencies=pins,
                turbo_disabled=Path('/sys/devices/system/cpu/intel_pstate/no_turbo').read_text().strip(),
                perf_event_paranoid=Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip(),
                selected_cpus=cpus, numa_node=args.numa_node, keys=args.keys, ops=args.ops,
                repeats=args.repeats, seeds=list(range(42, 42+args.repeats)),
                scan_calls=args.scan_calls if args.suite=='range-scan' else None,
                indexes=indexes, adapter_listing=listing, configs=configs, workloads=workloads,
                concurrency_policy=POLICY, scenario_indexes=scenario_indexes,
                internal_key=True, key_preparation='precomputed', measure_detail=True,
                planned_processes=planned, completed_processes=0,
                method='Serial fresh processes in randomized config/workload/adapter order; '
                       'excluded 100k-key warmup per index; identical seeds and traces per comparison; '
                       'input logical keys and new MVCC versions materialized outside timing; '
                       'full frozen validation precedes cursor-only then full-payload scan; '
                       'LookupOnly precedes GetCopy using identical read traces; '
                       'numactl process binding plus per-thread pinning; no CPU reservation or frequency lock')
    if args.suite == 'range-scan':
        meta['method'] = ('Serial fresh processes; untimed prefill/freeze/full validation; '
                          'SeekOnly then cursor traversal then full-payload scan; '
                          'identical start traces and call counts across lengths/adapters for each key layout/seed; '
                          'maximum row limit, actual rows counted at EOF; NUMA binding and physical CPU pinning')
    (root/'build-config.txt').write_text((binary.parent/'CMakeCache.txt').read_text())
    (root/'plan.json').write_text(json.dumps(dict(configs=configs, workloads=workloads, scenario_indexes=scenario_indexes, concurrency_policy=POLICY), indent=2)+'\n')

    def save():
        target = root/'metadata.json'
        temporary = root/'metadata.json.tmp'
        temporary.write_text(json.dumps(meta, indent=2)+'\n')
        temporary.replace(target)

    save()

    def run(config, workload, index, repeat, ordinal, warmup=False):
        scenario, stage, workers = workload
        selected = ','.join(map(str, cpus[:workers]))
        stem = f'{ordinal:04d}-{config["config_id"]}-{scenario}-{index}-r{repeat+1}'
        target = root/'runs'/(stem+'.csv')
        dataset = root/'runs'/(stem+'-dataset.json')
        seed = 41 if warmup else 42+repeat
        command = ['numactl', '--physcpubind='+selected, '--membind='+str(args.numa_node),
                   str(binary), '--stage', str(stage), '--index', index, '--internal-key', '--measure-detail',
                   '--key-preparation', 'precomputed', '--keys', str(min(args.keys, 100000) if warmup else args.keys),
                   '--ops', str(min(args.ops, 200000) if warmup else args.ops), '--threads', str(workers),
                   '--cpu-list', selected, '--numa-node', str(args.numa_node), '--seed', str(seed),
                   '--output', str(target), '--dataset-output', str(dataset)]
        for flag in ('key_size','value_size','key_layout','prefix_bytes','prefix_groups','distribution',
                     'hotspot_placement','insert_order','scan_length','read_percent'):
            command += ['--'+flag.replace('_','-'), str(config[flag])]
        if args.suite == 'range-scan':
            command += ['--scan-only', '--scan-ops', str(args.scan_calls)]
        record = dict(ordinal=ordinal, config_id=config['config_id'], scenario=scenario, index=index,
                      repeat=repeat+1, warmup=warmup, started_at=now(), command=command,
                      load_before=Path('/proc/loadavg').read_text().strip())
        meta['current_run']=record
        save()
        start = time.monotonic()
        result = subprocess.run(command, env=ENV, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=900)
        elapsed = time.monotonic()-start
        (root/'runs'/(stem+'.log')).write_text(result.stdout)
        record.update(returncode=result.returncode, process_elapsed_s=elapsed,
                      load_after=Path('/proc/loadavg').read_text().strip())
        with (root/'commands.jsonl').open('a') as stream:
            stream.write(json.dumps(record)+'\n')
        if result.returncode:
            raise RuntimeError(f'{stem}: exit {result.returncode}\n{result.stdout}')
        rows = list(csv.DictReader(target.open(newline='')))
        expected = {1:['insert','lookup_only','get','scan_iterate','scan'], 2:['mixed'],
                    3:['insert','freeze','ordered_traverse','ordered_flush','destroy']}[stage]
        if args.suite == 'range-scan':
            expected = ['seek_only','scan_iterate','scan']
        if [r['phase'] for r in rows] != expected or any(len(r)!=55 or None in r.values() for r in rows):
            raise RuntimeError(f'{stem}: phase/schema mismatch')
        info = json.loads(dataset.read_text())
        count = min(args.keys, 100000) if warmup else args.keys
        assert info['keys']==count and sum(info['lcp_histogram'])==count-1
        for row in rows:
            assert row['schema_version']=='3' and row['dataset_hash']==info['dataset_hash_fnv1a64']
            assert row['key_layout']==config['key_layout'] and row['key_preparation']=='precomputed'
            assert row['index']==index and int(row['key_size'])==config['key_size']
            assert int(row['value_size'])==config['value_size']
            assert row['internal_key']=='1' and row['measure_detail']=='1'
            if row['phase'] in ('ordered_traverse','ordered_flush'):
                assert int(row['items_scanned'])==count
        if args.suite == 'range-scan':
            assert all(int(r['ops'])==args.scan_calls for r in rows)
            assert int(rows[0]['items_scanned'])==args.scan_calls
            assert rows[1]['items_scanned']==rows[2]['items_scanned']
            assert 0<int(rows[1]['items_scanned'])<=args.scan_calls*min(count,config['scan_length'])
        if warmup:
            return rows, info
        for row in rows:
            row.update(config_id=config['config_id'], scenario=scenario, repeat=repeat+1, seed=seed,
                       run_sequence=ordinal, process_elapsed_s=f'{elapsed:.6f}')
        return rows, info

    try:
        for ordinal,index in enumerate(indexes):
            run(configuration('warmup'), ('single_uniform',1,1),index,0,ordinal,True)
            print(f'Warmup {ordinal+1}/{len(indexes)} {index}',flush=True)
        checks, datasets = {}, {}
        ordinal = len(indexes)
        rng = random.Random(20261008)
        with (root/'raw.csv').open('w',newline='') as stream:
            writer = None
            for repeat in range(args.repeats):
                jobs = [(c,w) for c in configs for w in workloads]
                rng.shuffle(jobs)
                for config, workload in jobs:
                    order = list(scenario_indexes[workload[0]])
                    rng.shuffle(order)
                    for index in order:
                        rows, info = run(config,workload,index,repeat,ordinal)
                        group = (config['config_id'],workload[0],repeat)
                        observed = [tuple(r[f] for f in ('phase','ops','items_scanned','checksum')) for r in rows]
                        if group in checks and observed != checks[group]:
                            raise RuntimeError(f'checksum mismatch: {group} {index}')
                        checks[group] = observed
                        dataset_group = (config['config_id'],repeat)
                        if dataset_group in datasets and info != datasets[dataset_group]:
                            raise RuntimeError(f'generated dataset differs: {dataset_group} {index}')
                        datasets[dataset_group] = info
                        if writer is None:
                            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                            writer.writeheader()
                        writer.writerows(rows)
                        stream.flush()
                        meta['completed_processes']+=1
                        meta['last_completed']=dict(config_id=config['config_id'],scenario=workload[0],
                                                    index=index,repeat=repeat+1)
                        save()
                        ordinal+=1
                        print(f"{meta['completed_processes']}/{planned} {config['config_id']} "
                              f'{workload[0]} {index} repeat {repeat+1}',flush=True)
        meta.update(status='complete',finished_at=now(),checksum_groups_verified=len(checks),
                    dataset_groups_verified=len(datasets),load_after=Path('/proc/loadavg').read_text().strip())
        save()
    except BaseException as error:
        meta.update(status='failed',failed_at=now(),error=repr(error))
        save()
        raise
    print(f'Complete: {root}',flush=True)


if __name__=='__main__':
    main()
