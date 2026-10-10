# MVCC benchmark results

Validated **5 processes / 15 phase rows**.

Each table reports the median of independent fresh-process repetitions. summary.csv includes quartiles, min/max and sample counts. Quartiles are descriptive, not confidence intervals. Compare candidates within a cohort; different key populations are kept separate.

Current groups are reported separately: OLTP captures the latest completed batch at each request start; history holds a fixed completed-round snapshot. Latest concurrent results are verified against an independent oracle using the exact captured timestamps after timing. Their visible values/hit counts/checksums can differ with scheduling; only deterministic request/write/dataset counts are compared across adapters. Fixed-view results retain cross-adapter content equality. Actual visibility counts and oracle checksums remain in raw CSV. Legacy mvcc-v1 archives retain their original both-view/fixed-snapshot protocol.

Writes are batch submissions, not atomic transactions. GetAt materializes values; scans hash visible live rows; flush hashes every retained version and tombstone. Adapter/encoding/FFI costs are included. No WAL, SST encoding or disk I/O is measured. SWMR uses one writer and N-1 readers with the selected read view; single-worker mixed timing is a different interleaving. Reader service throughput uses the complete group wall interval, including the tail after writing.

The shared host has CPU/NUMA binding but no frequency lock or reserved CPUs. Stage-1 scans have 1024 calls and about 16 latency samples; their p99 is not a stable tail estimate. Aggregate SWMR latency is intentionally absent. Reader service latency mixes Get and Scan. Current default mixed workloads use scan-percent=0 to keep their reader latency point-only; dedicated scans remain in stage 1. RSS deltas include allocator/runtime retention and are measured after input preparation. CSE backend accounting is not interchangeable with RSS. Phase elapsed time includes PMU start/stop and sampling setup. For a one-request Freeze phase this overhead dominates; the separately sampled call excludes PMU control but still includes clock/call instrumentation. Neither is a stable native-only Freeze latency estimate.

## point-1m: oltp / oltp_uniform

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 1. Profile: `{"batch_size": 32, "delete_percent": 10, "distribution": "uniform", "key_layout": "random", "key_size": 16, "miss_percent": 10, "prefix_bytes": 0, "prefix_groups": 1, "read_percent": 80, "read_view": "latest", "scan_length": 100, "scan_ops": 1024, "scan_percent": 0, "snapshot_lag": 0, "value_size": 32, "versions": 2}`.

Suite: `quick`; measured stages: `1`. One repetition: screening/correctness evidence, not a stable performance ranking.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Latest scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- |
| rocksdb_inlineskiplist | 0.642 | 0.454 | 2.560 | 151.648 | 79.507 |
| btreeolc | 0.445 | 0.453 | 0.814 | 406.043 | 212.883 |
| unodb_art | 1.013 | 0.644 | 0.447 | 578.785 | 303.450 |
| wormhole | 1.137 | 0.578 | 1.164 | 217.848 | 114.215 |
| cse_crossbeam | 0.427 | 0.398 | 1.952 | 414.590 | 217.364 |
