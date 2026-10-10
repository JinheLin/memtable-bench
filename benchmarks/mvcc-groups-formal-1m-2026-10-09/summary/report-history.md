# MVCC history benchmark

Validated group: **150 processes / 420 phase rows**.

Each table reports the median of independent fresh-process repetitions. summary.csv includes quartiles, min/max and sample counts. Quartiles are descriptive, not confidence intervals. Compare candidates within a cohort; different key populations are kept separate.

Current groups are reported separately: OLTP captures the latest completed batch at each request start; history holds a fixed completed-round snapshot. Latest concurrent results are verified against an independent oracle using the exact captured timestamps after timing. Their visible values/hit counts/checksums can differ with scheduling; only deterministic request/write/dataset counts are compared across adapters. Fixed-view results retain cross-adapter content equality. Actual visibility counts and oracle checksums remain in raw CSV. Legacy mvcc-v1 archives retain their original both-view/fixed-snapshot protocol.

Writes are batch submissions, not atomic transactions. GetAt materializes values; scans hash visible live rows; flush hashes every retained version and tombstone. Adapter/encoding/FFI costs are included. No WAL, SST encoding or disk I/O is measured. SWMR uses one writer and N-1 readers with the selected read view; single-worker mixed timing is a different interleaving. Reader service throughput uses the complete group wall interval, including the tail after writing.

The shared host has CPU/NUMA binding but no frequency lock or reserved CPUs. Stage-1 scans have 1024 calls and about 16 latency samples; their p99 is not a stable tail estimate. Aggregate SWMR latency is intentionally absent. Reader service latency mixes Get and Scan. Current default mixed workloads use scan-percent=0 to keep their reader latency point-only; dedicated scans remain in stage 1. RSS deltas include allocator/runtime retention and are measured after input preparation. CSE backend accounting is not interchangeable with RSS. Phase elapsed time includes PMU start/stop and sampling setup. For a one-request Freeze phase this overhead dominates; the separately sampled call excludes PMU control but still includes clock/call instrumentation. Neither is a stable native-only Freeze latency estimate.

## history-1m: history / history_v16

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "delete_percent": 10, "distribution": "uniform", "key_layout": "random", "key_size": 16, "miss_percent": 10, "prefix_bytes": 0, "prefix_groups": 1, "read_percent": 80, "read_view": "historical", "scan_length": 100, "scan_ops": 1024, "scan_percent": 0, "snapshot_lag": 15, "value_size": 32, "versions": 16}`.

### Single-thread operations

| Index | Load Mversions/s | Historical Get Mreq/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.391 | 0.287 | 0.320 | 1192.090 | 78.125 |
| btreeolc | 0.324 | 0.314 | 0.098 | 3219.785 | 211.012 |
| unodb_art | 0.980 | 0.574 | 0.067 | 2408.766 | 157.861 |
| wormhole | 0.923 | 0.326 | 0.148 | 1650.504 | 108.167 |
| cse_crossbeam | 0.390 | 0.196 | 0.268 | 2510.793 | 164.547 |

### Fixed historical snapshot: mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.240 | 0.906 | 1.333 | 0.899 | 1.323 | 0.333 | 0.331 |
| btreeolc | 0.244 | 0.972 | 1.125 | 0.964 | 1.116 | 0.287 | 0.279 |
| unodb_art | 0.466 | 1.690 | 2.852 | 1.677 | 2.830 | 0.677 | 0.708 |
| wormhole | 0.233 | 0.839 | 1.543 | 0.832 | 1.531 | 0.338 | 0.383 |
| cse_crossbeam | 0.165 | 0.607 | 1.471 | 0.602 | 1.460 | 0.359 | 0.370 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 40.819 | 25.876 | 0.251 | 4.750 | 0.003 |
| btreeolc | 49.242 | 25.892 | 0.294 | 3.158 | 0.755 |
| unodb_art | 16.028 | 26.620 | 0.439 | 1.933 | 5.067 |
| wormhole | 17.419 | 26.490 | 0.311 | 5.180 | 7.205 |
| cse_crossbeam | 41.028 | 30.746 | 0.606 | 2.844 | 5.478 |

## history-1m: history / history_v64

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "delete_percent": 10, "distribution": "uniform", "key_layout": "random", "key_size": 16, "miss_percent": 10, "prefix_bytes": 0, "prefix_groups": 1, "read_percent": 80, "read_view": "historical", "scan_length": 100, "scan_ops": 1024, "scan_percent": 0, "snapshot_lag": 63, "value_size": 32, "versions": 64}`.

### Single-thread operations

| Index | Load Mversions/s | Historical Get Mreq/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.284 | 0.201 | 0.065 | 4759.883 | 77.986 |
| btreeolc | 0.273 | 0.234 | 0.024 | 12877.352 | 210.983 |
| unodb_art | 0.829 | 0.484 | 0.016 | 8868.727 | 145.305 |
| wormhole | 0.837 | 0.128 | 0.037 | 6497.359 | 106.453 |
| cse_crossbeam | 0.384 | 0.070 | 0.065 | 9698.020 | 158.892 |

### Fixed historical snapshot: mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.164 | 0.655 | 0.999 | 0.650 | 0.991 | 0.242 | 0.248 |
| btreeolc | 0.204 | 0.801 | 0.942 | 0.794 | 0.935 | 0.237 | 0.234 |
| unodb_art | 0.413 | 1.493 | 2.450 | 1.481 | 2.431 | 0.614 | 0.608 |
| wormhole | 0.104 | 0.336 | 0.455 | 0.333 | 0.452 | 0.083 | 0.113 |
| cse_crossbeam | 0.064 | 0.203 | 0.479 | 0.202 | 0.476 | 0.350 | 0.351 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 224.993 | 27.616 | 0.434 | 4.015 | 0.017 |
| btreeolc | 234.486 | 27.593 | 0.369 | 3.060 | 3.295 |
| unodb_art | 77.976 | 26.859 | 0.493 | 1.956 | 20.421 |
| wormhole | 76.446 | 27.105 | 0.546 | 4.621 | 32.453 |
| cse_crossbeam | 167.299 | 26.887 | 0.619 | 2.636 | 23.295 |
