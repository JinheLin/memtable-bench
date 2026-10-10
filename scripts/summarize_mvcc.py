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
from mvcc_workloads import comparison_fields, phases


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
    'snapshot_min_ts': 'timestamp', 'snapshot_max_ts': 'timestamp',
    'reads_with_newer_snapshot': 'requests', 'newer_version_hits': 'point requests',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(root):
    meta = json.loads((root / 'metadata.json').read_text())
    args = meta['arguments']
    current = meta['model'] == 'mvcc-v2'
    require(current or meta['model'] == 'mvcc-v1', f'{root}: unknown workload protocol')
    require(meta['status'] == 'complete', f'{root}: run is not complete')
    listing = [line.split('\t') for line in meta['adapter_listing'].splitlines()]
    available = [fields[0] for fields in listing if fields[1] == 'available']
    native = {fields[0] for fields in listing if fields[1] == 'available' and
              'native_concurrent=1' in fields[3:]}
    indexes = args['indexes'].split(',') if args.get('indexes') else available
    profiles = args['profiles'].split(',')
    threads = [int(value) for value in args['threads'].split(',')]
    repeats = int(args['repeats'])
    stages = [int(value) for value in args.get('stages', '1,2,3').split(',')]
    require(bool(stages) and len(set(stages)) == len(stages) and set(stages) <= {1,2,3},
            f'{root}: invalid stages')
    require(len(set(indexes)) == len(indexes) and set(indexes) <= set(available),
            f'{root}: duplicate or unavailable index')
    require(len(set(profiles)) == len(profiles) and set(profiles) <= set(meta['profiles']),
            f'{root}: duplicate or missing profile')
    require(repeats > 0 and len(set(threads)) == len(threads) and min(threads) > 0,
            f'{root}: invalid repetitions/workers')
    expected = set()
    processes = 0
    for profile in profiles:
        for stage in stages:
            for workers in threads if stage == 2 else (1,):
                config = meta['profiles'][profile]
                expected_phases = phases(stage, workers, config.get('read_view'), config.get('read_percent', 80))
                for index in indexes:
                    if workers > 1 and index not in native:
                        continue
                    for repeat in range(1, repeats + 1):
                        processes += 1
                        expected.update((profile, stage, workers, index, repeat, phase) for phase in expected_phases)
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
        require(row['schema_version'] == ('mvcc-v2' if current else 'mvcc-v1'), f'{root}: wrong CSV schema')
        service_workers = 1 if phase == 'swmr_writer_batch' else workers - 1 if phase == 'swmr_readers' else workers
        require(int(row['threads']) == service_workers, f'{root}: wrong service worker count {key}')
        require(int(row['user_keys']) == int(args['keys']) and int(row['seed']) == 41 + repeat,
                f'{root}: wrong dataset size/seed {key}')
        for name, value in meta['profiles'][profile].items():
            field = 'initial_versions_per_key' if name == 'versions' else name
            require(row[field] == str(value), f'{root}: profile field differs: {field}, {key}')
        if current:
            require(row['workload_group'] == meta['profile_groups'][profile], f'{root}: wrong group {key}')
            oracle_required = stage == 2 or phase.startswith(('get_', 'scan_')) or phase == 'flush_all_versions'
            require(not oracle_required or row['oracle_checksum'] == row['checksum'],
                    f'{root}: oracle missing/different {key}')
            if int(row['point_reads']) + int(row['scan_requests']):
                lo, hi = int(row['snapshot_min_ts']), int(row['snapshot_max_ts'])
                initial = int(row['user_keys']) * int(row['initial_versions_per_key'])
                require(0 <= lo <= hi, f'{root}: invalid observed snapshots {key}')
                if row['read_view'] == 'historical' or stage != 2:
                    require(lo == hi == int(row['snapshot_ts']), f'{root}: fixed view moved {key}')
                else:
                    require(initial <= lo <= hi <= int(row['stored_versions']),
                            f'{root}: latest snapshot outside write history {key}')
            require(int(row['reads_with_newer_snapshot']) <= int(row['point_reads']) + int(row['scan_requests']) and
                    int(row['newer_version_hits']) <= int(row['live_hits']) + int(row['tombstone_hits']),
                    f'{root}: invalid latest visibility counts {key}')
            if row['read_view'] == 'historical' or stage != 2:
                require(row['reads_with_newer_snapshot'] == row['newer_version_hits'] == '0',
                        f'{root}: unexpected newly written visibility {key}')
        representation = 'user_key_chain' if index.startswith('cse_') else 'internal_key'
        require(row['representation'] == representation, f'{root}: representation differs {key}')
        group = (profile, stage, workers, repeat, phase)
        signature = tuple(row[name] for name in comparison_fields(row))
        require(group not in checks or checks[group] == signature, f'{root}: contents/counts differ {group}')
        checks[group] = signature
        for metric in METRICS:
            if row.get(metric):
                require(math.isfinite(float(row[metric])), f'{root}: nonfinite {metric} {key}')
        require(int(row['elapsed_ns']) > 0, f'{root}: invalid duration {key}')
    require(actual == expected, f'{root}: missing {len(expected - actual)} matrix rows')
    evidence = dict(cohort=root.name, processes=processes, phase_rows=len(rows),
                    comparison_groups=len(checks), binary_sha256=meta['binary_sha256'],
                    raw_sha256=hashlib.sha256((root / 'raw.csv').read_bytes()).hexdigest(),
                    pmu_rows={name: sum(bool(row[name]) for row in rows) for name in PMU})
    if 'suite' in args:
        evidence['suite'] = args['suite']
        evidence['stages'] = stages
        evidence['repeats'] = repeats
    if current:
        evidence['groups'] = {group: dict(
            processes=len({(r['profile'], r['stage'], r['scenario_threads'], r['index'], r['repeat'])
                           for r in rows if r['workload_group'] == group}),
            phase_rows=sum(r['workload_group'] == group for r in rows))
            for group in sorted(set(meta['profile_groups'].values()))}
        evidence['cross_adapter_validation'] = dict(
            content_groups=sum(not (key[1] == 2 and key[-1] in ('swmr_total', 'swmr_readers') and
                                    meta['profiles'][key[0]]['read_view'] == 'latest') for key in checks),
            latest_scheduled_count_groups=sum(key[1] == 2 and key[-1] in ('swmr_total', 'swmr_readers') and
                                             meta['profiles'][key[0]]['read_view'] == 'latest' for key in checks),
            oracle_verified_rows=sum(bool(row['oracle_checksum']) for row in rows))
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
            values = [float(row[metric]) for row in rows if row.get(metric)]
            if not values:
                continue
            q1, _, q3 = statistics.quantiles(values, n=4, method='inclusive') if len(values) > 1 else [values[0]] * 3
            stats[(*key, metric)] = dict(samples=len(values), median=statistics.median(values),
                                         q1=q1, q3=q3, min=min(values), max=max(values))
    destination = args.output.resolve()
    require(all(destination != source.resolve() for source in args.inputs), 'output must not overwrite measured input')
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / 'summary.csv').open('w', newline='') as stream:
        fields = ['cohort', 'workload_group', 'profile', 'stage', 'scenario_threads', 'phase', 'index', 'metric',
                  'unit', 'samples', 'median', 'q1', 'q3', 'min', 'max']
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        for (cohort, profile, stage, workers, phase, index, metric), values in sorted(stats.items()):
            writer.writerow(dict(cohort=cohort, workload_group=cohorts[cohort].get('profile_groups', {}).get(profile, 'legacy'),
                                 profile=profile, stage=stage, scenario_threads=workers,
                                 phase=phase, index=index, metric=metric, unit=METRICS[metric], **values))
    (destination / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    sections = ['# MVCC benchmark results',
                f"Validated **{validation['processes']} processes / {validation['phase_rows']} phase rows**.",
                'Each table reports the median of independent fresh-process repetitions. '
                'summary.csv includes quartiles, min/max and sample counts. '
                'Quartiles are descriptive, not confidence intervals. '
                'Compare candidates within a cohort; different key populations are kept separate.',
                'Current groups are reported separately: OLTP captures the latest completed batch '
                'at each request start; history holds a fixed completed-round snapshot. '
                'Latest concurrent results are verified against an independent oracle using the exact '
                'captured timestamps after timing. Their visible values/hit counts/checksums can differ '
                'with scheduling; only deterministic request/write/dataset counts are compared across adapters. '
                'Fixed-view results retain cross-adapter content equality. '
                'Actual visibility counts and oracle checksums remain in raw CSV. '
                'Legacy mvcc-v1 archives retain their original both-view/fixed-snapshot protocol.',
                'Writes are batch submissions, not atomic transactions. GetAt materializes values; '
                'scans hash visible live rows; flush hashes every retained version and tombstone. '
                'Adapter/encoding/FFI costs are included. No WAL, SST encoding or disk I/O is measured. '
                'SWMR uses one writer and N-1 readers with the selected read view; '
                'single-worker mixed timing is a different interleaving. '
                'Reader service throughput uses the complete group wall interval, including the tail after writing.',
                'The shared host has CPU/NUMA binding but no frequency lock or reserved CPUs. '
                'Stage-1 scans have 1024 calls and about 16 latency samples; their p99 is not a stable tail estimate. '
                'Aggregate SWMR latency is intentionally absent. Reader service latency mixes Get and Scan. '
                'Current default mixed workloads use scan-percent=0 to keep their reader latency point-only; '
                'dedicated scans remain in stage 1. '
                'RSS deltas include allocator/runtime retention and are measured after input preparation. '
                'CSE backend accounting is not interchangeable with RSS. '
                'Phase elapsed time includes PMU start/stop and sampling setup. '
                'For a one-request Freeze phase this overhead dominates; the separately sampled call '
                'excludes PMU control but still includes clock/call instrumentation. '
                'Neither is a stable native-only Freeze latency estimate.']
    if any(key[-1] == 'oceanbase_keybtree' for key in groups):
        sections.append('This historical OceanBase candidate is the KeyBtree core port with '
                        'InternalKey visibility; its common GetAt includes filling the first '
                        'native 225-entry iterator batch.')
    preface_end = len(sections)
    group_sections = defaultdict(list)
    for cohort, meta in cohorts.items():
        options = meta['arguments']
        indexes = options['indexes'].split(',') if options.get('indexes') else [
            line.split('\t')[0] for line in meta['adapter_listing'].splitlines() if line.split('\t')[1] == 'available']
        workers = [int(value) for value in options['threads'].split(',')]
        stages = [int(value) for value in options.get('stages', '1,2,3').split(',')]
        for profile, config in meta['profiles'].items():
            section_begin = len(sections)
            view = config.get('read_view')
            group = meta.get('profile_groups', {}).get(profile, 'legacy')
            def cell(index, phase, metric, stage=1, count=1, scale=1):
                value = stats.get((cohort, profile, stage, count, phase, index, metric))
                return f"{value['median'] / scale:.3f}" if value else '—'
            sections.append(f"## {cohort}: {group} / {profile}\n\n"
                            f"User keys: {options['keys']:,}; operation budget: {options['ops']:,}; "
                            f"repetitions: {options['repeats']}. Profile: `{json.dumps(config, sort_keys=True)}`.")
            if 'suite' in options:
                sections.append(f"Suite: `{options['suite']}`; measured stages: `{options['stages']}`. " +
                                ('One repetition: screening/correctness evidence, not a stable performance ranking.'
                                 if options['repeats'] == 1 else ''))
            read_phases = [('Latest Get Mreq/s', 'get_latest', 'throughput_requests_s'),
                           ('Latest scan Mrows/s', 'scan_latest', 'items_s')] if view == 'latest' else [
                           ('Historical Get Mreq/s', 'get_snapshot', 'throughput_requests_s'),
                           ('Historical scan Mrows/s', 'scan_snapshot', 'items_s')]
            if view is None:
                read_phases = [('Latest Get Mreq/s', 'get_latest', 'throughput_requests_s'),
                               ('Historical Get Mreq/s', 'get_snapshot', 'throughput_requests_s'),
                               ('Latest scan Mrows/s', 'scan_latest', 'items_s'),
                               ('Historical scan Mrows/s', 'scan_snapshot', 'items_s')]
            if 1 in stages:
                sections.append('### Single-thread operations\n\n' + table(
                    ['Index', 'Load Mversions/s', *[label for label, _, _ in read_phases],
                     'RSS MiB after load', 'Bytes/version'],
                    [[index, cell(index, 'batch_load', 'throughput_versions_s', scale=1e6),
                      *[cell(index, phase, metric, scale=1e6) for _, phase, metric in read_phases],
                      cell(index, 'batch_load', 'rss_retained_delta_bytes', scale=2**20),
                      cell(index, 'batch_load', 'bytes_per_version')] for index in indexes]))
            mixed_phase = 'mixed_latest' if view == 'latest' else 'mixed_snapshot'
            if 2 in stages:
                sections.append(('### Latest published batch: mixed / SWMR' if view == 'latest' else
                                 '### Fixed historical snapshot: mixed / SWMR') + '\n\n' + table(
                    ['Index', *[f'{count} workers Mreq/s' for count in workers],
                     *[f'{count} workers: readers Mreq/s' for count in workers if count > 1],
                     *[f'{count} workers: writer Mversions/s' for count in workers if count > 1]],
                    [[index, *[cell(index, mixed_phase if count == 1 else 'swmr_total',
                                   'throughput_requests_s', stage=2, count=count, scale=1e6) for count in workers],
                      *[cell(index, 'swmr_readers', 'throughput_requests_s', stage=2, count=count, scale=1e6)
                        for count in workers if count > 1],
                      *[cell(index, 'swmr_writer_batch', 'throughput_versions_s', stage=2, count=count, scale=1e6)
                        for count in workers if count > 1]] for index in indexes]))
            if 2 in stages and view == 'latest':
                sections.append('### Latest visibility evidence\n\n' + table(
                    ['Index', 'Workers', 'Min observed snapshot', 'Max observed snapshot',
                     'Reads after newer publication', 'Point hits on new versions'],
                    [[index, count, *[cell(index, mixed_phase if count == 1 else 'swmr_total', metric,
                                           stage=2, count=count) for metric in
                        ('snapshot_min_ts', 'snapshot_max_ts', 'reads_with_newer_snapshot', 'newer_version_hits')]]
                     for index in indexes for count in workers]))
            if 3 in stages:
                sections.append('### Lifecycle\n\n' + table(
                    ['Index', 'Load s', 'Freeze phase µs', 'Freeze sampled call µs', 'Flush Mversions/s', 'Destroy s'],
                    [[index, cell(index, 'batch_load', 'elapsed_ns', stage=3, scale=1e9),
                      cell(index, 'freeze', 'elapsed_ns', stage=3, scale=1e3),
                      cell(index, 'freeze', 'latency_p50_ns', stage=3, scale=1e3),
                      cell(index, 'flush_all_versions', 'items_s', stage=3, scale=1e6),
                      cell(index, 'destroy', 'elapsed_ns', stage=3, scale=1e9)] for index in indexes]))
            group_sections[group].extend(sections[section_begin:])
    (destination / 'report.md').write_text('\n\n'.join(sections) + '\n')
    for group in ('oltp', 'history'):
        if group in group_sections:
            totals = {field: sum(cohort.get('groups', {}).get(group, {}).get(field, 0)
                                 for cohort in evidence) for field in ('processes', 'phase_rows')}
            (destination / f'report-{group}.md').write_text(
                '# MVCC ' + group + ' benchmark\n\n' +
                f"Validated group: **{totals['processes']} processes / {totals['phase_rows']} phase rows**.\n\n" +
                '\n\n'.join(sections[2:preface_end] + group_sections[group]) + '\n')
    print(f"Validated {validation['processes']} processes / {validation['phase_rows']} rows; "
          f"report: {destination / 'report.md'}")


if __name__ == '__main__':
    main()
