# MVCC oltp benchmark

Validated group: **150 processes / 420 phase rows**.

Each table reports the median of independent fresh-process repetitions. summary.csv includes quartiles, min/max and sample counts. Quartiles are descriptive, not confidence intervals. Compare candidates within a cohort; different key populations are kept separate.

Current groups are reported separately: OLTP captures the latest completed batch at each request start; history holds a fixed completed-round snapshot. Latest concurrent results are verified against an independent oracle using the exact captured timestamps after timing. Their visible values/hit counts/checksums can differ with scheduling; only deterministic request/write/dataset counts are compared across adapters. Fixed-view results retain cross-adapter content equality. Actual visibility counts and oracle checksums remain in raw CSV. Legacy mvcc-v1 archives retain their original both-view/fixed-snapshot protocol.

Writes are batch submissions, not atomic transactions. GetAt materializes values; scans hash visible live rows; flush hashes every retained version and tombstone. Adapter/encoding/FFI costs are included. No WAL, SST encoding or disk I/O is measured. SWMR uses one writer and N-1 readers with the selected read view; single-worker mixed timing is a different interleaving. Reader service throughput uses the complete group wall interval, including the tail after writing.

The shared host has CPU/NUMA binding but no frequency lock or reserved CPUs. Stage-1 scans have 1024 calls and about 16 latency samples; their p99 is not a stable tail estimate. Aggregate SWMR latency is intentionally absent. Reader service latency mixes Get and Scan. Current default mixed workloads use scan-percent=0 to keep their reader latency point-only; dedicated scans remain in stage 1. RSS deltas include allocator/runtime retention and are measured after input preparation. CSE backend accounting is not interchangeable with RSS. Phase elapsed time includes PMU start/stop and sampling setup. For a one-request Freeze phase this overhead dominates; the separately sampled call excludes PMU control but still includes clock/call instrumentation. Neither is a stable native-only Freeze latency estimate.

## oltp-1m: oltp / oltp_uniform

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "delete_percent": 10, "distribution": "uniform", "key_layout": "random", "key_size": 16, "miss_percent": 10, "prefix_bytes": 0, "prefix_groups": 1, "read_percent": 80, "read_view": "latest", "scan_length": 100, "scan_ops": 1024, "scan_percent": 0, "snapshot_lag": 0, "value_size": 32, "versions": 2}`.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Latest scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.639 | 0.452 | 2.556 | 151.648 | 79.507 |
| btreeolc | 0.444 | 0.464 | 0.811 | 406.309 | 213.023 |
| unodb_art | 0.997 | 0.609 | 0.447 | 579.102 | 303.616 |
| wormhole | 1.144 | 0.587 | 1.135 | 218.105 | 114.350 |
| cse_crossbeam | 0.425 | 0.395 | 1.910 | 414.535 | 217.336 |

### Latest published batch: mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.363 | 1.382 | 2.091 | 1.371 | 2.075 | 0.518 | 0.519 |
| btreeolc | 0.341 | 1.356 | 1.468 | 1.346 | 1.457 | 0.367 | 0.364 |
| unodb_art | 0.519 | 1.813 | 2.894 | 1.799 | 2.871 | 0.755 | 0.718 |
| wormhole | 0.377 | 1.358 | 2.919 | 1.347 | 2.896 | 0.866 | 0.851 |
| cse_crossbeam | 0.302 | 1.214 | 1.513 | 1.204 | 1.501 | 0.374 | 0.375 |

### Latest visibility evidence

| Index | Workers | Min observed snapshot | Max observed snapshot | Reads after newer publication | Point hits on new versions |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 1 | 2000000.000 | 2200000.000 | 799962.000 | 67463.000 |
| rocksdb_inlineskiplist | 4 | 2000000.000 | 2200000.000 | 799931.000 | 88291.000 |
| rocksdb_inlineskiplist | 8 | 2000000.000 | 2131904.000 | 799768.000 | 44556.000 |
| btreeolc | 1 | 2000000.000 | 2200000.000 | 799962.000 | 67463.000 |
| btreeolc | 4 | 2000000.000 | 2200000.000 | 799913.000 | 72564.000 |
| btreeolc | 8 | 2000000.000 | 2092640.000 | 799693.000 | 31498.000 |
| unodb_art | 1 | 2000000.000 | 2200000.000 | 799962.000 | 67463.000 |
| unodb_art | 4 | 2000000.000 | 2200000.000 | 799948.000 | 89805.000 |
| unodb_art | 8 | 2000000.000 | 2135424.000 | 799714.000 | 43622.000 |
| wormhole | 1 | 2000000.000 | 2200000.000 | 799962.000 | 67463.000 |
| wormhole | 4 | 2000000.000 | 2200000.000 | 799987.000 | 118450.000 |
| wormhole | 8 | 2000000.000 | 2200000.000 | 799964.000 | 83077.000 |
| cse_crossbeam | 1 | 2000000.000 | 2200000.000 | 799962.000 | 67463.000 |
| cse_crossbeam | 4 | 2000000.000 | 2200000.000 | 799913.000 | 79112.000 |
| cse_crossbeam | 8 | 2000000.000 | 2108256.000 | 799769.000 | 36932.000 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 3.129 | 25.809 | 0.155 | 5.610 | 0.000 |
| btreeolc | 4.534 | 24.902 | 0.256 | 3.849 | 0.086 |
| unodb_art | 2.057 | 24.843 | 0.406 | 1.639 | 0.832 |
| wormhole | 1.759 | 25.271 | 0.308 | 5.405 | 0.837 |
| cse_crossbeam | 4.796 | 25.608 | 0.496 | 3.535 | 0.751 |

## oltp-1m: oltp / oltp_zipf

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "delete_percent": 10, "distribution": "zipf", "key_layout": "random", "key_size": 16, "miss_percent": 10, "prefix_bytes": 0, "prefix_groups": 1, "read_percent": 80, "read_view": "latest", "scan_length": 100, "scan_ops": 1024, "scan_percent": 0, "snapshot_lag": 0, "value_size": 32, "versions": 2}`.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Latest scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.644 | 0.744 | 3.294 | 151.590 | 79.477 |
| btreeolc | 0.445 | 0.777 | 0.886 | 406.309 | 213.023 |
| unodb_art | 1.038 | 0.967 | 0.474 | 579.102 | 303.616 |
| wormhole | 1.150 | 0.750 | 1.404 | 218.109 | 114.352 |
| cse_crossbeam | 0.422 | 0.662 | 2.518 | 414.535 | 217.336 |

### Latest published batch: mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.582 | 2.127 | 3.260 | 2.110 | 3.235 | 0.817 | 0.810 |
| btreeolc | 0.541 | 2.110 | 2.128 | 2.093 | 2.112 | 0.524 | 0.528 |
| unodb_art | 0.746 | 2.465 | 4.200 | 2.445 | 4.167 | 1.040 | 1.043 |
| wormhole | 0.546 | 1.906 | 3.982 | 1.891 | 3.951 | 1.080 | 1.002 |
| cse_crossbeam | 0.502 | 1.871 | 2.277 | 1.857 | 2.260 | 0.564 | 0.565 |

### Latest visibility evidence

| Index | Workers | Min observed snapshot | Max observed snapshot | Reads after newer publication | Point hits on new versions |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 1 | 2000000.000 | 2200000.000 | 799962.000 | 570463.000 |
| rocksdb_inlineskiplist | 4 | 2000000.000 | 2200000.000 | 799946.000 | 582395.000 |
| rocksdb_inlineskiplist | 8 | 2000000.000 | 2134368.000 | 799789.000 | 555889.000 |
| btreeolc | 1 | 2000000.000 | 2200000.000 | 799962.000 | 570463.000 |
| btreeolc | 4 | 2000000.000 | 2199072.000 | 799904.000 | 570272.000 |
| btreeolc | 8 | 2000000.000 | 2082688.000 | 799721.000 | 538362.000 |
| unodb_art | 1 | 2000000.000 | 2200000.000 | 799962.000 | 570463.000 |
| unodb_art | 4 | 2000000.000 | 2200000.000 | 799983.000 | 584077.000 |
| unodb_art | 8 | 2000000.000 | 2135424.000 | 799842.000 | 556758.000 |
| wormhole | 1 | 2000000.000 | 2200000.000 | 799962.000 | 570463.000 |
| wormhole | 4 | 2000000.000 | 2200000.000 | 799979.000 | 597058.000 |
| wormhole | 8 | 2000000.000 | 2200000.000 | 799960.000 | 575848.000 |
| cse_crossbeam | 1 | 2000000.000 | 2200000.000 | 799962.000 | 570463.000 |
| cse_crossbeam | 4 | 2000000.000 | 2200000.000 | 799917.000 | 575683.000 |
| cse_crossbeam | 8 | 2000000.000 | 2101376.000 | 799776.000 | 545566.000 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 3.114 | 24.989 | 0.173 | 5.648 | 0.000 |
| btreeolc | 4.522 | 25.307 | 0.253 | 3.856 | 0.086 |
| unodb_art | 1.930 | 24.918 | 0.327 | 1.581 | 0.853 |
| wormhole | 1.741 | 25.304 | 0.294 | 5.371 | 0.846 |
| cse_crossbeam | 4.759 | 25.436 | 0.452 | 3.498 | 0.752 |
