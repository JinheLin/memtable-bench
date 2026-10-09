"""Current MVCC groups and phase/comparison rules, including archive compatibility."""

COMMON = dict(key_size=16, value_size=32, batch_size=32, read_percent=80,
              scan_percent=0, delete_percent=10, miss_percent=10,
              scan_length=100, scan_ops=1024, key_layout='random', prefix_bytes=0, prefix_groups=1)
PROFILES = {
    'oltp_uniform': dict(COMMON, read_view='latest', versions=2, snapshot_lag=0,
                         distribution='uniform'),
    'oltp_zipf': dict(COMMON, read_view='latest', versions=2, snapshot_lag=0,
                      distribution='zipf'),
    'history_v16': dict(COMMON, read_view='historical', versions=16, snapshot_lag=15,
                        distribution='uniform'),
    'history_v64': dict(COMMON, read_view='historical', versions=64, snapshot_lag=63,
                        distribution='uniform'),
}
GROUPS = {'oltp': ('oltp_uniform', 'oltp_zipf'),
          'history': ('history_v16', 'history_v64')}
SIGNATURE = ('requests', 'point_reads', 'scan_requests', 'written_versions', 'live_hits',
             'tombstone_hits', 'not_found', 'items', 'stored_versions', 'checksum', 'dataset_hash')


def phases(stage, workers, read_view=None, read_percent=80):
    if stage == 1:
        if read_view is None:  # Captured mvcc-v1 runs measured both views.
            return ('batch_load', 'get_latest', 'get_snapshot', 'scan_latest', 'scan_snapshot')
        suffix = 'latest' if read_view == 'latest' else 'snapshot'
        return ('batch_load', 'get_' + suffix, 'scan_' + suffix)
    if stage == 3:
        return ('batch_load', 'freeze', 'flush_all_versions', 'destroy')
    if workers == 1:
        return ('mixed_latest' if read_view == 'latest' else 'mixed_snapshot',)
    if read_percent == 100:
        return ('parallel_readers',)
    return ('swmr_total', 'swmr_writer_batch', 'swmr_readers')


def comparison_fields(row):
    # Latest reads capture different published timestamps under different
    # schedules. Their contents are checked against each run's own oracle.
    if row.get('read_view') == 'latest' and row['phase'] in ('swmr_total', 'swmr_readers'):
        return ('requests', 'point_reads', 'scan_requests', 'written_versions',
                'stored_versions', 'dataset_hash')
    return SIGNATURE
