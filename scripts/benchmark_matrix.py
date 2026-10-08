#!/usr/bin/env python3
"""Run a serial, interleaved benchmark matrix with complete per-process records."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time
from zoneinfo import ZoneInfo

INDEXES = ['std_map', 'abseil_btree', 'tlx_btree', 'rocksdb_inlineskiplist',
           'btreeolc', 'unodb_art', 'masstree', 'hot', 'wormhole']
ENV = {k: v for k, v in os.environ.items()
       if k.lower() not in {'http_proxy', 'https_proxy', 'all_proxy'}}


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()


def output(command):
    return subprocess.check_output(command, text=True, env=ENV).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--keys', type=int, default=1000000)
    parser.add_argument('--ops', type=int, default=1000000)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--threads', default='1,2,4,8,16')
    parser.add_argument('--cpus', required=True, help='One logical CPU per physical core, comma separated')
    parser.add_argument('--numa-node', type=int, default=0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    root = args.output.resolve()
    threads = [int(t) for t in args.threads.split(',')]
    cpus = [int(c) for c in args.cpus.split(',')]
    if min(args.keys, args.ops, args.repeats, *threads) < 1 or max(threads) > len(cpus):
        parser.error('positive counts and at least one distinct CPU per worker are required')
    topology = {}
    for line in output(['lscpu', '-p=CPU,CORE,SOCKET,NODE']).splitlines():
        if not line.startswith('#'):
            cpu, core, socket, node = map(int, line.split(','))
            topology[cpu] = (core, socket, node)
    if len(cpus) != len(set(cpus)) or any(c not in os.sched_getaffinity(0) for c in cpus):
        parser.error('CPU list contains duplicates or disallowed CPU IDs')
    if any(topology[c][2] != args.numa_node for c in cpus):
        parser.error('all selected CPUs must belong to the selected NUMA node')
    if len({topology[c][:2] for c in cpus}) != len(cpus):
        parser.error('CPU list must not contain SMT siblings')
    listing = output([str(binary), '--list-indexes'])
    available = {line.split('\t')[0] for line in listing.splitlines()
                 if line.split('\t')[1] == 'available'}
    missing = set(INDEXES) - available
    if missing:
        raise RuntimeError(f'missing required adapters: {sorted(missing)}\n{listing}')
    scenarios = [('single_uniform', 1, 'uniform', 1), ('single_zipf', 1, 'zipf', 1),
                 ('lifecycle_uniform', 3, 'uniform', 1),
                 *[(f'mixed_t{t}', 2, 'uniform', t) for t in threads]]
    root.mkdir(parents=True, exist_ok=False)
    (root / 'runs').mkdir()
    repo = binary.parent.parent
    pins = {}
    for name in ('abseil-cpp', 'tlx', 'rocksdb', 'btreeolc', 'unodb', 'masstree', 'hot', 'wormhole'):
        pins[name] = output(['git', '-C', str(repo / 'vendor' / name), 'rev-parse', 'HEAD'])
    manifest_path = repo / 'source-manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if manifest:
        for name, digest in manifest['files'].items():
            if hashlib.sha256((repo / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f'source manifest differs: {name}')
        (root / 'source-manifest.json').write_text(manifest_path.read_text())
    metadata = {
        'status': 'running', 'started_at': now(), 'source': manifest,
        'binary': str(binary), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'compiler': output(['g++', '--version']).splitlines()[0],
        'build_type': 'Release (-O3 -DNDEBUG); per-library ISA flags in CMake',
        'kernel': output(['uname', '-a']), 'cpu_topology': output(['lscpu']),
        'numa': output(['numactl', '--hardware']), 'memory': output(['free', '-h']),
        'perf_event_paranoid': Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip(),
        'load_before': Path('/proc/loadavg').read_text().strip(),
        'cpu_governor': Path(f'/sys/devices/system/cpu/cpu{cpus[0]}/cpufreq/scaling_governor').read_text().strip(),
        'turbo_disabled': Path('/sys/devices/system/cpu/intel_pstate/no_turbo').read_text().strip(),
        'selected_cpus': cpus, 'numa_node': args.numa_node, 'smt_siblings_used': False,
        'keys': args.keys, 'ops': args.ops, 'user_key_bytes': 24, 'logical_key_bytes': 33,
        'value_bytes': 64, 'internal_key': True, 'scan_length': 100, 'read_percent': 80,
        'repeats': args.repeats, 'seeds': list(range(42, 42 + args.repeats)),
        'scenarios': scenarios, 'indexes': INDEXES, 'adapter_listing': listing,
        'dependencies': pins, 'boost_headers': '1.86.0',
        'planned_processes': len(scenarios) * len(INDEXES) * args.repeats,
        'completed_processes': 0,
        'method': 'Fresh process per stage/index/repeat; serial execution; randomized interleaved order; '
                  '100k-key warmup per adapter excluded; same seeds within each comparison; '
                  'numactl binds process allocations before startup, harness pins each worker; '
                  'no frequency lock or exclusive CPU reservation; background load recorded',
    }
    (root / 'build-config.txt').write_text((binary.parent / 'CMakeCache.txt').read_text())

    def save_metadata():
        (root / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')

    save_metadata()

    def run(index, scenario, stage, distribution, worker_count, repeat, ordinal, warmup=False):
        stem = f'{ordinal:03d}-{scenario}-{index}-r{repeat + 1}'
        target = root / 'runs' / (stem + '.csv')
        selected = ','.join(map(str, cpus[:worker_count]))
        command = ['numactl', '--physcpubind=' + selected, '--membind=' + str(args.numa_node),
                   str(binary), '--stage', str(stage), '--index', index, '--internal-key',
                   '--keys', str(min(100000, args.keys) if warmup else args.keys),
                   '--ops', str(min(200000, args.ops) if warmup else args.ops),
                   '--key-layout', 'legacy', '--key-preparation', 'inline', '--key-size', '24', '--value-size', '64', '--scan-length', '100',
                   '--read-percent', '80', '--distribution', distribution,
                   '--threads', str(worker_count), '--cpu-list', selected,
                   '--numa-node', str(args.numa_node), '--seed', str(41 if warmup else 42 + repeat),
                   '--output', str(target)]
        start = time.monotonic()
        record = {'ordinal': ordinal, 'scenario': scenario, 'index': index, 'repeat': repeat + 1,
                  'warmup': warmup, 'started_at': now(), 'command': command,
                  'load_before': Path('/proc/loadavg').read_text().strip()}
        metadata['current_run'] = record
        save_metadata()
        result = subprocess.run(command, env=ENV, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=600)
        elapsed = time.monotonic() - start
        (root / 'runs' / (stem + '.log')).write_text(result.stdout)
        record.update(process_elapsed_s=elapsed, returncode=result.returncode,
                      load_after=Path('/proc/loadavg').read_text().strip())
        with (root / 'commands.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        if result.returncode != 0:
            raise RuntimeError(f'{stem}: exit {result.returncode}\n{result.stdout}')
        with target.open(newline='') as stream:
            reader = csv.DictReader(stream)
            if len(reader.fieldnames) not in (36, 55):
                raise RuntimeError('unexpected CSV schema')
            rows = list(reader)
        expected = {1: ['insert', 'get', 'scan'], 2: ['mixed'],
                    3: ['insert', 'freeze', 'ordered_flush', 'destroy']}[stage]
        assert [r['phase'] for r in rows] == expected, stem
        assert all(r['index'] == index and r['internal_key'] == '1' for r in rows), stem
        if stage == 3:
            assert int(rows[2]['items_scanned']) == args.keys, stem
        if warmup:
            return rows
        for row in rows:
            row.update(scenario=scenario, repeat=repeat + 1, seed=42 + repeat,
                       run_sequence=ordinal, process_elapsed_s=f'{elapsed:.6f}')
        return rows

    try:
        for ordinal, index in enumerate(INDEXES):
            run(index, 'warmup', 1, 'uniform', 1, 0, ordinal, warmup=True)
            print(f'Warmup {ordinal + 1}/{len(INDEXES)} {index}', flush=True)
        checksums = {}
        ordinal = len(INDEXES)
        order_rng = random.Random(20261008)
        with (root / 'raw.csv').open('w', newline='') as raw:
            writer = None
            for repeat in range(args.repeats):
                scenario_order = list(scenarios)
                order_rng.shuffle(scenario_order)
                for scenario, stage, distribution, worker_count in scenario_order:
                    adapter_order = list(INDEXES)
                    order_rng.shuffle(adapter_order)
                    for index in adapter_order:
                        rows = run(index, scenario, stage, distribution, worker_count, repeat, ordinal)
                        observed = [(r['phase'], r['ops'], r['items_scanned'], r['checksum']) for r in rows]
                        group = (scenario, repeat)
                        if group in checksums:
                            assert observed == checksums[group], (group, index, 'checksum mismatch')
                        else:
                            checksums[group] = observed
                        if writer is None:
                            writer = csv.DictWriter(raw, fieldnames=list(rows[0]))
                            writer.writeheader()
                        writer.writerows(rows)
                        raw.flush()
                        metadata['completed_processes'] += 1
                        metadata['last_completed'] = {'scenario': scenario, 'index': index, 'repeat': repeat + 1,
                                                      'process_elapsed_s': rows[0]['process_elapsed_s']}
                        save_metadata()
                        ordinal += 1
                        print(f"{metadata['completed_processes']}/{metadata['planned_processes']} "
                              f'{scenario} {index} repeat {repeat + 1}', flush=True)
        metadata.update(status='complete', finished_at=now(), checksum_groups_verified=len(checksums),
                        load_after=Path('/proc/loadavg').read_text().strip())
        save_metadata()
    except BaseException as error:
        metadata.update(status='failed', failed_at=now(), error=repr(error))
        save_metadata()
        raise
    print(f'Complete: {root}', flush=True)


if __name__ == '__main__':
    main()
