#!/usr/bin/env python3
"""MVCC screening matrix: version depth, prefixes and values as separate factors."""
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

ENV = {k: v for k, v in os.environ.items() if k.lower() not in {'http_proxy', 'https_proxy', 'all_proxy'}}
PROFILES = {
    'base': dict(key_size=16, value_size=32, versions=4, snapshot_lag=2, batch_size=32),
    'deep': dict(key_size=16, value_size=32, versions=16, snapshot_lag=15, batch_size=32),
    'prefix': dict(key_size=32, value_size=32, versions=4, snapshot_lag=2, batch_size=32,
                   key_layout='global-prefix', prefix_bytes=24),
    'value': dict(key_size=16, value_size=1024, versions=4, snapshot_lag=2, batch_size=32),
}


def output(command):
    return subprocess.check_output(command, text=True, env=ENV).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--indexes', help='Default: all available adapters')
    parser.add_argument('--profiles', default='base,deep,prefix,value')
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
    profiles = args.profiles.split(',')
    threads = [int(n) for n in args.threads.split(',')]
    if set(available) - {*INDEXES, 'cse_crossbeam'}:
        parser.error('binary advertises retired adapters; rebuild it for the current cohort')
    if not indexes or set(indexes)-set(available) or set(profiles)-set(PROFILES):
        parser.error('unavailable adapter or unknown profile')
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
        print(json.dumps(dict(processes=len(jobs), profiles=profiles, indexes=indexes,
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
    metadata = dict(status='running', model='mvcc-v1', started_at=time.time(),
                    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                    source_files=manifest, dependencies=dependencies, adapter_listing=listing,
                    arguments=vars(args) | {'binary': str(binary), 'output': str(root)},
                    profiles={p: PROFILES[p] for p in profiles}, planned_processes=len(jobs),
                    completed_processes=0, host=output(['uname', '-a']),
                    method='Fresh process per profile/stage/index/repeat; randomized serial order; '
                           'fixed snapshots; full independent oracle validation; no disk I/O; no warmup')
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
            expected_phases = {1: {'batch_load','get_latest','get_snapshot','scan_latest','scan_snapshot'},
                               2: {'mixed_snapshot'} if workers == 1 else {'swmr_total','swmr_writer_batch','swmr_readers'},
                               3: {'batch_load','freeze','flush_all_versions','destroy'}}[stage]
            if {r['phase'] for r in process_rows} != expected_phases or len(process_rows) != len(expected_phases):
                raise RuntimeError(f'phase matrix differs: {name}')
            for row in process_rows:
                row.update(profile=profile, repeat=repeat+1, scenario_threads=workers)
                group = (profile, stage, workers, repeat, row['phase'])
                signature = tuple(row[k] for k in ('requests','point_reads','scan_requests','written_versions',
                    'live_hits','tombstone_hits','not_found','items','stored_versions','checksum','dataset_hash'))
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
