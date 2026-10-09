#!/usr/bin/env python3
"""Run OLTP latest-version and long-chain historical MVCC groups separately."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time
from adapter_policy import INDEXES
from mvcc_workloads import GROUPS, PROFILES, comparison_fields, phases

ENV = {k: v for k, v in os.environ.items() if k.lower() not in {'http_proxy', 'https_proxy', 'all_proxy'}}


def output(command):
    return subprocess.check_output(command, text=True, env=ENV).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--indexes', help='Default: all available adapters')
    parser.add_argument('--group', choices=['oltp', 'history', 'all'], default='all')
    parser.add_argument('--profiles', help='Subset of profiles within the selected group')
    parser.add_argument('--threads', default='1,4,8')
    parser.add_argument('--keys', type=int, default=100000)
    parser.add_argument('--ops', type=int, default=100000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--cpus')
    parser.add_argument('--numa-node', type=int, default=-1)
    parser.add_argument('--list-plan', action='store_true')
    args = parser.parse_args()
    binary = args.binary.resolve()
    listing = output([str(binary), '--list-indexes'])
    available, native = [], set()
    for line in listing.splitlines():
        name, status, _, *fields = line.split('\t')
        if status == 'available':
            available.append(name)
            if 'native_concurrent=1' in fields:
                native.add(name)
    indexes = args.indexes.split(',') if args.indexes else available
    allowed = [name for group, names in GROUPS.items()
               if args.group in ('all', group) for name in names]
    profiles = args.profiles.split(',') if args.profiles else allowed
    args.profiles = ','.join(profiles)
    threads = [int(n) for n in args.threads.split(',')]
    if set(available) - {*INDEXES, 'cse_crossbeam'}:
        parser.error('binary advertises retired adapters; rebuild it for the current cohort')
    if not indexes or set(indexes)-set(available) or set(profiles)-set(allowed):
        parser.error('unavailable adapter or profile outside the selected group')
    if min(args.keys, args.ops, args.repeats, *threads) < 1 or len(set(threads)) != len(threads):
        parser.error('positive sizes / unique thread counts required')
    if len(set(indexes)) != len(indexes) or len(set(profiles)) != len(profiles):
        parser.error('duplicate indexes/profiles')
    jobs = [(profile, stage, workers, index, repeat)
            for profile in profiles for stage in (1, 2, 3)
            for workers in (threads if stage == 2 else [1])
            for index in indexes if workers == 1 or index in native
            for repeat in range(args.repeats)]
    if args.list_plan:
        print(json.dumps(dict(processes=len(jobs),
                              phase_rows=sum(len(phases(stage, workers, PROFILES[profile]['read_view']))
                                             for profile, stage, workers, _, _ in jobs),
                              group=args.group, profiles=profiles, configurations={p: PROFILES[p] for p in profiles}, indexes=indexes,
                              native_concurrent=sorted(native), threads=threads), indent=2))
        return
    if args.cpus:
        cpus = [int(c) for c in args.cpus.split(',')]
        if len(cpus) < max(threads) or len(set(cpus)) != len(cpus):
            parser.error('distinct CPU per worker required')
        topology = {}
        for line in output(['lscpu', '-p=CPU,CORE,SOCKET,NODE']).splitlines():
            if not line.startswith('#'):
                cpu, core, socket, node = map(int, line.split(','))
                topology[cpu] = (core, socket, node)
        if set(cpus)-os.sched_getaffinity(0) or len({topology[c][:2] for c in cpus}) != len(cpus):
            parser.error('CPU list uses disallowed CPUs or SMT siblings')
        if args.numa_node >= 0 and any(topology[c][2] != args.numa_node for c in cpus):
            parser.error('selected CPUs must be in the bound NUMA node')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root/'runs').mkdir()
    repo = Path(__file__).resolve().parents[1]
    files = [p for folder in ('src', 'include', 'cmake', 'rust', 'scripts', 'tests')
             for p in (repo/folder).rglob('*') if p.is_file() and
             p.suffix in {'.cc', '.h', '.cmake', '.rs', '.json', '.toml', '.lock', '.py', '.patch', '.in', '.sh'} and
             '__pycache__' not in p.parts and 'target' not in p.parts]
    files.append(repo/'CMakeLists.txt')
    manifest = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    dependencies = {}
    for name in ('rocksdb', 'btreeolc', 'unodb', 'wormhole'):
        p = repo/'vendor'/name
        if (p/'.git').exists():
            dependencies[p.name] = output(['git', '-C', str(p), 'rev-parse', 'HEAD'])
    cse_manifest = repo/'vendor/cse-memtable/source-manifest.json'
    if cse_manifest.exists():
        dependencies['cse'] = json.loads(cse_manifest.read_text())
        dependencies['rust_toolchain'] = output(['rustc', '+stable', '-vV'])
    metadata = dict(status='running', model='mvcc-v2', started_at=time.time(),
                    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                    source_files=manifest, dependencies=dependencies, adapter_listing=listing,
                    arguments=vars(args) | {'binary': str(binary), 'output': str(root)},
                    profiles={p: PROFILES[p] for p in profiles},
                    profile_groups={p: group for group, names in GROUPS.items() for p in profiles if p in names},
                    planned_processes=len(jobs),
                    completed_processes=0, host=output(['uname', '-a']),
                    method='Fresh process per profile/stage/index/repeat; randomized serial order; '
                           'latest published batch or fixed historical snapshots; independent oracle validation; '
                           'latest contents validated per run, deterministic counts compared across adapters; no disk I/O; no warmup')
    cache = binary.parent/'CMakeCache.txt'
    if cache.exists():
        metadata['cmake_configuration'] = [line for line in cache.read_text().splitlines()
                                           if line.startswith(('CMAKE_BUILD_TYPE:', 'CMAKE_CXX_COMPILER:',
                                                               'MEMTABLE_BENCH_', 'CMAKE_CXX_FLAGS'))]
    if Path('/proc/sys/kernel/perf_event_paranoid').exists():
        metadata['perf_event_paranoid'] = Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip()
        metadata['topology'] = output(['lscpu'])
    random.Random(931).shuffle(jobs)
    checks, rows = {}, []
    try:
        for profile, stage, workers, index, repeat in jobs:
            name = f'{profile}-s{stage}-t{workers}-{index}-r{repeat+1}'
            dest = root/'runs'/f'{name}.csv'
            command = [str(binary), '--index', index, '--stage', str(stage), '--threads', str(workers),
                       '--keys', str(args.keys), '--ops', str(args.ops), '--seed', str(42+repeat),
                       '--output', str(dest)]
            for key, value in PROFILES[profile].items():
                command += ['--'+key.replace('_','-'), str(value)]
            if args.cpus:
                command += ['--cpu-list', ','.join(args.cpus.split(',')[:workers])]
            if args.numa_node >= 0:
                command += ['--numa-node', str(args.numa_node)]
            (root/'runs'/f'{name}.command.json').write_text(json.dumps(command)+'\n')
            with (root/'runs'/f'{name}.log').open('w') as stream:
                subprocess.run(command, env=ENV, stdout=stream, stderr=subprocess.STDOUT, check=True)
            process_rows = list(csv.DictReader(dest.open()))
            expected_phases = set(phases(stage, workers, PROFILES[profile]['read_view']))
            if {r['phase'] for r in process_rows} != expected_phases or len(process_rows) != len(expected_phases):
                raise RuntimeError(f'phase matrix differs: {name}')
            for row in process_rows:
                if row['schema_version'] != 'mvcc-v2' or row['read_view'] != PROFILES[profile]['read_view']:
                    raise RuntimeError(f'workload protocol differs: {name}; rebuild the binary')
                if row['oracle_checksum'] and row['checksum'] != row['oracle_checksum']:
                    raise RuntimeError(f'oracle checksum differs: {name}')
                row.update(profile=profile, repeat=repeat+1, scenario_threads=workers,
                           workload_group=metadata['profile_groups'][profile])
                group = (profile, stage, workers, repeat, row['phase'])
                signature = tuple(row[k] for k in comparison_fields(row))
                if group in checks and checks[group] != signature:
                    raise RuntimeError(f'cross-adapter result differs: {group}, {index}')
                checks[group] = signature
                rows.append(row)
            metadata['completed_processes'] += 1
            print(f'{metadata["completed_processes"]}/{len(jobs)} {name}', flush=True)
        metadata['status'] = 'complete'
    except BaseException:
        metadata['status'] = 'failed'
        raise
    finally:
        metadata['finished_at'] = time.time()
        (root/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
        if rows:
            with (root/'raw.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


if __name__ == '__main__':
    main()
