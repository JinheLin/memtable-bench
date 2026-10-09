# MVCC MemTable benchmark

`mvcc_bench` compares the complete in-memory MVCC operation path. The original
`memtable_bench` and its CSV v3 archives remain exact-key index diagnostics.
Results from these two workload models must be analyzed separately.

The [historical completed formal matrix](../benchmarks/mvcc-formal-1m-2026-10-08/README.md)
contains six cohorts and three repetitions: **906 processes / 2,928 phase rows**,
with 288 matching count/content comparison groups. The million-user-key
base/deep/prefix/value cohorts use 1/4/8 workers where native concurrency permits.
CSE Arena's deep and large-value capacity exclusions are recorded separately;
matched 500k/100k-user-key supplements include all twelve implementations.
See [all cohort tables](../benchmarks/mvcc-formal-1m-2026-10-08/summary/report.md).

## Implementations

The current benchmark retains five candidates; InlineSkipList is the default
baseline. See [index selection and removal reasons](index-selection.md).
The completed archive above records the twelve-candidate run before pruning.

| Candidates | Physical representation | Multiworker participation |
| --- | --- | --- |
| RocksDB InlineSkipList, BTreeOLC, UnoDB ART, Wormhole | One ordered InternalKey per version | Native concurrent readers; SWMR |
| `cse_crossbeam` | One Crossbeam SkipMap entry per user key; native immutable Arc version chains | Native concurrent reads; internally serialized batch writer |

The four ordered-index candidates use `user_key || BE(~timestamp) || type`,
with deletion type 0 and put type 1. User keys are fixed width in one experiment.
`GetAt` seeks the first version at or below the snapshot, then checks the user
key and copies the payload. Each lookup includes cursor creation and key encoding.
CSE invokes native `get(user_key, snapshot)` and copies its result while the
native ownership guard is live. It stores native metadata and user keys.

Wrappers, synchronization, Rust FFI, ownership and encoding are timed. UnoDB
retains terminated nibble encoding. The CSE cursor bridge performs C ABI calls
per navigation step and metadata refresh; these costs are included in scans
and flush traversal.

### CSE source boundary

The adapter compiles the **unmodified** `arena.rs`, `skl.rs`, and
`crossbeam_skl.rs` from CSE commit
`80b0309f23f387ff5835a8153263f0d00fbfdaa0`. The export also pins `table.rs` as the
reference for metadata layout. SHA-256 digests are checked at configure time
and before the Rust build. Crossbeam is pinned to CSE's patched revision
`c4abd1b93149108dfa13c0cd42c878657c618bad`, not the crates.io release with the
same version number. Rust transitive dependencies are locked in `Cargo.lock`.

A small standalone Rust static library supplies compatible `Value`, raw
`InnerKey`, and iterator types. Benchmark keys are already inner keys;
TiKV API V2 keyspace prefix parsing is not performed. Snapshot callbacks are
unreachable because the adapters always use the native preserve-tombstones
batch API. Crossbeam reuses the native `WriteBatch`/`WriteBatchEntry` defined in
`skl.rs`, which imports `arena.rs`; these pinned dependency modules remain
compiled. The C ABI creates only Crossbeam and has no backend-selection argument.
Arena is no longer a candidate or a constructible bridge backend.
Blob references, user metadata, CfTable's three CFs, transaction files, WAL,
lower SSTs and actual SST generation are outside this comparison.

Crossbeam Freeze calls native `seal`; ordered flush uses its sealed, borrowed
iterator. Concurrent writes use the native batch writer mutex; the bridge
retains native backing owners for cursor views and catches Rust panics at the
ABI boundary. Its flush iterator retains an Arc owner until after iterator
destruction. C++ exceptions from Get materialization do not cross the C ABI.

CSE source files and accompanying upstream license files remain in the ignored
local export. The public benchmark repository contains pins and the bridge,
without redistributing the engine source. Check the CSE checkout's commercial
and third-party terms before redistributing an export or linked binary.

## Build

The default builds both executables with the required InlineSkipList baseline:

```sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 8
ctest --test-dir build --output-on-failure
```

CSE requires an authorized local checkout, Python 3, Cargo/rustup and a stable
Rust toolchain. Export reads the fixed Git commit, leaving checkout files alone:

```sh
python3 scripts/export_cse_memtable.py \
  --source ~/github/cloud-storage-engine --output vendor/cse-memtable
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cmake -S . -B build-cse -DCMAKE_BUILD_TYPE=Release \
  -DMEMTABLE_BENCH_CSE_SOURCE_DIR="$PWD/vendor/cse-memtable"
cmake --build build-cse -j 8
ctest --test-dir build-cse --output-on-failure
build-cse/mvcc_bench --list-indexes
```

To combine all existing optional indexes with CSE:

```sh
./scripts/build_all.sh build-all -G Ninja \
  -DMEMTABLE_BENCH_CSE_SOURCE_DIR="$PWD/vendor/cse-memtable"
```

For an authorized benchmark host without the checkout, copy that verified
export and pass its absolute directory to CMake. Rust uses the selected CMake
compiler as its host linker and clears inherited Rust flags. CMake's Cargo
build clears proxy variables too. The export is verified even on that host.
Without a valid export, `cse_crossbeam` is explicitly unavailable.
The build does not download the complete CSE workspace or require its nightly
toolchain. The project supports **native Linux x86-64 only**; configuration rejects other
platforms and cross builds. See [verification notes](testing.md) for current
and historical test evidence.

## Two workload groups

The current matrix has two groups and uses CSV protocol **`mvcc-v2`**.
InlineSkipList remains the baseline; all five candidates participate.

| Group | Profiles | Initial versions/key | Read view | Purpose |
| --- | --- | --- | --- | --- |
| `oltp` | `oltp_uniform`, `oltp_zipf` | 2 | Latest completed write batch at each request start | Short retained history, current point reads, and current reads under updates |
| `history` | `history_v16`, `history_v64` | 16 / 64 | Fixed snapshot at the end of the first version round; lag 15 / 63 | Long retained histories, old-version lookup and visible-row scans |

Both groups use the same 16 B random user keys, 32 B live values, batch size 32,
10% deterministic deletions, 10% point misses, 80% read budgets and 1/4/8 workers.
Their mixed reader workload is **point-only** (`scan_percent=0`), allowing reader
latency comparisons without a mixture of Get and scan. Dedicated visible scans
remain in stage 1: maximum 100 live rows/call, at most 1,024 calls.
OLTP's Zipf distribution uses theta 1.1 with popular ranks spread across the
random key order. The historical profiles both use uniform access and read the
same first-round view, so their visibility is matched while retained history grows.

The initial OLTP history is two versions/key; newer updates accumulate during
stage 2, including longer chains on hot keys. No version GC is performed. The
history group deliberately includes retained-history/index-size effects in
addition to traversal; it is not a traversal-only microbenchmark.
Key width, common-prefix layout, value width, batch size, scan mix and deletion
rate remain CLI controls for focused follow-up experiments. The default matrix
keeps those dimensions fixed instead of multiplying the two groups by every
key/value configuration.

## Workload semantics

Precomputed inputs contain N present user keys and N disjoint absent keys.
For key id i and version round r, timestamp is `r*N+i+1`. Writes are shuffled
within a round; rounds increase, ensuring strictly increasing timestamps per
key for every implementation. Each `(user_key,timestamp)` is written once.
Round zero is live; later rounds generate deterministic tombstones and allow
resurrection. Live payload bytes vary by version round. Tombstone payloads are
empty, and an empty live value remains distinct from deletion and absence.

After prefill, the latest timestamp is `versions*N`. A fixed historical
snapshot is `(versions-snapshot_lag)*N`; lag equal to versions reads before
the first insert. `--read-view latest` requires `--snapshot-lag 0`.
`--read-view historical` selects the fixed lagged view. Tombstones mask older
values; they never fall back to an earlier live
version. These are memtable-only reads, without an LSM lookup in older tables.

| Stage | Timed phases | Units |
| --- | --- | --- |
| 1 | Batch load; Get and visible scan using only the selected group's read view | Batch requests, point requests, scan requests; visible live rows |
| 2, one worker | Interleaved writes and reads with latest publication or a fixed historical snapshot | Read requests plus batch requests; written versions separately |
| 2, multiple workers | One writer + readers; or read-only workers when read-percent=100 | Aggregate wall throughput; separate writer service and readers rows |
| 3 | Batch load → Freeze → ordered complete-version flush → Destroy | Written versions, all flushed versions, phase durations |

### OLTP latest publication

Stage 1 reads the latest completed prefill view and emits `get_latest` and
`scan_latest`. Stage 2 reads a **moving latest committed bound**: a single writer
submits monotonically increasing timestamps, then publishes the final timestamp
of a batch with a release store after `Write` returns. Each Get or scan captures
that bound once with an acquire load before accessing the table. Newer physical
entries from an in-progress batch are filtered by that bound. A scan uses the
same captured timestamp throughout its traversal.

This models current reads at request start with benchmark-managed publication.
Publication is not a transaction manager, and no native transaction-atomic batch
implementation is claimed. Readers can miss a publication that happens after
they capture their bound, as a snapshot reader normally would. Single-worker
mixed mode follows the same publication rule with a deterministic action order.

Each reader saves its captured timestamps in a preallocated trace. After timing,
an independent oracle replays its requests against the precomputed write history
at those exact timestamps. The index is not used to construct expected answers.
The atomic load and trace write are timed; oracle replay is not. RSS is sampled
before replay. CSV records snapshot bounds, reads after a newer publication,
point hits on newly written versions and the oracle checksum. Scheduling changes
which updates are visible in multiworker runs, so their read checksums and hit
counts need not match across adapters. Deterministic request/write counts and
input identity still must match. Single-worker OLTP results remain deterministic.

### Historical fixed view

Stage 1 emits `get_snapshot` and `scan_snapshot` only. Stage 2 readers retain the
same first-round snapshot while a writer appends timestamps beyond the completed
prefill. This stresses old-version visibility and concurrent maintenance without
changing expected read results. All fixed-view contents/checksums must agree
across adapters. The current history profiles use lag `versions-1`; custom runs
can select any lag from 0 through `versions`.

Both groups use one writer plus N-1 readers for mixed multiworker tests, or
read-only workers at read-percent=100. They do not implement multiwriter scaling,
transaction conflict handling, version reclamation or lower-SST lookup. In a
single-worker trace, batch calls and read calls are shuffled while write batches
consume their globally ordered timestamps in submission order.

`--ops` is the stage 2 budget of read requests plus **written versions**;
`--read-percent` splits that budget. Actual timed requests collapse written
versions into batch calls. `--scan-percent` selects scans within read requests.
`--miss-percent` selects absent keys within point requests; deletion hits are
additional, separately counted misses at the database level. Short traces may
vary from configured percentages because choices are randomized and reproducible.

Visible range scans start at a user key and return up to `--scan-length` live
rows, skipping future versions, tombstones, and duplicate versions. They may
stop early at EOF. `versions_tested` counts versions examined for snapshot
selection; it excludes versions discarded inside NextUser. Stage 1 performs
`min(ops,scan_ops)` scan calls, with scan-ops defaulting to 1024. Stage 3 emits
**every** retained version and tombstone, in user-key ascending/timestamp
descending order; it simulates flush traversal, without disk or SST encoding.

### Parameters and examples

All runs use precomputed keys/traces and include write batch construction and
native entry ownership in the timed Write call. Dataset creation, sorting,
payload generation and fixed-view oracle preparation precede index allocation;
latest concurrent oracle replay runs after timing using recorded snapshots.
Read/scan validation hashes keys, visible timestamp/type and payload bytes;
hashing is timed. The load phase hashes submission counts, with full contents
validated by snapshot reads and lifecycle flush. No benchmark relies on exact
raw Get to model MVCC visibility.

```sh
# Old first-round view with a 64-version retained chain.
build-core/mvcc_bench --index cse_crossbeam --stage 1 --read-view historical \
  --keys 100000 --versions 64 --snapshot-lag 63 --ops 100000 \
  --batch-size 32 --key-size 32 --key-layout global-prefix --prefix-bytes 24 \
  --value-size 64 --delete-percent 10 --miss-percent 10 \
  --scan-length 100 --scan-ops 2000 --output mvcc-single.csv

# Single writer + seven latest-view point readers; 80% reads, Zipf access.
build-core/mvcc_bench --index cse_crossbeam --stage 2 --read-view latest \
  --keys 100000 --versions 2 --snapshot-lag 0 --ops 1000000 \
  --threads 8 --read-percent 80 --scan-percent 0 --batch-size 32 \
  --distribution zipf --cpu-list 2,3,4,5,6,7,8,9 --numa-node 0 \
  --output mvcc-swmr.csv

# Lifetime including all historical versions and delete markers.
build-core/mvcc_bench --index rocksdb_inlineskiplist --stage 3 \
  --keys 1000000 --versions 4 --batch-size 32 --output mvcc-lifecycle.csv
```

Common-prefix layouts and distributions reuse the controlled key generator.
Uniform, sequential and Zipf(theta=1.1) choose user keys; history depth varies
independently. Native key limits apply to encoded keys for the four ordered
indexes and user-key width for CSE. Crossbeam has no Arena-specific 16 MiB
value limit; the bridge checks uint16 keys, uint32 values and total batch bytes.

## Group matrices

`scripts/mvcc_matrix.py --group oltp|history|all` schedules fresh processes in
randomized serial order. The default `all` covers both groups. `--profiles`
selects a subset within the selected group. The runner discovers available/native
concurrent candidates and records the group, exact parameters, commands,
per-process CSV/logs, source/dependency hashes, binary hash and topology.

With all five candidates, two profiles/group, three repetitions and 1/4/8
workers, **each group has 150 processes / 420 phase rows**. Together they have
**300 / 840**. Stage 1 now measures one read view per process, removing the old
latest/history duplication. Without CSE the matrix schedules the four available
C++ candidates. These are plan counts, not a claim of completed performance runs.
At one million user keys, the history profiles load 16M/64M versions; plan memory
and run time accordingly. To inspect participants without running:

```sh
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/mvcc-oltp --group oltp --list-plan
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/mvcc-history --group history --list-plan
```

Run each group separately:

```sh
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/mvcc-oltp --group oltp \
  --keys 1000000 --ops 1000000 --repeats 3 --threads 1,4,8 \
  --cpus 2,3,4,5,6,7,8,9 --numa-node 0
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/mvcc-history --group history \
  --keys 1000000 --ops 1000000 --repeats 3 --threads 1,4,8 \
  --cpus 2,3,4,5,6,7,8,9 --numa-node 0
```

The former base/deep/prefix/value plan belongs to the historical `mvcc-v1`
protocol. Its published raw files, reports, pins and source snapshots are
unchanged; rebuild an archived source snapshot to reproduce its workload.

### Result validation and summaries

The summarizer checks the complete declared process/phase matrix, native
multiworker participation, dataset/profile fields, per-run oracle digests and
cross-adapter deterministic counts/contents before producing median, quartile, min/max and sample-count
statistics. It requires completed runs and leaves measured input files alone.
Multiple input directories are distinct cohorts; their populations are never
pooled. The output directory must differ from each input directory.

```sh
python3 scripts/summarize_mvcc.py results/mvcc-oltp results/mvcc-history \
  --output results/mvcc-groups-summary
# Optional figures require Matplotlib and NumPy.
python3 scripts/plot_mvcc.py results/mvcc-groups-summary
```

`report.md` has separate group/profile sections. `report-oltp.md` and
`report-history.md` contain their own group's tables. They include single-thread
operation rates, retained RSS per version,
SWMR total/readers/writer service rates and lifecycle timings. `summary.csv`
also retains latency, PMU and overlap-duration statistics. `validation.json`
records process/phase counts, raw-file and binary hashes, and PMU availability.

## CSV schema: `mvcc-v2`

The full header is defined by `Csv::kHeader` in `src/mvcc_main.cc`. It cannot be
appended to a legacy exact-key v3 or MVCC v1 file. Use new output files.
The summarizer can still validate/read original `mvcc-v1` archives.
Matrix raw CSV adds `workload_group`, `profile`, `repeat`, and `scenario_threads`
(the parent SWMR worker count). Summary CSV also carries `workload_group`.

| Fields | Meaning |
| --- | --- |
| schema_version, run_id, index, representation, adapter_mode, native_batch | Workload/implementation identity and actual batch support |
| stage, phase, threads | Phase worker count; writer row is 1, readers row N-1 |
| user_keys, initial_versions_per_key, stored_versions | Present user population and physical MVCC version counts |
| key_size, value_size, batch_size, snapshot_ts, snapshot_lag | Input widths, submission size and initial/fixed read timestamp; latest stage 2 can advance beyond snapshot_ts |
| delete_percent, miss_percent, read_percent, scan_percent, scan_length | Planned workload shares and visible-row limit |
| distribution, key_layout, prefix_bytes, prefix_groups, seed, dataset_hash | Deterministic input identity |
| cpu_list, numa_node | Requested worker placement; NUMA -1 means unbound |
| requests, point_reads, scan_requests, written_versions | Timed operation units, including batch aggregation |
| live_hits, tombstone_hits, not_found, items, versions_tested | Actual contents/visibility counts; items include writes in mixed phases |
| elapsed_ns, throughput_requests_s, throughput_versions_s, items_s | Wall/service timing and throughput in explicit units |
| latency_p50_ns, latency_p95_ns, latency_p99_ns | One sample per 64 requests; batch latency is per submission |
| cycles_per_request, instructions_per_request, ipc, l1d_miss_per_request, llc_miss_per_request, branch_miss_per_request, dtlb_miss_per_request | Linux user-mode PMU counters, scaled for multiplexing |
| rss_baseline_bytes, rss_before_bytes, rss_after_bytes, rss_retained_delta_bytes | Baseline after precomputed input allocation; delta is after minus baseline |
| bytes_per_user_key, bytes_per_version, backend_retained_bytes | RSS normalization; optional CSE accounting counter |
| concurrent_overlap_ns, writer_elapsed_ns | Common measured worker-active interval and writer service duration |
| checksum, oracle_checksum | Actual digest and independently computed expected digest; latest multiworker contents depend on scheduling |
| read_view, snapshot_min_ts, snapshot_max_ts | Selected view and actual observed read timestamp range; bounds blank for phases without reads |
| reads_with_newer_snapshot, newer_version_hits | Reads whose bound exceeds prefill latest; point hits (including tombstones) on versions added in stage 2 |
| scan_ops | Requested stage-1 scan-call cap |

Throughput per request does not mean per written version when batches contain
multiple entries. A flush is one request; `items_s` is flushed versions/s.
Writer throughput uses its service duration, while `swmr_total` and readers
throughput use the whole group wall interval, including reader tail after the
writer finishes. Use overlap and writer duration to assess how much of a finite
run actually involved writing. Aggregate SWMR latency is blank because writer
batches and reader requests are different operations; service rows carry
sampled latency. Reader latency may still combine Get and scan; use scan-percent
0 or 100 for dedicated latency comparisons. Unavailable PMU data is blank.

RSS includes allocator caches and measurement overhead; it is not exact object
size. Prefer a fresh process per stage, as the runner does, for memory comparison.
Stage-all can retain allocator pages from earlier tables. Crossbeam estimates
retained object charges, excluding allocator overhead; this is not equivalent
to RSS. Destroy may leave resident allocator pages even after all objects retire.

Phase wall duration includes PMU start/stop and sampling setup. For the one-call
Freeze phase, these controls dominate the recorded duration. The report also
shows the sampled call duration, which excludes PMU control but includes clock
and call instrumentation. These small samples do not establish native-only
Freeze latency rankings. Bulk operation phases amortize this setup overhead.

Contract tests cover latest publication/oracle replay, historical reads, deleted/absent/empty values, resurrection,
version navigation, visible scans, native concurrent readers with newer writes,
permanent Freeze and complete flush cardinality. Workload tests compare all
available candidates with independent oracles and enforce concurrency policy.
Group runner/report tests exercise both groups and reject wrong groups/views,
invalid snapshot ranges and mismatched oracle digests.
