"""Eligibility for the integrated implementations, checked against the binary."""
import csv
import hashlib
import json
import os

INDEXES = ['std_map', 'abseil_btree', 'tlx_btree', 'rocksdb_inlineskiplist',
           'btreeolc', 'unodb_art', 'masstree', 'hot', 'wormhole']
# Keep the historical default cohort stable. New index cores can be selected
# explicitly in sensitivity_matrix; mvcc_matrix discovers the binary's list.
KNOWN_INDEXES = frozenset([*INDEXES, 'oceanbase_keybtree'])
NATIVE_CONCURRENT = frozenset({'rocksdb_inlineskiplist', 'btreeolc', 'unodb_art',
                               'masstree', 'wormhole', 'oceanbase_keybtree'})
POLICY = 'native-concurrency-v1'


def eligible_indexes(indexes, workers):
    return [index for index in indexes if workers == 1 or index in NATIVE_CONCURRENT]


def validate_listing(listing, indexes):
    adapters = {}
    for line in listing.splitlines():
        fields = line.split('\t')
        info = dict(field.split('=', 1) for field in fields[3:])
        if info.get('native_concurrent') != str(int(fields[0] in NATIVE_CONCURRENT)):
            raise RuntimeError(f'concurrency capability differs for {fields[0]}; rebuild the binary')
        adapters[fields[0]] = fields[1] == 'available'
    missing = [index for index in indexes if not adapters.get(index)]
    if missing:
        raise RuntimeError(f'requested adapters unavailable: {missing}\n{listing}')


def validate_rows(meta, rows, workloads, phases, configs=('',)):
    """Validate old full matrices and new per-scenario participant matrices."""
    indexes = meta['indexes']
    participants = {name: list(indexes) for name, _, _ in workloads}
    if 'concurrency_policy' in meta:
        assert meta['concurrency_policy'] == POLICY, 'unknown concurrency policy'
        participants = {name: eligible_indexes(indexes, workers)
                        for name, _, workers in workloads}
        assert meta['scenario_indexes'] == participants, 'incorrect scenario participants'
    expected = {(config, name, phase, index, repeat)
                for config in configs for name, stage, _ in workloads
                for phase in phases[stage] for index in participants[name]
                for repeat in range(1, meta['repeats'] + 1)}
    actual, checks = set(), {}
    counts = {name: (stage, workers) for name, stage, workers in workloads}
    for row in rows:
        key = (row.get('config_id', ''), row['scenario'], row['phase'],
               row['index'], int(row['repeat']))
        assert key not in actual, f'duplicate matrix row: {key}'
        actual.add(key)
        assert (int(row['stage']), int(row['threads'])) == counts[row['scenario']]
        group = (key[0], row['scenario'], row['phase'], row['repeat'])
        observed = tuple(row[field] for field in ('ops', 'items_scanned', 'checksum'))
        if 'dataset_hash' in row:
            observed += (row['dataset_hash'],)
        assert group not in checks or checks[group] == observed, f'checksum mismatch: {group}'
        checks[group] = observed
    assert actual == expected, f'matrix differs: missing {len(expected-actual)}, extra {len(actual-expected)}'
    processes = sum(len(participants[name]) for name, _, _ in workloads) * len(configs) * meta['repeats']
    assert meta['completed_processes'] == meta['planned_processes'] == processes


def select_rows(rows, source, destination):
    """Keep legacy raw data intact; report discarded wrapper-concurrency rows."""
    included, excluded = [], []
    for row in rows:
        assert row['index'] in KNOWN_INDEXES, f'unknown adapter: {row["index"]}'
        allowed = row['index'] in eligible_indexes([row['index']], int(row['threads']))
        if allowed and int(row['threads']) > 1:
            assert row['adapter_mode'].startswith('native_'), 'native adapter uses a wrapper concurrency mode'
        (included if allowed else excluded).append(row)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / 'excluded.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(excluded)
    identity = lambda row: (row.get('config_id', ''), row['scenario'], row['index'], row['repeat'])
    selection = dict(concurrency_policy=POLICY,
                     source_directory=os.path.relpath(source, destination),
                     raw_sha256=hashlib.sha256((source / 'raw.csv').read_bytes()).hexdigest(),
                     included_phase_rows=len(included), excluded_phase_rows=len(excluded),
                     included_processes=len({identity(row) for row in included}),
                     excluded_processes=len({identity(row) for row in excluded}),
                     native_concurrent_indexes=sorted(NATIVE_CONCURRENT.intersection(row['index'] for row in rows)),
                     exclusion_reason='threads > 1 without native concurrency in the integrated implementation',
                     measurement_rerun=False)
    (destination / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n')
    return included, excluded, selection
