#!/usr/bin/env python3
"""Validate complete MVCC matrices and write median/IQR CSV and Markdown."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


PHASES = {1: ('batch_load', 'get_latest', 'get_snapshot', 'scan_latest', 'scan_snapshot'),
          3: ('batch_load', 'freeze', 'flush_all_versions', 'destroy')}
SIGNATURE = ('requests', 'point_reads', 'scan_requests', 'written_versions', 'live_hits',
             'tombstone_hits', 'not_found', 'items', 'stored_versions', 'checksum', 'dataset_hash')
PMU = ('cycles_per_request', 'instructions_per_request', 'l1d_miss_per_request',
       'llc_miss_per_request', 'branch_miss_per_request', 'dtlb_miss_per_request')
METRICS = {
    'elapsed_ns': 'ns', 'throughput_requests_s': 'requests/s',
    'throughput_versions_s': 'written versions/s', 'items_s': 'items/s',
    'latency_p50_ns': 'ns', 'latency_p95_ns': 'ns', 'latency_p99_ns': 'ns',
    'cycles_per_request': 'cycles/request', 'instructions_per_request': 'instructions/request',
    'ipc': 'instructions/cycle', 'l1d_miss_per_request': 'misses/request',
    'llc_miss_per_request': 'misses/request', 'branch_miss_per_request': 'misses/request',
    'dtlb_miss_per_request': 'misses/request', 'rss_retained_delta_bytes': 'bytes',
    'bytes_per_user_key': 'bytes/user key', 'bytes_per_version': 'bytes/version',
    'backend_retained_bytes': 'bytes', 'concurrent_overlap_ns': 'ns', 'writer_elapsed_ns': 'ns',
    'versions_tested': 'versions',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(root):
    meta = json.loads((root / 'metadata.json').read_text())
    args = meta['arguments']
    require(meta['status'] == 'complete', f'{root}: run is not complete')
    listing = [line.split('\t') for line in meta['adapter_listing'].splitlines()]
    available = [fields[0] for fields in listing if fields[1] == 'available']
    native = {fields[0] for fields in listing if fields[1] == 'available' and
              'native_concurrent=1' in fields[3:]}
    indexes = args['indexes'].split(',') if args.get('indexes') else available
    profiles = args['profiles'].split(',')
    threads = [int(value) for value in args['threads'].split(',')]
    repeats = int(args['repeats'])
    require(len(set(indexes)) == len(indexes) and set(indexes) <= set(available),
            f'{root}: duplicate or unavailable index')
    require(len(set(profiles)) == len(profiles) and set(profiles) <= set(meta['profiles']),
            f'{root}: duplicate or missing profile')
    require(repeats > 0 and len(set(threads)) == len(threads) and min(threads) > 0,
            f'{root}: invalid repetitions/workers')
    expected = set()
    processes = 0
    for profile in profiles:
        for stage in (1, 2, 3):
            for workers in threads if stage == 2 else (1,):
                phases = (('mixed_snapshot',) if workers == 1 else
                          ('swmr_total', 'swmr_writer_batch', 'swmr_readers')) if stage == 2 else PHASES[stage]
                for index in indexes:
                    if workers > 1 and index not in native:
                        continue
                    for repeat in range(1, repeats + 1):
                        processes += 1
                        expected.update((profile, stage, workers, index, repeat, phase) for phase in phases)
    require(meta['completed_processes'] == meta['planned_processes'] == processes,
            f'{root}: process count differs from declared matrix')
    with (root / 'raw.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    actual, checks = set(), {}
    for row in rows:
        key = (row['profile'], int(row['stage']), int(row['scenario_threads']),
               row['index'], int(row['repeat']), row['phase'])
        require(key in expected and key not in actual, f'{root}: unexpected/duplicate row {key}')
        actual.add(key)
        profile, stage, workers, index, repeat, phase = key
        require(row['schema_version'] == 'mvcc-v1', f'{root}: wrong CSV schema')
        service_workers = 1 if phase == 'swmr_writer_batch' else workers - 1 if phase == 'swmr_readers' else workers
        require(int(row['threads']) == service_workers, f'{root}: wrong service worker count {key}')
        require(int(row['user_keys']) == int(args['keys']) and int(row['seed']) == 41 + repeat,
                f'{root}: wrong dataset size/seed {key}')
        for name, value in meta['profiles'][profile].items():
            field = 'initial_versions_per_key' if name == 'versions' else name
            require(row[field] == str(value), f'{root}: profile field differs: {field}, {key}')
        representation = 'user_key_chain' if index.startswith('cse_') else 'internal_key'
        require(row['representation'] == representation, f'{root}: representation differs {key}')
        group = (profile, stage, workers, repeat, phase)
        signature = tuple(row[name] for name in SIGNATURE)
        require(group not in checks or checks[group] == signature, f'{root}: contents/counts differ {group}')
        checks[group] = signature
        for metric in METRICS:
            if row[metric]:
                require(math.isfinite(float(row[metric])), f'{root}: nonfinite {metric} {key}')
        require(int(row['elapsed_ns']) > 0, f'{root}: invalid duration {key}')
    require(actual == expected, f'{root}: missing {len(expected - actual)} matrix rows')
    evidence = dict(cohort=root.name, processes=processes, phase_rows=len(rows),
                    comparison_groups=len(checks), binary_sha256=meta['binary_sha256'],
                    raw_sha256=hashlib.sha256((root / 'raw.csv').read_bytes()).hexdigest(),
                    pmu_rows={name: sum(bool(row[name]) for row in rows) for name in PMU})
    return meta, rows, evidence


def table(header, rows):
    return '\n'.join(['| ' + ' | '.join(header) + ' |',
                      '| ' + ' | '.join(['---'] * len(header)) + ' |',
                      *['| ' + ' | '.join(map(str, row)) + ' |' for row in rows]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, nargs='+', help='Completed mvcc_matrix output directories')
    parser.add_argument('--output', type=Path, help='New derived report directory')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if not args.validate_only and not args.output:
        parser.error('--output is required unless --validate-only')
    cohorts, groups, evidence = {}, defaultdict(list), []
    for source in args.inputs:
        root = source.resolve()
        require(root.name not in cohorts, f'duplicate cohort name: {root.name}')
        meta, rows, proof = validate(root)
        cohorts[root.name] = meta
        evidence.append(proof)
        for row in rows:
            groups[(root.name, row['profile'], int(row['stage']), int(row['scenario_threads']),
                    row['phase'], row['index'])].append(row)
    validation = dict(status='complete', processes=sum(item['processes'] for item in evidence),
                      phase_rows=sum(item['phase_rows'] for item in evidence), cohorts=evidence)
    if args.validate_only:
        print(json.dumps(validation, indent=2))
        return
    stats = {}
    for key, rows in groups.items():
        for metric in METRICS:
            values = [float(row[metric]) for row in rows if row[metric]]
            if not values:
                continue
            q1, _, q3 = statistics.quantiles(values, n=4, method='inclusive') if len(values) > 1 else [values[0]] * 3
            stats[(*key, metric)] = dict(samples=len(values), median=statistics.median(values),
                                         q1=q1, q3=q3, min=min(values), max=max(values))
    destination = args.output.resolve()
    require(all(destination != source.resolve() for source in args.inputs), 'output must not overwrite measured input')
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / 'summary.csv').open('w', newline='') as stream:
        fields = ['cohort', 'profile', 'stage', 'scenario_threads', 'phase', 'index', 'metric',
                  'unit', 'samples', 'median', 'q1', 'q3', 'min', 'max']
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        for (cohort, profile, stage, workers, phase, index, metric), values in sorted(stats.items()):
            writer.writerow(dict(cohort=cohort, profile=profile, stage=stage, scenario_threads=workers,
                                 phase=phase, index=index, metric=metric, unit=METRICS[metric], **values))
    (destination / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    sections = ['# MVCC benchmark results',
                f"Validated **{validation['processes']} processes / {validation['phase_rows']} phase rows**.",
                'Each table reports the median of independent fresh-process repetitions. '
                'summary.csv includes quartiles, min/max and sample counts. '
                'Quartiles are descriptive, not confidence intervals. '
                'Compare candidates within a cohort; different key populations are kept separate.',
                'The prefix profile changes both user-key width and shared-prefix length; '
                'the deep profile changes both version depth and snapshot lag. '
                'These are representative configurations, not independent estimates of each factor. '
                'Actual live/tombstone/missing counts remain in raw CSV.',
                'Writes are batch submissions, not atomic transactions. GetAt materializes values; '
                'scans hash visible live rows; flush hashes every retained version and tombstone. '
                'Adapter/encoding/FFI costs are included. No WAL, SST encoding or disk I/O is measured. '
                'SWMR uses one writer and N-1 readers at a fixed historical snapshot; '
                'single-worker mixed timing is a different interleaving. '
                'Reader service throughput uses the complete group wall interval, including the tail after writing.',
                'The shared host has CPU/NUMA binding but no frequency lock or reserved CPUs. '
                'Stage-1 scans have 1024 calls and about 16 latency samples; their p99 is not a stable tail estimate. '
                'Aggregate SWMR latency is intentionally absent. Reader service latency mixes Get and Scan. '
                'RSS deltas include allocator/runtime retention and are measured after input preparation. '
                'CSE backend accounting is not interchangeable with RSS. '
                'Phase elapsed time includes PMU start/stop and sampling setup. '
                'For a one-request Freeze phase this overhead dominates; the separately sampled call '
                'excludes PMU control but still includes clock/call instrumentation. '
                'Neither is a stable native-only Freeze latency estimate. '
                'OceanBase is the KeyBtree core port with InternalKey visibility, not full ObMemtable; '
                'its common GetAt includes filling the first native 225-entry iterator batch.']
    for cohort, meta in cohorts.items():
        options = meta['arguments']
        indexes = options['indexes'].split(',') if options.get('indexes') else [
            line.split('\t')[0] for line in meta['adapter_listing'].splitlines() if line.split('\t')[1] == 'available']
        workers = [int(value) for value in options['threads'].split(',')]
        for profile, config in meta['profiles'].items():
            def cell(index, phase, metric, stage=1, count=1, scale=1):
                value = stats.get((cohort, profile, stage, count, phase, index, metric))
                return f"{value['median'] / scale:.3f}" if value else '—'
            sections.append(f"## {cohort}: {profile}\n\n"
                            f"User keys: {options['keys']:,}; operation budget: {options['ops']:,}; "
                            f"repetitions: {options['repeats']}. Profile: `{json.dumps(config, sort_keys=True)}`.")
            sections.append('### Single-thread operations\n\n' + table(
                ['Index', 'Load Mversions/s', 'Latest Get Mreq/s', 'Historical Get Mreq/s',
                 'Latest scan Mrows/s', 'Historical scan Mrows/s', 'RSS MiB after load', 'Bytes/version'],
                [[index, cell(index, 'batch_load', 'throughput_versions_s', scale=1e6),
                  cell(index, 'get_latest', 'throughput_requests_s', scale=1e6),
                  cell(index, 'get_snapshot', 'throughput_requests_s', scale=1e6),
                  cell(index, 'scan_latest', 'items_s', scale=1e6),
                  cell(index, 'scan_snapshot', 'items_s', scale=1e6),
                  cell(index, 'batch_load', 'rss_retained_delta_bytes', scale=2**20),
                  cell(index, 'batch_load', 'bytes_per_version')] for index in indexes]))
            sections.append('### Fixed-snapshot mixed / SWMR\n\n' + table(
                ['Index', *[f'{count} workers Mreq/s' for count in workers],
                 *[f'{count} workers: readers Mreq/s' for count in workers if count > 1],
                 *[f'{count} workers: writer Mversions/s' for count in workers if count > 1]],
                [[index, *[cell(index, 'mixed_snapshot' if count == 1 else 'swmr_total',
                               'throughput_requests_s', stage=2, count=count, scale=1e6) for count in workers],
                  *[cell(index, 'swmr_readers', 'throughput_requests_s', stage=2, count=count, scale=1e6)
                    for count in workers if count > 1],
                  *[cell(index, 'swmr_writer_batch', 'throughput_versions_s', stage=2, count=count, scale=1e6)
                    for count in workers if count > 1]] for index in indexes]))
            sections.append('### Lifecycle\n\n' + table(
                ['Index', 'Load s', 'Freeze phase µs', 'Freeze sampled call µs', 'Flush Mversions/s', 'Destroy s'],
                [[index, cell(index, 'batch_load', 'elapsed_ns', stage=3, scale=1e9),
                  cell(index, 'freeze', 'elapsed_ns', stage=3, scale=1e3),
                  cell(index, 'freeze', 'latency_p50_ns', stage=3, scale=1e3),
                  cell(index, 'flush_all_versions', 'items_s', stage=3, scale=1e6),
                  cell(index, 'destroy', 'elapsed_ns', stage=3, scale=1e9)] for index in indexes]))
    (destination / 'report.md').write_text('\n\n'.join(sections) + '\n')
    print(f"Validated {validation['processes']} processes / {validation['phase_rows']} rows; "
          f"report: {destination / 'report.md'}")


if __name__ == '__main__':
    main()
