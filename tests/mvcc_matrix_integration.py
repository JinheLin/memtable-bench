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
    for group in ('oltp', 'history', 'all'):
        plan = json.loads(subprocess.check_output([*runner, '--output', str(root/'unused'),
                          '--group', group, '--list-plan'], text=True))
        multiplier = 2 if group == 'all' else 1
        assert plan['processes'] == 30*available*multiplier
        assert plan['phase_rows'] == 84*available*multiplier
        views = {config['read_view'] for config in plan['configurations'].values()}
        assert views == ({'latest', 'historical'} if group == 'all' else
                         {'latest' if group == 'oltp' else 'historical'})
    invalid = root/'invalid'
    result = subprocess.run([*runner, '--output', str(invalid), '--group', 'oltp',
                             '--profiles', 'history_v16'], capture_output=True)
    assert result.returncode != 0 and not invalid.exists()
    measured = root/'measured'
    subprocess.run([*runner, '--output', str(measured), '--indexes', 'rocksdb_inlineskiplist',
                    '--profiles', 'oltp_uniform,history_v16', '--threads', '1,4',
                    '--keys', '128', '--ops', '1200', '--repeats', '1'],
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
print('OLTP/history plans, execution, separate reports and invalid evidence rejection passed')
