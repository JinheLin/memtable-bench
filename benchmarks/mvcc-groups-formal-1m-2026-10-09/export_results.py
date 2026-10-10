#!/usr/bin/env python3
"""Export completed public results, checking original process/source bytes."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import time

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    status = json.loads((ROOT / 'status.json').read_text())
    assert status['status'] == 'complete' and status['completed_groups'] == ['oltp', 'history']
    proof = json.loads((ROOT / 'summary/validation.json').read_text())
    assert proof['status'] == 'complete' and proof['processes'] == 300 and proof['phase_rows'] == 840
    source = json.loads((ROOT / 'measurement-source.json').read_text())
    with tarfile.open(ROOT / 'source.tar.gz') as archive:
        packed = {item.name: hashlib.sha256(archive.extractfile(item).read()).hexdigest()
                  for item in archive.getmembers() if item.isfile()}
    assert packed == source['source_files']
    destination = ROOT / 'public'
    destination.mkdir(exist_ok=False)
    records = []
    for group in ('oltp', 'history'):
        cohort = group + '-1m'
        measured = ROOT / cohort
        exported = destination / cohort
        exported.mkdir()
        metadata = json.loads((measured / 'metadata.json').read_text())
        assert metadata['source_files'] == source['source_files']
        assert metadata['binary_sha256'] == '7ecb7d29c148a27b7ba1975f77f72daf5e7ecbbca8ab953b48f5bf508c24fbe5'
        rows = list(csv.DictReader((measured / 'raw.csv').open()))
        signatures = {(r['profile'], r['stage'], r['scenario_threads'], r['index'], r['repeat'], r['phase']): r
                      for r in rows}
        assert len(signatures) == len(rows) == 420
        matched = 0
        csvs = sorted((measured / 'runs').glob('*.csv'))
        assert len(csvs) == metadata['completed_processes'] == 150
        for path in csvs:
            profile, stage, workers, index, repeat = path.stem.split('-')
            for original in csv.DictReader(path.open()):
                key = (profile, stage[1:], workers[1:], index, repeat[1:], original['phase'])
                combined = signatures[key]
                assert all(combined[k] == v for k, v in original.items()), path
                matched += 1
        assert matched == len(rows)
        files = {str(p.relative_to(measured)): sha(p) for p in sorted((measured / 'runs').iterdir())}
        assert len(files) == 450
        (exported / 'process-files-sha256.json').write_text(json.dumps(files, indent=2) + '\n')
        packed_path = exported / 'process-records.tar.gz'
        with tarfile.open(packed_path, 'w:gz') as archive:
            for name in files:
                archive.add(measured / name, arcname=name)
        with tarfile.open(packed_path) as archive:
            packed = {item.name: hashlib.sha256(archive.extractfile(item).read()).hexdigest()
                      for item in archive.getmembers() if item.isfile()}
        assert packed == files
        for name in ('metadata.json', 'raw.csv'):
            shutil.copy2(measured / name, exported / name)
        records.append(dict(cohort=cohort, processes=len(csvs), phase_rows=matched,
                            raw_matches_original_process_csv=True,
                            process_archive_bytes_verified=True,
                            raw_sha256=sha(exported / 'raw.csv')))
    shutil.copytree(ROOT / 'summary', destination / 'summary')
    for name in ('status.json', 'run_formal.py', 'export_results.py', 'measurement-source.json',
                 'source.tar.gz', 'build-provenance.json', 'resources-before.json',
                 'resources-after.json', 'launcher.log', 'oltp.log', 'history.log',
                 'oltp-command.json', 'history-command.json', 'summary.log',
                 'progress.py', 'progress.jsonl'):
        shutil.copy2(ROOT / name, destination / name)
    verification = dict(status='verified', verified_at=time.time(), model='mvcc-v2',
                        source_commit=source['commit'], source_snapshot_verified=True,
                        source_files=len(source['source_files']), cohorts=records,
                        processes=300, phase_rows=840,
                        all_cohorts_same_binary_and_source=True,
                        private_engine_sources_and_binary_excluded=True)
    (destination / 'records-verification.json').write_text(json.dumps(verification, indent=2) + '\n')
    print(json.dumps(verification, indent=2))


if __name__ == '__main__':
    main()
