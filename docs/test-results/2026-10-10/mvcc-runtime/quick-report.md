# MVCC benchmark results

Validated **45 processes / 150 phase rows**.

Each table reports the median of independent fresh-process repetitions. summary.csv includes quartiles, min/max and sample counts. Quartiles are descriptive, not confidence intervals. Compare candidates within a cohort; different key populations are kept separate.

Current groups are reported separately: OLTP captures the latest completed batch at each request start; history holds a fixed completed-round snapshot. Latest concurrent results are verified against an independent oracle using the exact captured timestamps after timing. Their visible values/hit counts/checksums can differ with scheduling; only deterministic request/write/dataset counts are compared across adapters. Fixed-view results retain cross-adapter content equality. Actual visibility counts and oracle checksums remain in raw CSV. Legacy mvcc-v1 archives retain their original both-view/fixed-snapshot protocol.

Writes are batch submissions, not atomic transactions. GetAt materializes values; scans hash visible live rows; flush hashes every retained version and tombstone. Adapter/encoding/FFI costs are included. No WAL, SST encoding or disk I/O is measured. SWMR uses one writer and N-1 readers with the selected read view; single-worker mixed timing is a different interleaving. Reader service throughput uses the complete group wall interval, including the tail after writing.

The shared host has CPU/NUMA binding but no frequency lock or reserved CPUs. Stage-1 scans have 1024 calls and about 16 latency samples; their p99 is not a stable tail estimate. Aggregate SWMR latency is intentionally absent. Reader service latency mixes Get and Scan. Current default mixed workloads use scan-percent=0 to keep their reader latency point-only; dedicated scans remain in stage 1. RSS deltas include allocator/runtime retention and are measured after input preparation. CSE backend accounting is not interchangeable with RSS. Phase elapsed time includes PMU start/stop and sampling setup. For a one-request Freeze phase this overhead dominates; the separately sampled call excludes PMU control but still includes clock/call instrumentation. Neither is a stable native-only Freeze latency estimate.

## quick: oltp / oltp_uniform

User keys: 100,000; operation budget: 100,000; repetitions: 1. Profile: `{"batch_size": 32, "delete_percent": 10, "distribution": "uniform", "key_layout": "random", "key_size": 16, "miss_percent": 10, "prefix_bytes": 0, "prefix_groups": 1, "read_percent": 80, "read_view": "latest", "scan_length": 100, "scan_ops": 1024, "scan_percent": 0, "snapshot_lag": 0, "value_size": 32, "versions": 2}`.

Suite: `quick`; measured stages: `1,2,3`. One repetition: screening/correctness evidence, not a stable performance ranking.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Latest scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 1.338 | 0.911 | 3.671 | 15.008 | 78.684 |
| btreeolc | 0.739 | 0.799 | 0.901 | 40.215 | 210.842 |
| unodb_art | 1.306 | 0.775 | 0.458 | 63.418 | 332.493 |
| wormhole | 1.717 | 0.702 | 1.352 | 30.676 | 160.829 |
| cse_crossbeam | 0.777 | 0.681 | 2.311 | 41.535 | 217.764 |

### Latest published batch: mixed / SWMR

| Index | 8 workers Mreq/s | 8 workers: readers Mreq/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- |
| rocksdb_inlineskiplist | 3.978 | 3.947 | 0.997 |
| btreeolc | 2.206 | 2.189 | 0.551 |
| unodb_art | 3.553 | 3.525 | 0.888 |
| wormhole | 3.985 | 3.954 | 1.357 |
| cse_crossbeam | 2.707 | 2.686 | 0.676 |

### Latest visibility evidence

| Index | Workers | Min observed snapshot | Max observed snapshot | Reads after newer publication | Point hits on new versions |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 8 | 200000.000 | 213088.000 | 79810.000 | 4440.000 |
| btreeolc | 8 | 200000.000 | 208256.000 | 79764.000 | 2938.000 |
| unodb_art | 8 | 200000.000 | 213888.000 | 79870.000 | 4723.000 |
| wormhole | 8 | 200000.000 | 220000.000 | 79995.000 | 9936.000 |
| cse_crossbeam | 8 | 200000.000 | 210048.000 | 79782.000 | 3512.000 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.153 | 24.604 | 0.160 | 7.660 | 0.000 |
| btreeolc | 0.277 | 25.453 | 0.280 | 4.415 | 0.008 |
| unodb_art | 0.163 | 25.031 | 0.283 | 1.718 | 0.084 |
| wormhole | 0.112 | 28.309 | 0.431 | 5.805 | 0.033 |
| cse_crossbeam | 0.261 | 25.770 | 0.597 | 3.827 | 0.065 |

## quick: oltp / oltp_zipf

User keys: 100,000; operation budget: 100,000; repetitions: 1. Profile: `{"batch_size": 32, "delete_percent": 10, "distribution": "zipf", "key_layout": "random", "key_size": 16, "miss_percent": 10, "prefix_bytes": 0, "prefix_groups": 1, "read_percent": 80, "read_view": "latest", "scan_length": 100, "scan_ops": 1024, "scan_percent": 0, "snapshot_lag": 0, "value_size": 32, "versions": 2}`.

Suite: `quick`; measured stages: `1,2,3`. One repetition: screening/correctness evidence, not a stable performance ranking.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Latest scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 1.376 | 1.303 | 4.268 | 14.953 | 78.397 |
| btreeolc | 0.735 | 1.185 | 1.004 | 40.273 | 211.149 |
| unodb_art | 1.167 | 1.055 | 0.475 | 63.418 | 332.493 |
| wormhole | 1.690 | 0.919 | 1.519 | 30.734 | 161.137 |
| cse_crossbeam | 0.786 | 1.225 | 3.121 | 41.480 | 217.477 |

### Latest published batch: mixed / SWMR

| Index | 8 workers Mreq/s | 8 workers: readers Mreq/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- |
| rocksdb_inlineskiplist | 5.023 | 4.984 | 1.264 |
| btreeolc | 2.835 | 2.813 | 0.709 |
| unodb_art | 4.565 | 4.530 | 1.145 |
| wormhole | 4.565 | 4.529 | 1.237 |
| cse_crossbeam | 3.539 | 3.512 | 0.887 |

### Latest visibility evidence

| Index | Workers | Min observed snapshot | Max observed snapshot | Reads after newer publication | Point hits on new versions |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 8 | 200000.000 | 213984.000 | 79824.000 | 51049.000 |
| btreeolc | 8 | 200000.000 | 207904.000 | 79708.000 | 48360.000 |
| unodb_art | 8 | 200000.000 | 213440.000 | 79829.000 | 50858.000 |
| wormhole | 8 | 200000.000 | 220000.000 | 79985.000 | 54374.000 |
| cse_crossbeam | 8 | 200000.000 | 209664.000 | 79635.000 | 49046.000 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.161 | 25.705 | 0.289 | 7.204 | 0.000 |
| btreeolc | 0.275 | 24.573 | 0.276 | 4.382 | 0.008 |
| unodb_art | 0.154 | 25.166 | 0.373 | 1.738 | 0.084 |
| wormhole | 0.116 | 24.569 | 0.263 | 5.857 | 0.033 |
| cse_crossbeam | 0.263 | 25.825 | 0.613 | 3.942 | 0.064 |

## quick: history / history_v16

User keys: 100,000; operation budget: 100,000; repetitions: 1. Profile: `{"batch_size": 32, "delete_percent": 10, "distribution": "uniform", "key_layout": "random", "key_size": 16, "miss_percent": 10, "prefix_bytes": 0, "prefix_groups": 1, "read_percent": 80, "read_view": "historical", "scan_length": 100, "scan_ops": 1024, "scan_percent": 0, "snapshot_lag": 15, "value_size": 32, "versions": 16}`.

Suite: `quick`; measured stages: `1,2,3`. One repetition: screening/correctness evidence, not a stable performance ranking.

### Single-thread operations

| Index | Load Mversions/s | Historical Get Mreq/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.682 | 0.502 | 0.368 | 119.164 | 78.095 |
| btreeolc | 0.468 | 0.496 | 0.110 | 319.426 | 209.339 |
| unodb_art | 1.267 | 0.691 | 0.073 | 260.645 | 170.816 |
| wormhole | 1.241 | 0.367 | 0.167 | 173.504 | 113.708 |
| cse_crossbeam | 0.682 | 0.323 | 0.329 | 251.336 | 164.716 |

### Fixed historical snapshot: mixed / SWMR

| Index | 8 workers Mreq/s | 8 workers: readers Mreq/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- |
| rocksdb_inlineskiplist | 2.222 | 2.205 | 0.554 |
| btreeolc | 1.553 | 1.541 | 0.387 |
| unodb_art | 3.535 | 3.507 | 0.884 |
| wormhole | 1.738 | 1.725 | 0.433 |
| cse_crossbeam | 2.257 | 2.240 | 0.637 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 2.331 | 24.893 | 0.264 | 5.787 | 0.000 |
| btreeolc | 3.452 | 24.848 | 0.166 | 3.490 | 0.080 |
| unodb_art | 1.235 | 24.925 | 0.401 | 2.157 | 0.392 |
| wormhole | 1.319 | 25.694 | 0.326 | 5.660 | 0.600 |
| cse_crossbeam | 2.313 | 25.514 | 0.512 | 3.592 | 0.455 |
