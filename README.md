# memtable-bench

A C++20 harness for comparing ordered in-memory indexes as LSM MemTable candidates.
It starts with a working `std::map` reference adapter. Abseil B-tree and TLX B+Tree
are optional, buildable adapters. The remaining candidates have named, unavailable
adapter slots with explicit integration work; the harness never substitutes one
data structure for another.

## Status

| Adapter name | Implementation | Build status | Concurrency in this harness |
| --- | --- | --- | --- |
| `std_map` | `std::map` | Default | Coarse reader/writer lock |
| `abseil_btree` | Abseil `btree_map` | Optional FetchContent | Coarse reader/writer lock |
| `tlx_btree` | TLX `btree_map` (B+Tree) | Optional FetchContent | Coarse reader/writer lock |
| `rocksdb_inlineskiplist` | RocksDB InlineSkipList | Stub | Not measured |
| `btreeolc` | BTreeOLC | Stub | Not measured |
| `unodb_art` | UnoDB ART | Stub | Not measured |
| `masstree` | Masstree | Stub | Not measured |
| `hot` | HOT | Stub | Not measured |
| `wormhole` | Wormhole | Stub | Not measured |

`--list-indexes` reports the status of the actual binary. Requesting an unavailable
adapter exits with an error before creating the result file. The three working
adapters use the same owned `std::string` key/value format and the same coarse lock.
Their stage 2 measurements are **wrapper scalability**, not native concurrent-index
scalability. Native stage 2 results must wait for native adapters.

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
(tag `v0.6.1`). Keep these pins fixed within an experiment series. Dependencies
retain their own licenses; this repository's MIT license covers only its own code.

## Run

```sh
./build/memtable_bench --stage all --index std_map \
  --keys 100000 --ops 1000000 --key-size 16 --value-size 64 \
  --distribution uniform --threads 8 --read-percent 80 \
  --scan-length 100 --output results.csv

./build/memtable_bench --stage 3 --index std_map --internal-key \
  --keys 100000 --key-size 24 --value-size 128 \
  --distribution zipf --output lifecycle.csv
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
   gets, then bounded ordered scans. Insert order is a seeded permutation for
   `uniform`/`zipf`, sequential for `sequential`. The selected distribution controls
   read and scan start IDs. Zipf uses exponent 1.1. `scan_length` is a maximum
   per scan.
2. **Concurrent scaling:** prefill an index, then run a seeded trace of `ops`
   mixed exact-key reads and inserts/updates across `threads` workers. Reads target
   prefilled versions so all reads are hits. Without `--internal-key`, writes update
   existing keys. With it, writes insert unique newer versions. The start barrier
   excludes thread creation; throughput uses the wall time until all workers finish.
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

- [RocksDB InlineSkipList](https://github.com/facebook/rocksdb/blob/main/memtable/inlineskiplist.h): pair its arena allocation and comparator with the correct memtable key encoding; handle lifetime and concurrent insert semantics.
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
src/main.cc                    Workloads, placement, metrics, CSV
tests/adapter_contract.cc       Binary order, cursor, upsert, freeze contracts
```
