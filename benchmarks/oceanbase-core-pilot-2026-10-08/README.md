# OceanBase KeyBtree integration pilot — 2026-10-08

Completed on Linux x86-64 / GCC 11.3.1, on the shared Xeon Gold 6240 host.
Processes ran serially in randomized order, with physical CPUs 2/3/4/5 and
NUMA node 0 memory binding. Frequency and background load were not controlled.

| Parameter | Value |
| --- | --- |
| Candidates | Original nine ordered indexes, both CSE backends, OceanBase KeyBtree core port |
| Present user keys | 10,000, plus a disjoint 10,000-key miss corpus |
| Profiles | Base, deep history, shared prefix, large value |
| Initial versions per key | Four; sixteen in deep history |
| Operation budget | 10,000 per process |
| Repetitions | One, seed 42 |
| Workers | One for all twelve; four for eight native concurrent candidates |
| Completed processes / phase rows | **176 / 576** |
| Matching comparison groups | **52 / 52** |
| PMU cycle availability | **576 / 576 phase rows** |

Every run validated its output against the independent MVCC oracle. Counts,
visibility, tombstones, retained versions and content checksums also agree
across candidates within each eligible comparison. Native concurrent candidates
participate in the one-writer/multiple-reader workload; this pilot does not
measure parallel MVCC writers. The exact-key CTest separately exercises
multiple concurrent inserters and Freeze admission.

**OceanBase scope:** this is the actual KeyBtree algorithm with standalone
runtime glue and binary key comparison, storing one encoded InternalKey per
version. It is not full `ObMemtable` transaction/MVCC performance. Native
version chains, hash lookups, transaction cleanout and row compaction are not
integrated. In particular, common `GetAt` fills the native iterator's first
225-entry batch; OceanBase's native user-key point-get path would work differently.
See [the integration boundary](../../docs/oceanbase.md).

This is a functional pilot. These small datasets and one repetition do not
establish stable throughput, tail latency or memory rankings. Timings include
adapters, FFI where applicable, payload copying/hashing and key encoding.
The `mvcc-v1` rows must not be combined with legacy exact-key CSV v3 results.

## Artifacts

- [raw.csv](raw.csv): all 576 phase rows, unchanged.
- [metadata.json](metadata.json): measured binary/source hashes, dependency
  pins, native capability listing, CMake inputs and exact arguments.
- [archive.json](archive.json): SHA-256 digests and independent archive checks.
- `process-records.tar.gz`: all 176 command JSONs, process logs and CSVs.
- `source-snapshot.tar.gz`: measured harness, port glue, source pins, build and
  test inputs listed in the metadata. It contains no CSE engine source and no
  complete OceanBase checkout. The vendor script retrieves the verified public
  OceanBase subset; CSE still requires an authorized local export.

Source inputs and the measured binary matched their metadata when archived.
This pilot includes the current UnoDB restart and HOT lower-bound fixes.
Full tests, memory checks and source-integrity checks are recorded in
[verification](../../docs/testing.md#oceanbase-keybtree-core-integration).

```sh
python3 scripts/mvcc_matrix.py --binary build-linux/mvcc_bench \
  --output results/new-oceanbase-core-pilot --keys 10000 --ops 10000 \
  --repeats 1 --profiles base,deep,prefix,value --threads 1,4 \
  --cpus 2,3,4,5 --numa-node 0
```
