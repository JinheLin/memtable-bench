# MVCC MemTable benchmark

`mvcc_bench` compares the complete in-memory MVCC operation path. The original
`memtable_bench` and its CSV v3 archives remain exact-key index diagnostics.
Results from these two workload models must be analyzed separately.

## Implementations

| Candidates | Physical representation | Multiworker participation |
| --- | --- | --- |
| std::map, Abseil B-tree, TLX B+tree, HOTSingleThreaded | One ordered InternalKey per version | One worker only |
| RocksDB InlineSkipList, BTreeOLC, UnoDB ART, Masstree, Wormhole | One ordered InternalKey per version | One worker; native concurrent readers; SWMR |
| `cse_arena` | One Arena skiplist node per user key; native older-version links | Native concurrent reads; internally serialized batch writer |
| `cse_crossbeam` | One Crossbeam SkipMap entry per user key; native immutable Arc version chains | Native concurrent reads; internally serialized batch writer |

The first nine use `user_key || BE(~timestamp) || type`, with deletion type 0
and put type 1. User keys are fixed width in one experiment. `GetAt` seeks the
first version at or below the snapshot, then checks the user key. It returns a
copy of the payload. Each lookup includes cursor creation and key encoding.
The CSE adapters invoke native `get(user_key, snapshot)` and copy the result
while its native ownership guard is live. They store user keys and native
metadata, rather than passing an encoded InternalKey as the CSE user key.

Costs of wrappers, synchronization, Rust FFI, ownership and encoding are timed.
This is an operation-path comparison; it is not an isolated measurement of
the underlying tree traversal instructions. UnoDB/HOT retain their additional
terminated nibble encoding. The CSE cursor bridge performs C ABI calls per
navigation step and metadata refresh; this cost is included in scans and flush.

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
batch API. Arena growth timing is retained, with a no-op metrics observer.
Blob references, user metadata, CfTable's three CFs, transaction files, WAL,
lower SSTs and actual SST generation are outside this comparison.

Crossbeam Freeze calls its native `seal`; ordered flush uses its sealed,
borrowed iterator. Arena has an adapter write gate for permanent Freeze and
uses its native iterator. Concurrent writes use the native batch writer mutex
in each CSE core; the adapter does not claim parallel writers. The bridge
retains native backing owners for cursor views and catches Rust panics at the
ABI boundary. Its flush iterator retains an Arc owner until after iterator
destruction. C++ exceptions from Get materialization do not cross the C ABI.

CSE source files and accompanying upstream license files remain in the ignored
local export. The public benchmark repository contains pins and the bridge,
without redistributing the engine source. Check the CSE checkout's commercial
and third-party terms before redistributing an export or linked binary.

## Build

The dependency-free default builds both executables, with `std_map` available:

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
Without a valid export, both CSE candidates are explicitly unavailable.
The build does not download the complete CSE workspace or require its nightly
toolchain. The project supports **native Linux x86-64 only**; configuration rejects other
platforms and cross builds. GCC 11.3.1 and Rust stable 1.92.0 passed all eleven
implementation tests; see [verification notes](testing.md).

## Workload semantics

Precomputed inputs contain N present user keys and N disjoint absent keys.
For key id i and version round r, timestamp is `r*N+i+1`. Writes are shuffled
within a round; rounds increase, ensuring strictly increasing timestamps per
key for every implementation. Each `(user_key,timestamp)` is written once.
Round zero is live; later rounds generate deterministic tombstones and allow
resurrection. Live payload bytes vary by version round. Tombstone payloads are
empty, and an empty live value remains distinct from deletion and absence.

A snapshot is a completed-round timestamp: latest is `versions*N`, historical
is `(versions-snapshot_lag)*N`. Lag equal to versions reads before the first
insert. Tombstones mask older values; they never fall back to an earlier live
version. These are memtable-only reads, without an LSM lookup in older tables.

| Stage | Timed phases | Units |
| --- | --- | --- |
| 1 | Batch load; latest/historical Get; latest/historical visible range scan | Batch requests, point requests, scan requests; visible live rows |
| 2, one worker | Interleaved writes, point reads and scans at a fixed historical snapshot | Read requests plus batch requests; written versions separately |
| 2, multiple workers | One writer + readers; or read-only workers when read-percent=100 | Aggregate wall throughput; separate writer service and readers rows |
| 3 | Batch load → Freeze → ordered complete-version flush → Destroy | Written versions, all flushed versions, phase durations |

Stage 2 uses a fixed snapshot from the completed prefill. New timestamps are
strictly greater; readers continue to see the earlier view throughout the
write phase. This permits exact independent validation despite scheduling
differences. The model does not claim transaction-atomic batch visibility,
moving/latest snapshots, multiwriter scaling, or transaction conflict handling.
In a single-worker trace, batch calls and read calls are shuffled while write
batches consume their globally ordered timestamps in submission order.

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
payload generation and read oracle calculation precede index allocation.
Read/scan validation hashes keys, visible timestamp/type and payload bytes;
hashing is timed. The load phase hashes submission counts, with full contents
validated by snapshot reads and lifecycle flush. No benchmark relies on exact
raw Get to model MVCC visibility.

```sh
# Eight versions per key; historical snapshot six rounds behind latest.
build-cse/mvcc_bench --index cse_crossbeam --stage 1 \
  --keys 100000 --versions 8 --snapshot-lag 6 --ops 100000 \
  --batch-size 32 --key-size 32 --key-layout global-prefix --prefix-bytes 24 \
  --value-size 64 --delete-percent 10 --miss-percent 10 \
  --scan-length 100 --scan-ops 2000 --output mvcc-single.csv

# Single writer + seven readers; 80% reads, of which 10% are visible scans.
build-all/mvcc_bench --index cse_arena --stage 2 \
  --keys 100000 --versions 4 --snapshot-lag 2 --ops 1000000 \
  --threads 8 --read-percent 80 --scan-percent 10 --batch-size 64 \
  --distribution zipf --cpu-list 2,3,4,5,6,7,8,9 --numa-node 0 \
  --output mvcc-swmr.csv

# Lifetime including all historical versions and delete markers.
build-all/mvcc_bench --index rocksdb_inlineskiplist --stage 3 \
  --keys 1000000 --versions 4 --batch-size 32 --output mvcc-lifecycle.csv
```

Common-prefix layouts and distributions reuse the controlled key generator.
Uniform, sequential and Zipf(theta=1.1) choose user keys; history depth varies
independently. Native key limits apply to encoded keys for the nine indexes,
and user key width for CSE. Arena limits encoded values to 16 MiB-1 and rejects
workload bounds that could overflow its uint32 allocation counter. This guard
is deliberately conservative; it is not a claim of exact allocation size.

## Screening matrix

`scripts/mvcc_matrix.py` runs fresh processes in randomized serial order,
with the same seeds across candidates. It obtains availability/concurrency
from `mvcc_bench --list-indexes` and skips non-native multiworker cases. It
records commands, raw per-process CSV/logs, binary SHA-256, source file hashes,
dependency revisions and topology. All phase counts and cross-adapter contents
are checked; missing phases, mismatches or process errors fail the run.

Default profiles vary one factor from the base (16-byte key, 32-byte payload,
4 versions, lag 2, batch 32):

| Profile | Change |
| --- | --- |
| base | Reference configuration |
| deep | 16 versions, lag 15, to expose historical chain traversal |
| prefix | 32-byte user keys sharing a 24-byte prefix |
| value | 1024-byte values |

This is a screening design; timestamp retention, contention, key distribution,
batch size and read/scan mix can then be explored in focused CLI runs. It avoids
exhausting the Cartesian product before identifying expensive cases.

```sh
python3 scripts/mvcc_matrix.py --binary build-all/mvcc_bench \
  --output results/mvcc-screening --keys 100000 --ops 100000 --repeats 3 \
  --profiles base,deep,prefix,value --threads 1,4,8 \
  --cpus 2,3,4,5,6,7,8,9 --numa-node 0
```

## CSV schema: `mvcc-v1`

The full header is defined by `Csv::kHeader` in `src/mvcc_main.cc`. It cannot be
appended to a legacy v3 CSV or a different header. Matrix raw CSV adds
`profile`, `repeat`, and `scenario_threads` (the parent SWMR worker count).

| Fields | Meaning |
| --- | --- |
| schema_version, run_id, index, representation, adapter_mode, native_batch | Workload/implementation identity and actual batch support |
| stage, phase, threads | Phase worker count; writer row is 1, readers row N-1 |
| user_keys, initial_versions_per_key, stored_versions | Present user population and physical MVCC version counts |
| key_size, value_size, batch_size, snapshot_ts, snapshot_lag | Input widths, submission size and read timestamp |
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
| checksum | Validated deterministic contents, including timestamp/type |

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
Stage-all can retain allocator pages from earlier tables. CSE Arena accounting
counts arena allocation charges; Crossbeam estimates retained object charges,
excluding allocator overhead. They are not interchangeable with each other or
RSS. Destroy may leave resident allocator pages even after all objects retire.

Contract tests cover historical reads, deleted/absent/empty values, resurrection,
version navigation, visible scans, native concurrent readers with newer writes,
permanent Freeze and complete flush cardinality. Workload tests compare all
available candidates with independent oracles and enforce concurrency policy.
