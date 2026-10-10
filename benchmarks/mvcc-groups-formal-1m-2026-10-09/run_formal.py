#!/usr/bin/env python3
"""Run both million-user-key MVCC groups serially, retaining provenance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
BINARY = REPO / 'build-linux-core/mvcc_bench'
ENV = {k: v for k, v in os.environ.items()
       if k.lower() not in {'http_proxy', 'https_proxy', 'all_proxy'}}
EXPECTED_BINARY = '7ecb7d29c148a27b7ba1975f77f72daf5e7ecbbca8ab953b48f5bf508c24fbe5'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(command):
    result = subprocess.run(command, env=ENV, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    return dict(command=command, exit_code=result.returncode, output=result.stdout)


def resources():
    return dict(captured_at=time.time(), data=[capture(cmd) for cmd in (
        ['uname', '-a'], ['lscpu'], ['free', '-b'], ['df', '-B1', str(ROOT)],
        ['uptime'], ['numactl', '--hardware'], ['cat', '/proc/sys/kernel/perf_event_paranoid'])])


def main():
    source = json.loads((ROOT / 'expected-source.json').read_text())
    actual = {name: sha(REPO / name) for name in source['source_files']}
    if actual != source['source_files'] or sha(BINARY) != EXPECTED_BINARY:
        raise RuntimeError('Measurement source or validated binary differs')
    (ROOT / 'measurement-source.json').write_text(json.dumps(source, indent=2) + '\n')
    with tarfile.open(ROOT / 'source.tar.gz', 'w:gz') as archive:
        for name in sorted(actual):
            archive.add(REPO / name, arcname=name)
    (ROOT / 'resources-before.json').write_text(json.dumps(resources(), indent=2) + '\n')
    provenance = dict(binary_sha256=EXPECTED_BINARY, source_commit=source['commit'],
                      commands=[capture(cmd) for cmd in (
                          ['g++', '--version'], ['rustc', '+stable', '-vV'],
                          ['ldd', str(BINARY)], [str(BINARY), '--list-indexes'])],
                      cmake_cache=(BINARY.parent / 'CMakeCache.txt').read_text(),
                      shared_host=True, frequency_locked=False, cpus_reserved=False,
                      cpu_list=[2, 3, 4, 5, 6, 7, 8, 9], numa_node=0)
    (ROOT / 'build-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    # Keep the exact linked executable private, outside the public export.
    (ROOT / 'binaries').mkdir()
    (ROOT / 'binaries/mvcc_bench').write_bytes(BINARY.read_bytes())
    os.chmod(ROOT / 'binaries/mvcc_bench', 0o755)
    status = dict(status='running', pid=os.getpid(), started_at=time.time(),
                  completed_groups=[], planned_processes=300, planned_phase_rows=840)

    def save():
        (ROOT / 'status.json').write_text(json.dumps(status, indent=2) + '\n')

    save()
    try:
        for group in ('oltp', 'history'):
            status['active_group'] = group
            save()
            command = ['python3', '-u', 'scripts/mvcc_matrix.py', '--binary', str(BINARY),
                       '--output', str(ROOT / (group + '-1m')), '--group', group,
                       '--keys', '1000000', '--ops', '1000000', '--repeats', '3',
                       '--threads', '1,4,8', '--cpus', '2,3,4,5,6,7,8,9', '--numa-node', '0']
            (ROOT / (group + '-command.json')).write_text(json.dumps(command, indent=2) + '\n')
            with (ROOT / (group + '.log')).open('w') as stream:
                subprocess.run(command, cwd=REPO, env=ENV, stdout=stream,
                               stderr=subprocess.STDOUT, check=True)
            status['completed_groups'].append(group)
            save()
        status['active_group'] = 'validation'
        save()
        command = ['python3', 'scripts/summarize_mvcc.py', str(ROOT / 'oltp-1m'),
                   str(ROOT / 'history-1m'), '--output', str(ROOT / 'summary')]
        with (ROOT / 'summary.log').open('w') as stream:
            subprocess.run(command, cwd=REPO, env=ENV, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        if {name: sha(REPO / name) for name in actual} != actual or sha(BINARY) != EXPECTED_BINARY:
            raise RuntimeError('Source/binary changed during measurement')
        status['status'] = 'complete'
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        status['finished_at'] = time.time()
        save()
        (ROOT / 'resources-after.json').write_text(json.dumps(resources(), indent=2) + '\n')


if __name__ == '__main__':
    main()
