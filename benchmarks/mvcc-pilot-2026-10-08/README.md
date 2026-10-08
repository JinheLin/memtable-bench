# MVCC/CSE functional pilot — 2026-10-08

Completed on the shared Xeon Gold 6240 Linux host, with GCC 11.3.1 and Rust
stable 1.92.0. CPU affinity selects physical cores 2/3/4/5 on NUMA node 0;
allocations are bound to node 0. Runs execute serially in randomized order.
CPU frequency is not fixed and the machine is not reserved.

| Parameter | Value |
| --- | --- |
| Candidates | Existing nine indexes + `cse_arena` + `cse_crossbeam` |
| Present user keys | 10,000 (another 10,000 keys serve as disjoint misses) |
| Initial versions | Four per key; sixteen in the deep profile |
| Operation budget | 10,000 per process |
| Profiles | Base, deep history, shared prefix, large value |
| Repeats | One, seed 42 |
| Stages / workers | Single-thread operations and lifecycle for all eleven; mixed single worker for all eleven; SWMR at four workers for seven native candidates |
| Completed processes / rows | **160 / 524** |
| PMU cycle availability | 524 / 524 phase rows |

Profiles are defined in the [workload guide](../../docs/mvcc.md). The base uses
16-byte user keys, 32-byte live values, four versions, snapshot lag two and
batch size 32. Deep increases history to sixteen versions / lag fifteen;
prefix uses 32-byte keys sharing 24 bytes; value uses 1024-byte live values.
Tombstones are retained. Read requests include explicit absent keys and visible
range scans, with exact independent oracle checking.

Every planned process completed. Within each profile/stage/thread comparison,
all candidates have matching request/row/version counts, point visibility and
checksums. Single-thread row counts include 5 operation phases + 1 mixed phase
+ 4 lifecycle phases per implementation. Each SWMR process produces total,
writer and readers rows. No wrapper-only implementation ran above one worker.

**This is a correctness and execution pilot.** One repeat and these small
datasets do not establish stable throughput or memory rankings. The values
include FFI, adapters, key encoding, payload copies/hashing and batch preparation.
The stage 2 snapshots are fixed; this does not measure moving snapshots or
parallel writers. CSE writers are internally serialized. The output is
`mvcc-v1` and cannot be merged with legacy v3 exact-key results.

## Files and reproducibility

- [raw.csv](raw.csv): all 524 phase rows.
- [metadata.json](metadata.json): original measurement metadata, binary SHA-256,
  source hashes, dependency revisions and exact arguments.
- [build-record.json](build-record.json): compiler/Rust versions, CMake cache
  settings and additional build input hashes captured on the same host.
- `process-records.tar.gz`: 160 exact command JSONs, logs and per-process CSVs.
- `source-snapshot.tar.gz`: harness/bridge source files named by the original
  metadata. It contains no CSE engine source.
- `build-inputs.tar.gz`: unchanged upstream patch files, CMake template and
  build script, with hashes in the build record.
- [archive.json](archive.json): archive hashes and validation counts.

The source snapshot records the measured development tree. Subsequent source
cleanup and safety documentation are represented by repository commits; this
archive is not relabeled as a run of a later binary. The final Linux tests
also cover the added oversized-value boundary check.

This pilot predates the UnoDB iterator restart/seek and HOT single-record bound
fixes. Although every pilot result matched its oracle, later stress tests exposed
these correctness issues. Use the current sources for new runs; this archive's
timings are historical. The [current Linux validation](../../docs/testing.md)
includes the fixes and a fresh 40-process matrix.

```sh
python3 scripts/mvcc_matrix.py --binary build-linux/mvcc_bench \
  --output results/new-mvcc-pilot --keys 10000 --ops 10000 --repeats 1 \
  --profiles base,deep,prefix,value --threads 1,4 \
  --cpus 2,3,4,5 --numa-node 0
```

Extract both source/build-input archives into an empty directory to restore
the measurement harness. Provide the pinned dependencies and an authorized,
verified CSE export as described in the guide; this public archive intentionally
does not redistribute the engine. Extract process-records separately to recover
the exact original invocation records.
