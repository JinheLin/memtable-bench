# memtable-bench

A C++20 harness for comparing ordered in-memory indexes as LSM MemTable candidates.
It starts with a working `std::map` reference adapter. Abseil B-tree, TLX B+Tree,
and RocksDB InlineSkipList are optional, buildable adapters. Other candidates have named, unavailable
adapter slots with explicit integration work; the harness never substitutes one
data structure for another.

## Status

| Adapter name | Implementation | Build status | Concurrency in this harness |
| --- | --- | --- | --- |
| `std_map` | `std::map` | Default | Coarse reader/writer lock |
| `abseil_btree` | Abseil `btree_map` | Optional FetchContent | Coarse reader/writer lock |
| `tlx_btree` | TLX `btree_map` (B+Tree) | Optional FetchContent | Coarse reader/writer lock |
| `rocksdb_inlineskiplist` | RocksDB InlineSkipList + ConcurrentArena | Optional FetchContent | Native concurrent insert; append-only |
| `btreeolc` | BTreeOLC | Stub | Not measured |
| `unodb_art` | UnoDB ART | Stub | Not measured |
| `masstree` | Masstree | Stub | Not measured |
| `hot` | HOT | Stub | Not measured |
| `wormhole` | Wormhole | Stub | Not measured |

`--list-indexes` reports the status of the actual binary. Requesting an unavailable
adapter exits with an error before creating the result file. The three map/tree
adapters use owned `std::string` keys and values with a coarse reader/writer lock;
their stage 2 measurements describe wrapper scalability. RocksDB uses its upstream
native concurrent insertion and arena storage. All adapters receive identical
logical binary keys and values. Results record their concurrency mode in CSV.

## Build

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
```

The default build has no downloaded dependencies. To enable the two optional trees:

```sh
cmake -S . -B build-optional -DCMAKE_BUILD_TYPE=Release \
  -DMEMTABLE_BENCH_FETCH_ABSEIL=ON -DMEMTABLE_BENCH_FETCH_TLX=ON
cmake --build build-optional -j
./build-optional/memtable_bench --list-indexes
```

CMake FetchContent pins Abseil to commit `76bb24329e8bf5f39704eb10d21b9a80befa7c81`
(tag `20250512.1`) and TLX to `502601e2328129263eeb31a61342e4a48f519a2b`
(tag `v0.6.1`). RocksDB uses tag `v9.10.0`, verified against commit
`ae8fb3e5000e46d8d4c9dbf3a36019c0aaceebff`. Its FetchContent downloader performs
a single-branch shallow clone and verifies the commit on configuration. Keep these
pins fixed within an experiment series. Dependencies
retain their own licenses; this repository's MIT license covers only its own code.

To build the native skiplist:

```sh
cmake -S . -B build-rocksdb -DCMAKE_BUILD_TYPE=Release \
  -DMEMTABLE_BENCH_FETCH_ROCKSDB=ON
cmake --build build-rocksdb --target memtable_bench adapter_contract -j
ctest --test-dir build-rocksdb --output-on-failure
```

The first build compiles the upstream RocksDB static library with tools, upstream
tests, and optional compression dependencies disabled. No skiplist source is copied
or modified. The internal-header adapter uses the same platform definitions as the
upstream library. All three FetchContent options can be enabled in the same build.
On macOS, the system compiler can be selected with
`-DCMAKE_CXX_COMPILER=/usr/bin/clang++` in a new build directory.

## Run

```sh
./build/memtable_bench --stage all --index std_map \
  --keys 100000 --ops 1000000 --key-size 16 --value-size 64 \
  --distribution uniform --threads 8 --read-percent 80 \
  --scan-length 100 --output results.csv

./build/memtable_bench --stage 3 --index std_map --internal-key \
  --keys 100000 --key-size 24 --value-size 128 \
  --distribution zipf --output lifecycle.csv

./build-rocksdb/memtable_bench --stage all --index rocksdb_inlineskiplist \
  --internal-key --keys 100000 --ops 1000000 --threads 8 \
  --key-size 24 --value-size 64 --output rocksdb.csv
```

On Linux, pin worker threads and bind their future allocations to a NUMA node:

```sh
./build/memtable_bench --stage 2 --threads 4 --cpu-list 0,2,4,6 \
  --numa-node 0 --index std_map --output numa.csv
```

CPU IDs must belong to the process's allowed CPU set. The NUMA option uses Linux
`set_mempolicy(MPOL_BIND)` per thread and fails if the requested binding is not
permitted. On macOS these options are rejected explicitly. For a full process
memory/CPU policy, launch through `numactl` as well. Build commands should be run
with proxy environment variables unset on hosts where that is required.

## Three stages and measurement rules

1. **Single thread:** construct an index, insert each user key once, run exact-key
   gets, freeze outside the timed region, then run bounded ordered scans. Insert order is a seeded permutation for
   `uniform`/`zipf`, sequential for `sequential`. The selected distribution controls
   read and scan start IDs. Zipf uses exponent 1.1. `scan_length` is a maximum
   per scan.
2. **Concurrent scaling:** prefill an index, then run a seeded trace of `ops`
   mixed exact-key reads and inserts/updates across `threads` workers. Reads target
   prefilled versions so all reads are hits. Without `--internal-key`, writes update
   existing keys. With it, writes insert unique newer versions. The start barrier
   excludes thread creation; throughput uses the wall time until all workers finish.
   RocksDB is append-only: stage 2 writes require `--internal-key`. Without it, a
   read-only phase (`--read-percent 100`) is allowed. Incompatible workloads are
   rejected before creating output. Duplicate exact keys return false for RocksDB,
   while the map/tree adapters implement upsert.
3. **MemTable lifecycle:** create, insert, `Freeze`, one complete ordered scan
   simulating a flush, then destroy the index. The flush verifies strict key order
   and exact row count. Freeze and destroy get separate timing rows.

The interface is `Insert`, `Get`, `NewCursor` (`Seek`, `Next`), `Scan`, and `Freeze`.
All keys and values are binary strings. `key_size` is the **user key** size (minimum
8 bytes). The first eight bytes are a big-endian user ID; a deterministic suffix
fills larger keys. `--internal-key` appends the one's complement of a big-endian
64-bit sequence and a one-byte value type. This sorts versions of the same user key
newest first. `Get` is an exact **encoded key** lookup; snapshot-visible lookup,
tombstone resolution, and compaction are not implemented.

Frozen map/tree cursors hold a native const iterator: `Seek` calls `lower_bound`
once, and each `Next` increments the iterator without a key/value copy or another
lookup. Full traversal is linear. Cursors created before Freeze retain their safe
active-table behavior, which re-seeks on `Next` to tolerate iterator invalidation
from writes. Stage 1 scan and stage 3 flush always create cursors after Freeze.
RocksDB cursors use its native iterator in both modes and return views into arena
records. An index must outlive every cursor.

The [RocksDB InlineSkipList](https://github.com/facebook/rocksdb/blob/v9.10.0/memtable/inlineskiplist.h)
adapter stores `[varint32 key length][key][varint32 value length][value]`
in `InlineSkipList::AllocateKey` storage owned by `ConcurrentArena` (64 KiB blocks,
huge pages disabled). A custom binary comparator preserves the harness's encoded
key order; this is an InternalKey-style benchmark format, not RocksDB's on-disk
InternalKey trailer format. It calls upstream `InsertConcurrently`, with no global
adapter lock. A small atomic admission/count gate lets Freeze stop new writes and
wait for admitted inserts to finish. Its overhead is included in insertion timing.
Published records remain immutable; duplicate attempts retain their unlinked arena
allocation until Destroy. `--seed` controls workload traces; upstream skiplist
height randomness is seeded by its own thread-local generator.

Workload plans and constant values are prepared outside timed regions. Timed
operations include key encoding, adapter locks, value copies, cursor work, and
one-in-64 latency sampling. The checksum prevents the scans and reads from being
discarded. Stage 1 and 3 report index growth against a pre-construction RSS sample.
Stage 2 samples RSS after prefill and trace preparation, so its RSS delta is
*additional memory during the mixed phase*, including worker stacks and runtime
allocations. RSS is process-wide and page-granular;
allocator retention can make the destroy delta smaller than the index allocation.
Run one benchmark process at a time and repeat experiments for stable comparisons.

## CSV schema

Each row is one phase. The file is appended if it exists; a new file gets the
header below. Use a new output file per experiment matrix if schemas change.

| Columns | Meaning |
| --- | --- |
| `run_id,index,adapter_mode,stage,phase` | Run epoch nanoseconds, adapter and phase |
| `threads,keys,ops,items_scanned` | Workload counts; `ops` is scan calls for stage 1 and 3 |
| `key_size,value_size,internal_key,distribution,read_percent,scan_length` | Workload parameters |
| `cpu_list,numa_node` | Requested placement; empty when absent |
| `elapsed_ns,throughput_ops_s,items_per_s` | Wall time and rates |
| `latency_p50_ns,latency_p95_ns,latency_p99_ns` | Sampled operation latency, one in 64; one sample for single-operation phases |
| `cycles_per_op,instructions_per_op,ipc` | Linux thread-local perf counters, aggregated across workers in stage 2 |
| `l1d_miss_per_op,llc_miss_per_op,branch_miss_per_op,dtlb_miss_per_op` | Linux hardware/cache misses per operation |
| `rss_before_bytes,rss_after_bytes,rss_delta_bytes,bytes_per_key` | Resident memory; bytes/key is RSS delta divided by current index count (or pre-destroy count) |
| `checksum` | Accumulated digest of observed data |

On macOS, and on Linux when `perf_event_open` is unavailable or restricted,
hardware counter fields are **empty**, never zero-filled. Linux counts exclude
kernel/hypervisor execution and are scaled by enabled/running time when multiplexed.
The counters are thread-local. A stage 2 metric is blank if any worker lacks it.
For `ordered_flush`, `items_per_s` is the useful throughput; `ops` is one scan.

## Adapter roadmap

Implementations should be integrated one at a time behind `Index`, preserving
binary ordering and per-index value ownership. Each adapter needs verification of
exact reads, seek/next order, freeze behavior, memory cleanup, and concurrent API
semantics before its `available` flag changes. In particular:

- [BTreeOLC](https://github.com/wangziqi2016/index-microbench/blob/master/BTreeOLC/BTreeOLC.h): adapt arbitrary binary keys and add a safe ordered cursor.
- [UnoDB ART](https://github.com/unodb-dev/unodb): verify byte-key encoding, range iterator, and chosen concurrency mode.
- [Masstree](https://github.com/kohler/masstree-beta): provide thread contexts and explicit value ownership.
- [HOT](https://github.com/googol-lab/hot-trie): define key extraction and value lifetime for this exact binary-key format.
- [Wormhole](https://github.com/wuxb45/wormhole): handle thread registration, iterator lifetime, and memory ownership.

Do not publish cross-index rankings until adapters implement equivalent operations
and their wrapper concurrency modes are stated alongside results.

## Layout

```text
CMakeLists.txt                  Build and pinned optional dependencies
include/memtable_bench/index.h Unified ordered-index interface
src/index.cc                   Working adapters, registry, key encoding
src/rocksdb_index.cc            Native InlineSkipList/ConcurrentArena adapter
src/main.cc                    Workloads, placement, metrics, CSV
cmake/RocksDB.cmake             Pinned upstream library configuration
cmake/FetchRocksDB.cmake         Single-branch dependency downloader
tests/adapter_contract.cc       Binary/MVCC order, cursors, duplicate policy, concurrent Freeze
```
