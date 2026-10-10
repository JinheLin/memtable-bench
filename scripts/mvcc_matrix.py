#!/usr/bin/env python3
"""Run OLTP latest-version and long-chain historical MVCC groups separately."""
import argparse
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time
from adapter_policy import INDEXES
from mvcc_workloads import GROUPS, PROFILES, SUITES, comparison_fields, phases

ENV = {k: v for k, v in os.environ.items() if k.lower() not in {'http_proxy', 'https_proxy', 'all_proxy'}}


def output(command):
    return subprocess.check_output(command, text=True, env=ENV).strip()


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def save_rows(root, rows):
    if not rows:
        return
    temporary = root/'raw.csv.tmp'
    with temporary.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(root/'raw.csv')


def read_result(path, job, checks, group):
    profile, stage, workers, index, repeat = job
    rows = list(csv.DictReader(path.open()))
    expected = set(phases(stage, workers, PROFILES[profile]['read_view']))
    if {r['phase'] for r in rows} != expected or len(rows) != len(expected):
        raise RuntimeError(f'phase matrix differs: {path}')
    for row in rows:
        if row['schema_version'] != 'mvcc-v2' or row['read_view'] != PROFILES[profile]['read_view']:
            raise RuntimeError(f'workload protocol differs: {path}; rebuild the binary')
        if row['index'] != index or row['stage'] != str(stage) or row['seed'] != str(42+repeat):
            raise RuntimeError(f'process identity differs: {path}')
        if row['oracle_checksum'] and row['checksum'] != row['oracle_checksum']:
            raise RuntimeError(f'oracle checksum differs: {path}')
        row.update(profile=profile, repeat=repeat+1, scenario_threads=workers, workload_group=group)
        comparison = (profile, stage, workers, repeat, row['phase'])
        signature = tuple(row[k] for k in comparison_fields(row))
        if comparison in checks and checks[comparison] != signature:
            raise RuntimeError(f'cross-adapter result differs: {comparison}, {index}')
        checks[comparison] = signature
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--indexes', help='Default: all available adapters')
    parser.add_argument('--suite', choices=SUITES, default='quick',
                        help='quick (default): screening; full: formal matrix; smoke: correctness')
    parser.add_argument('--group', choices=['oltp', 'history', 'all'], default='all')
    parser.add_argument('--profiles', help='Subset of profiles within the selected group')
    parser.add_argument('--threads', help='Override suite stage-2 worker counts')
    parser.add_argument('--stages', help='Subset of 1,2,3; default all stages')
    parser.add_argument('--keys', type=int)
    parser.add_argument('--ops', type=int)
    parser.add_argument('--repeats', type=int)
    parser.add_argument('--cpus')
    parser.add_argument('--numa-node', type=int, default=-1)
    parser.add_argument('--list-plan', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Reuse verified completed jobs in the same output')
    args = parser.parse_args()
    suite = SUITES[args.suite]
    for field in ('threads', 'stages', 'keys', 'ops', 'repeats'):
        if getattr(args, field) is None:
            setattr(args, field, suite[field])
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
    profiles = args.profiles.split(',') if args.profiles else [p for p in suite['profiles'] if p in allowed]
    args.profiles = ','.join(profiles)
    try:
        threads = [int(n) for n in args.threads.split(',')]
        stages = [int(n) for n in args.stages.split(',')]
    except ValueError:
        parser.error('threads/stages must be comma-separated integers')
    if set(available) - {*INDEXES, 'cse_crossbeam'}:
        parser.error('binary advertises retired adapters; rebuild it for the current cohort')
    if not indexes or not profiles or set(indexes)-set(available) or set(profiles)-set(allowed):
        parser.error('unavailable adapter or profile outside the selected group')
    if min(args.keys, args.ops, args.repeats, *threads) < 1 or len(set(threads)) != len(threads):
        parser.error('positive sizes / unique thread counts required')
    if len(set(indexes)) != len(indexes) or len(set(profiles)) != len(profiles):
        parser.error('duplicate indexes/profiles')
    if not stages or set(stages)-{1,2,3} or len(set(stages)) != len(stages):
        parser.error('stages must be a unique subset of 1,2,3')
    args.threads = ','.join(map(str, threads))
    args.stages = ','.join(map(str, stages))
    args.indexes = ','.join(indexes)
    jobs = [(profile, stage, workers, index, repeat)
            for profile in profiles for stage in stages
            for workers in (threads if stage == 2 else [1])
            for index in indexes if workers == 1 or index in native
            for repeat in range(args.repeats)]
    if not jobs:
        parser.error('no jobs; select a native concurrent adapter or include threads=1')
    prefill = sum(args.keys*PROFILES[profile]['versions'] for profile, _, _, _, _ in jobs)
    if args.list_plan:
        print(json.dumps(dict(processes=len(jobs),
                              phase_rows=sum(len(phases(stage, workers, PROFILES[profile]['read_view']))
                                             for profile, stage, workers, _, _ in jobs),
                              suite=args.suite, repeats=args.repeats, keys=args.keys, ops=args.ops,
                              stages=stages, total_prefill_versions=prefill,
                              group=args.group, profiles=profiles, configurations={p: PROFILES[p] for p in profiles}, indexes=indexes,
                              native_concurrent=sorted(native), threads=threads), indent=2))
        return
    if args.cpus:
        cpus = [int(c) for c in args.cpus.split(',')]
        if len(cpus) < max(job[2] for job in jobs) or len(set(cpus)) != len(cpus):
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
    arguments = vars(args) | {'binary': str(binary), 'output': str(root)}
    arguments.pop('resume')
    arguments.pop('list_plan')
    metadata = dict(status='running', model='mvcc-v2', runner_version=2, started_at=time.time(),
                    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                    source_files=manifest, dependencies=dependencies, adapter_listing=listing,
                    arguments=arguments,
                    profiles={p: PROFILES[p] for p in profiles},
                    profile_groups={p: group for group, names in GROUPS.items() for p in profiles if p in names},
                    planned_processes=len(jobs), total_prefill_versions=prefill,
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
    if args.resume:
        previous = json.loads((root/'metadata.json').read_text())
        for field in ('runner_version', 'arguments', 'binary_sha256', 'source_files', 'dependencies',
                      'adapter_listing', 'host', 'topology'):
            if previous.get(field) != metadata.get(field):
                parser.error(f'cannot resume: {field} changed; use a new output directory')
        metadata = previous
    else:
        root.mkdir(parents=True, exist_ok=False)
        (root/'runs').mkdir()
    lock = (root/'.runner.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('another runner is using this output directory')
    random.Random(931).shuffle(jobs)
    checks, rows = {}, []
    invocation = dict(started_at=time.time(), reused_processes=0, executed_processes=0)
    metadata.setdefault('invocations', []).append(invocation)
    metadata.setdefault('process_wall_seconds', {})
    metadata.update(status='running', completed_processes=0)
    save_json(root/'metadata.json', metadata)
    try:
        for job in jobs:
            profile, stage, workers, index, repeat = job
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
            command_path = root/'runs'/f'{name}.command.json'
            log_path = root/'runs'/f'{name}.log'
            marker = root/'runs'/f'{name}.complete.json'
            metadata['active_job'] = name
            save_json(root/'metadata.json', metadata)
            if marker.exists():
                done = json.loads(marker.read_text())
                if set(done['files']) != {dest.name, command_path.name, log_path.name}:
                    raise RuntimeError(f'completed process manifest differs: {name}')
                if not args.resume or done['command'] != command or any(
                    hashlib.sha256((root/'runs'/path).read_bytes()).hexdigest() != sha
                    for path, sha in done['files'].items()):
                    raise RuntimeError(f'completed process evidence differs: {name}')
                process_rows = read_result(dest, job, checks, metadata['profile_groups'][profile])
                invocation['reused_processes'] += 1
                action = 'reused'
            else:
                existing = [path for path in (dest, command_path, log_path) if path.exists()]
                if existing:
                    failed = root/'failed-attempts'/f'{name}-{time.time_ns()}'
                    failed.mkdir(parents=True)
                    for path in existing:
                        path.rename(failed/path.name)
                command_path.write_text(json.dumps(command)+'\n')
                began = time.monotonic()
                with log_path.open('w') as stream:
                    subprocess.run(command, env=ENV, stdout=stream, stderr=subprocess.STDOUT, check=True)
                elapsed = time.monotonic()-began
                process_rows = read_result(dest, job, checks, metadata['profile_groups'][profile])
                done = dict(command=command, wall_seconds=elapsed,
                            files={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in (dest, command_path, log_path)})
                save_json(marker, done)
                invocation['executed_processes'] += 1
                action = 'done'
            metadata['process_wall_seconds'][name] = done['wall_seconds']
            rows.extend(process_rows)
            metadata['completed_processes'] += 1
            save_rows(root, rows)
            save_json(root/'metadata.json', metadata)
            print(f'{metadata["completed_processes"]}/{len(jobs)} {name} {action} wall={done["wall_seconds"]:.3f}s', flush=True)
        if hashlib.sha256(binary.read_bytes()).hexdigest() != metadata['binary_sha256'] or any(
            hashlib.sha256((repo/path).read_bytes()).hexdigest() != sha for path, sha in manifest.items()):
            raise RuntimeError('binary/source changed during measurement')
        metadata['status'] = 'complete'
    except BaseException:
        metadata['status'] = 'failed'
        raise
    finally:
        metadata['finished_at'] = time.time()
        invocation.update(finished_at=metadata['finished_at'], status=metadata['status'])
        metadata.pop('active_job', None)
        save_rows(root, rows)
        save_json(root/'metadata.json', metadata)
        lock.close()


if __name__ == '__main__':
    main()
