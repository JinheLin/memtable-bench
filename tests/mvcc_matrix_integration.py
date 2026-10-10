#!/usr/bin/env python3
"""Check group planning, actual execution, and rejection of invalid MVCC evidence."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
binary = str(Path(sys.argv[1]).resolve())
runner = [sys.executable, str(repo/'scripts/mvcc_matrix.py'), '--binary', binary]
summarizer = [sys.executable, str(repo/'scripts/summarize_mvcc.py')]
listing = subprocess.check_output([binary, '--list-indexes'], text=True)
available = sum(line.split('\t')[1] == 'available' for line in listing.splitlines())

with tempfile.TemporaryDirectory(prefix='mvcc-groups-') as directory:
    root = Path(directory)
    quick = json.loads(subprocess.check_output([*runner, '--output', str(root/'unused'), '--list-plan'], text=True))
    assert quick['suite'] == 'quick' and quick['repeats'] == 1 and quick['threads'] == [8]
    assert quick['keys'] == quick['ops'] == 100000
    assert quick['profiles'] == ['oltp_uniform', 'oltp_zipf', 'history_v16']
    assert quick['processes'] == 9*available and quick['phase_rows'] == 30*available
    assert quick['total_prefill_versions'] == 6000000*available
    for group in ('oltp', 'history', 'all'):
        plan = json.loads(subprocess.check_output([*runner, '--output', str(root/'unused'),
                          '--suite', 'full', '--group', group, '--list-plan'], text=True))
        multiplier = 2 if group == 'all' else 1
        assert plan['processes'] == 30*available*multiplier
        assert plan['phase_rows'] == 84*available*multiplier
        assert plan['total_prefill_versions'] == (20000000 if group == 'oltp' else
                                                  400000000 if group == 'history' else 420000000)*available*3
        views = {config['read_view'] for config in plan['configurations'].values()}
        assert views == ({'latest', 'historical'} if group == 'all' else
                         {'latest' if group == 'oltp' else 'historical'})
    invalid = root/'invalid'
    result = subprocess.run([*runner, '--output', str(invalid), '--group', 'oltp',
                             '--profiles', 'history_v16'], capture_output=True)
    assert result.returncode != 0 and not invalid.exists()
    measured = root/'measured'
    command = [*runner, '--output', str(measured), '--suite', 'full', '--indexes', 'rocksdb_inlineskiplist',
               '--profiles', 'oltp_uniform,history_v16', '--threads', '1,4',
               '--keys', '128', '--ops', '1200', '--repeats', '1']
    subprocess.run(command,
                   stdout=subprocess.DEVNULL, check=True)
    proof = json.loads(subprocess.check_output([*summarizer, str(measured), '--validate-only']))
    assert proof['processes'] == 8 and proof['phase_rows'] == 22
    assert proof['cohorts'][0]['groups'] == {
        'oltp': {'processes': 4, 'phase_rows': 11},
        'history': {'processes': 4, 'phase_rows': 11}}
    summary = root/'summary'
    subprocess.run([*summarizer, str(measured), '--output', str(summary)],
                   stdout=subprocess.DEVNULL, check=True)
    report = (summary/'report.md').read_text()
    assert 'Latest published batch: mixed / SWMR' in report
    assert 'Fixed historical snapshot: mixed / SWMR' in report
    assert 'Latest visibility evidence' in report
    assert 'history_v16' not in (summary/'report-oltp.md').read_text()
    assert 'oltp_uniform' not in (summary/'report-history.md').read_text()
    assert '4 processes / 11 phase rows' in (summary/'report-oltp.md').read_text()
    assert proof['cohorts'][0]['cross_adapter_validation'] == {
        'content_groups': 20, 'latest_scheduled_count_groups': 2, 'oracle_verified_rows': 14}
    process_files = {path: path.read_bytes() for path in (measured/'runs').glob('*.csv')}
    subprocess.run([*command, '--resume'], stdout=subprocess.DEVNULL, check=True)
    meta = json.loads((measured/'metadata.json').read_text())
    assert meta['invocations'][-1]['reused_processes'] == 8
    assert meta['invocations'][-1]['executed_processes'] == 0
    assert all(path.read_bytes() == data for path, data in process_files.items())
    assert len(meta['process_wall_seconds']) == 8 and min(meta['process_wall_seconds'].values()) > 0
    # Resume must reject changed workloads and corrupted completed bytes.
    result = subprocess.run([*command, '--ops', '1201', '--resume'], capture_output=True)
    assert result.returncode != 0 and b'arguments changed' in result.stderr
    path, data = next(iter(process_files.items()))
    path.write_bytes(data + b'\n')
    result = subprocess.run([*command, '--resume'], capture_output=True)
    assert result.returncode != 0 and b'evidence differs' in result.stderr
    path.write_bytes(data)
    # An interrupted job has no completion marker. Retry only it and preserve
    # its partial command/log/CSV; all other process evidence stays untouched.
    marker = path.with_suffix('.complete.json')
    marker.unlink()
    subprocess.run([*command, '--resume'], stdout=subprocess.DEVNULL, check=True)
    meta = json.loads((measured/'metadata.json').read_text())
    assert meta['invocations'][-1]['reused_processes'] == 7
    assert meta['invocations'][-1]['executed_processes'] == 1
    assert len(list((measured/'failed-attempts').iterdir())) == 1
    subprocess.run([*summarizer, str(measured), '--validate-only'], stdout=subprocess.DEVNULL, check=True)
    stage_only = root/'stage-only'
    subprocess.run([*runner, '--output', str(stage_only), '--indexes', 'rocksdb_inlineskiplist',
                    '--profiles', 'oltp_uniform,history_v16', '--stages', '1', '--keys', '128', '--ops', '1200'],
                   stdout=subprocess.DEVNULL, check=True)
    stage_proof = json.loads(subprocess.check_output([*summarizer, str(stage_only), '--validate-only']))
    assert stage_proof['processes'] == 2 and stage_proof['phase_rows'] == 6
    for stages in ('0', '1,1', '1,4'):
        result = subprocess.run([*runner, '--output', str(root/'unused'), '--stages', stages, '--list-plan'],
                                capture_output=True)
        assert result.returncode != 0
    with (summary/'summary.csv').open() as stream:
        assert {row['workload_group'] for row in csv.DictReader(stream)} == {'oltp', 'history'}
    raw = measured/'raw.csv'
    original = raw.read_text()
    rows = list(csv.DictReader(original.splitlines()))
    target = next(i for i, row in enumerate(rows) if row['phase'] == 'mixed_latest')
    for field, value in [('checksum', str(int(rows[target]['checksum']) ^ 1)),
                         ('read_view', 'historical'), ('snapshot_min_ts', '0'),
                         ('workload_group', 'history')]:
        altered = [dict(row) for row in rows]
        altered[target][field] = value
        with raw.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0]); writer.writeheader(); writer.writerows(altered)
        result = subprocess.run([*summarizer, str(measured), '--validate-only'], capture_output=True)
        assert result.returncode != 0, field
    raw.write_text(original)
print('Quick/full plans, stage subsets, verified resume/retry, separate reports and evidence rejection passed')
