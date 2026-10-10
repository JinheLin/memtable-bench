# memtable-bench

A C++20 harness for comparing in-memory indexes as LSM MemTable candidates.
Supported environment: **native Linux x86-64 with GCC or Clang**. CMake rejects
other platforms and cross builds before downloading dependencies.

**RocksDB InlineSkipList is the required baseline and default index.**
The project retains five candidates. For database semantics use `mvcc_bench`:
latest published snapshots or fixed historical reads, tombstones, native or InternalKey version storage,
visible-row scans, batch submissions and complete-version flush traversal.
`memtable_bench` is the separate exact-key structural diagnostic; its
`--internal-key` option does not implement snapshot visibility.

## Status

| Candidate | Build setting | Representation / concurrency |
| --- | --- | --- |
| `rocksdb_inlineskiplist` | Required, enabled by default | Production InlineSkipList + ConcurrentArena; append-only, native concurrency |
| `btreeolc` | `MEMTABLE_BENCH_FETCH_BTREEOLC=ON` | B-tree with OLC and per-key stripes; native concurrency |
| `unodb_art` | `MEMTABLE_BENCH_FETCH_UNODB=ON` | UnoDB ART `olc_db` + QSBR; append-only, native concurrency |
| `wormhole` | `MEMTABLE_BENCH_FETCH_WORMHOLE=ON` | Native whsafe API, parked thread references |
| `cse_crossbeam` | `MEMTABLE_BENCH_CSE_SOURCE_DIR=/verified/export` | CSE native user-key version chains; concurrent readers, serialized batch writer; MVCC executable only |

CSE defaults to Crossbeam at pinned commit
`80b0309f23f387ff5835a8153263f0d00fbfdaa0`. The pruning decision and reasons for
removing std::map, Abseil, TLX, Masstree, HOT, OceanBase KeyBtree and CSE Arena are
recorded in [index selection](docs/index-selection.md). Retired adapters have no
build targets or runtime registry entries. Their historical measurements retain
their original source snapshots and reporting compatibility.

The binary's `--list-indexes` is authoritative for compiled availability.
All retained candidates are eligible for native concurrent workloads; MVCC
mixed workloads use one writer plus readers and do not measure parallel writers.
UnoDB uses terminated nibble keys (`2 * logical_key_bytes + 1` bytes); encoding,
ownership, synchronization, FFI and payload copying/hashing are timed.

## Build

Default baseline, including both executables:

```sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 8
ctest --test-dir build --output-on-failure
build/mvcc_bench --list-indexes
```

RocksDB is fetched at a fixed revision and builds with unrelated tools/tests
and optional compression libraries disabled. Disabling the required baseline
is rejected. Three optional C++ adapters default to OFF. To build them:

```sh
./scripts/build_all.sh build-core -G Ninja
```

Add CSE from an authorized local checkout:

```sh
python3 scripts/export_cse_memtable.py \
  --source ~/github/cloud-storage-engine --output vendor/cse-memtable
./scripts/build_all.sh build-core -G Ninja \
  -DMEMTABLE_BENCH_CSE_SOURCE_DIR="$PWD/vendor/cse-memtable"
```

CSE needs Python 3, Cargo and a native Linux x86-64 stable Rust toolchain. Its
export stays ignored; the repository distributes the bridge and pins only.
See [MVCC build and source boundaries](docs/mvcc.md).

Builds and downloads bypass proxies. An installed Boost is used for UnoDB;
otherwise pinned Boost 1.86 headers are fetched and SHA-256 checked. UnoDB uses
SSE4.1 with AVX2 disabled; Wormhole needs SSE4.2. Commit pins are verified even
with `FETCHCONTENT_SOURCE_DIR_<NAME>` overrides; patches are explicit and
reconfiguration is idempotent. [THIRD_PARTY.md](THIRD_PARTY.md) records licenses.
Use a fresh build directory when migrating an old all-adapter configuration;
requests to enable removed adapters fail explicitly.

## Run

```sh
mkdir -p results
# Default InlineSkipList baseline, with full MVCC visibility.
build/mvcc_bench --read-view latest --stage all --keys 100000 --versions 2 --ops 1000000 \
  --key-size 16 --value-size 32 --scan-length 100 --output results/baseline.csv

# Exact-key append workload; writes on RocksDB/UnoDB require --internal-key.
build-core/memtable_bench --index rocksdb_inlineskiplist --internal-key \
  --stage all --keys 100000 --ops 1000000 --threads 8 \
  --cpu-list 2,3,4,5,6,7,8,9 --numa-node 0 --output results/exact-key.csv

# Default quick screening: 100k keys, one repetition, all three stages.
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/mvcc-quick --cpus 2,3,4,5,6,7,8,9 --numa-node 0

# Focused million-key point/scan comparison, without concurrency or lifecycle.
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/mvcc-point-1m --profiles oltp_uniform --stages 1 \
  --keys 1000000 --ops 1000000 --cpus 2 --numa-node 0

# Formal OLTP: latest reads, uniform/Zipf, three repetitions, 1/4/8 workers.
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/mvcc-oltp --suite full --group oltp --keys 1000000 --ops 1000000 --repeats 3 \
  --threads 1,4,8 --cpus 2,3,4,5,6,7,8,9 --numa-node 0
# History: 16/64 retained versions/key, fixed first-round snapshots.
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/mvcc-history --suite full --group history --keys 1000000 --ops 1000000 --repeats 3 \
  --threads 1,4,8 \
  --cpus 2,3,4,5,6,7,8,9 --numa-node 0
python3 scripts/summarize_mvcc.py results/mvcc-oltp results/mvcc-history \
  --output results/mvcc-groups-summary
python3 scripts/plot_mvcc.py results/mvcc-groups-summary
```

Select CPU IDs from your actual topology. Missing perf access leaves PMU fields
empty. Plotting needs Matplotlib/NumPy; validation uses Python's standard library.
The default `quick` suite has **45 processes / 150 phase rows** with all five
candidates, both OLTP profiles and history v16. It is a one-repetition screening
run. `--suite full` retains **150 processes / 420 rows per group**, **300 / 840**
together, including history v64. `--suite smoke` uses small inputs for correctness.
Use `--list-plan` to see total prefill versions before running, `--stages 1`
(or `2` / `3`) to focus on a phase, and the same command with `--resume` after interruption.
Resume verifies source/binary/configuration and completed command/CSV/log hashes;
process wall times include setup, prefill, validation and destruction.
The [Linux runtime verification](docs/test-results/2026-10-10/mvcc-runtime/README.md)
completed the default quick suite in 62.35 s and a focused million-key
five-index Get/scan comparison in 36.53 s; these are different scopes from full.
OLTP reads the latest completed batch at request start;
history holds a fixed old view. Mixed reader latency is point-only by default;
stage 1 still measures dedicated visible scans. Separate group reports are
`report-oltp.md` and `report-history.md`; the CSV protocol is now `mvcc-v2`.
Availability is discovered from the binary; without the CSE export it has four
candidates. No Arena-specific smaller cohorts are needed in the current plan.
See [MVCC semantics and CSV schema](docs/mvcc.md).

## Controlled key / prefix / value experiments

Workload controls include key/value widths, scale, uniform/sequential/Zipf
access, insert order, global/group prefixes, thread count, read/write mix,
scan length, scan calls, batch size, history depth, snapshot lag and deletions.
Precomputed corpora separate key generation from timing and record dataset
hashes and adjacent-user-key LCP statistics. Prefix length excludes the MVCC
trailer. `--hotspot-placement spread|clustered` controls Zipf rank placement.

For the exact-key diagnostic, `--measure-detail` separates Contains/GetCopy,
Seek/cursor navigation and payload hashing. `--scan-only --scan-ops N` isolates
SeekOnly, cursor traversal and payload scan with identical starting keys.

```sh
python3 scripts/benchmark_matrix.py --list-plan
python3 scripts/sensitivity_matrix.py --suite screening --list-plan
python3 scripts/sensitivity_matrix.py --suite representative --list-plan
python3 scripts/sensitivity_matrix.py --suite range-scan --list-plan
```

The current four-index defaults schedule **160** original-matrix processes,
**240** screening processes, **192** representative processes and **120**
range-scan processes. Exact-key runners record dependency pins, command lines,
placement and fresh-process repetitions. These diagnostics and MVCC results
use different workload semantics and CSV schemas; keep their statistics separate.

## Published measurements

The [completed two-group MVCC million-key run](benchmarks/mvcc-groups-formal-1m-2026-10-09/README.md)
has **300 processes / 840 phase rows**, all five retained candidates, three
repetitions and 1/4/8 workers. OLTP measures latest published versions with
uniform/Zipf access; history measures fixed first-round snapshots with 16/64
retained versions per key. All 480 read/mixed/flush rows match independent
oracle digests; another 120 writer rows have no read content to hash.
[OLTP tables](benchmarks/mvcc-groups-formal-1m-2026-10-09/summary/report-oltp.md)
and [history tables](benchmarks/mvcc-groups-formal-1m-2026-10-09/summary/report-history.md)
include operation, scan, memory, SWMR and lifecycle results.

The [completed historical MVCC matrix](benchmarks/mvcc-formal-1m-2026-10-08/README.md)
has **906 processes / 2,928 rows**, three repetitions and 288 matching content/count
comparison groups. It was measured before pruning, with twelve candidates and
CSE Arena's separate smaller cohorts. The archive is the evidence for the
selection decision; its rows and figures still include retired candidates.

[Benchmark archives](benchmarks/README.md) also retain earlier exact-key suites.
Measurements ran serially on a shared Xeon Gold 6240 server with physical CPU
and NUMA binding, without frequency locking or reserved CPUs. The current code
and archived measurement source revisions can differ. See [verification](docs/testing.md)
for the scope of actual test and workload runs.

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
   Every retained adapter supports native concurrency and is eligible for multiple workers.
   RocksDB and UnoDB are append-only: stage 2 writes require `--internal-key`. Without it, a
   read-only phase (`--read-percent 100`) is allowed. Incompatible workloads are
   rejected before creating output. Duplicate exact keys return false for these two adapters; the other adapters
   implement upsert.
3. **MemTable lifecycle:** create, insert, `Freeze`, one complete ordered scan
   simulating a flush, then destroy the index. The flush verifies strict key order
   and exact row count. Freeze and destroy get separate timing rows.

The interface is `Insert`, `Get`, `Contains`, `NewCursor` (`Seek`, `Next`), `Scan`, and `Freeze`.
All keys and values are binary strings. `key_size` is the **user key** size (minimum
8 bytes). In legacy mode the first eight bytes are a big-endian user ID; a deterministic suffix
fills larger keys. `--internal-key` appends the one's complement of a big-endian
64-bit sequence and a one-byte value type. This sorts versions of the same user key
newest first. `Get` is an exact **encoded key** lookup; snapshot-visible lookup,
tombstone resolution, and compaction are not implemented.

Stage 1 scans and stage 3 flush create native cursors after Freeze. RocksDB
cursors return views into arena records. An index must outlive every cursor.

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
operations in legacy inline mode include key encoding, adapter locks, value copies, cursor work, and
one-in-64 latency sampling. The checksum prevents the scans and reads from being
discarded. Stage 1 and 3 report index growth against a pre-construction RSS sample.
Stage 2 samples RSS after prefill and trace preparation, so its RSS delta is
*additional memory during the mixed phase*, including worker stacks and runtime
allocations. RSS is process-wide and page-granular;
allocator retention can make the destroy delta smaller than the index allocation.
Run one benchmark process at a time and repeat experiments for stable comparisons.

## CSV schema

Each row is one phase. The file is appended if it exists; a new file gets the
header described below. Existing files with a different header are rejected
without appending. Schema v3 has **55 columns**: the original 36 columns followed
by 19 key/measurement fields. Use a new output file for previous 35/36-column files.
Historical reports and raw files remain unchanged.

| Columns | Meaning |
| --- | --- |
| `run_id,index,adapter_mode,stage,phase` | Run epoch nanoseconds, adapter and phase |
| `threads,keys,ops,items_scanned` | Workload counts; `ops` counts the row's phase operations/calls, and `items_scanned` counts returned rows |
| `key_size,value_size,internal_key,distribution,read_percent,scan_length` | Workload parameters |
| `cpu_list,numa_node` | Requested placement; empty when absent |
| `elapsed_ns,throughput_ops_s,items_per_s` | Wall time and rates |
| `latency_p50_ns,latency_p95_ns,latency_p99_ns` | Sampled operation latency, one in 64; one sample for single-operation phases |
| `cycles_per_op,instructions_per_op,ipc` | Linux thread-local perf counters, aggregated across workers in stage 2 |
| `l1d_miss_per_op,llc_miss_per_op,branch_miss_per_op,dtlb_miss_per_op` | Linux hardware/cache misses per operation |
| `rss_before_bytes,rss_after_bytes,rss_delta_bytes,bytes_per_key` | Resident memory; bytes/key is RSS delta divided by current index count (or pre-destroy count) |
| `checksum` | Accumulated digest of observed data |
| `adapter_key_encoding` | `binary` or `nibble_terminated`; column 36 |
| `schema_version,key_layout,prefix_bytes,prefix_groups,key_preparation,insert_order,hotspot_placement,measure_detail` | Schema 3 and independent key/workload controls |
| `logical_key_bytes,physical_key_bytes` | User key + trailer length; adapter encoded-key length |
| `dataset_hash,lcp_min,lcp_p50,lcp_p95,lcp_p99,lcp_max,lcp_mean` | Precomputed input digest and adjacent-user-key LCP; blank in inline mode |
| `logical_payload_bytes,payload_gb_s` | Logical byte volume for Insert/GetCopy/full Scan and decimal GB/s; rate blank for other phases |

When `perf_event_open` is unavailable or restricted, hardware counter fields
are **empty**, never zero-filled. Counts exclude
kernel/hypervisor execution and are scaled by enabled/running time when multiplexed.
The counters are thread-local. A stage 2 metric is blank if any worker lacks it.
For `ordered_flush`, `items_per_s` is the useful throughput; `ops` is one scan.

## Research adapter integration notes

- **BTreeOLC:** upstream nodes require trivially copyable keys, so the adapter
  stores one-word pointers to binary views over immutable owned records. Its upstream `scan` stops at
  one leaf; active cursors perform an optimistic path traversal, while frozen
  cursors increment through native leaf arrays using a parent stack. Individual
  records, including overwritten values, stay alive until Destroy. Equal keys are
  serialized by a 256-stripe mutex array because upstream `insert` returns no
  created/upsert result. The extra lookup, stripes and record allocations are
  timed. The patch fixes empty-node `lowerBound`, uninitialized lookup misses,
  missing standalone headers. The upstream OLC page fields use
  plain reads under version validation; ASan/UBSan success is not a proof of
  C++ data-race freedom. TSan cleanliness is not claimed.
- **UnoDB ART:** uses `olc_db<key_view,value_view>` and QSBR. Terminated nibble
  encoding removes embedded zero bytes and makes keys prefix-free. The thread
  registration patch exposes an idempotent registration method for the harness's
  ordinary `std::thread` workers; upstream TLS destruction unregisters them.
  Every operation/movement announces quiescence. An idle registered thread can
  delay QSBR reclamation until it resumes or exits; the memory measurement includes
  this behavior. Live cursors use public `scan_from`, copy one record, and re-seek
  for the next movement. Frozen cursors use the pinned internal
  `test_only_iterator()` API for native linear traversal, decoding each key.
  An explicit iterator patch copies the restart key before mutable traversal
  and corrects the keyless-leaf lower-bound comparison. The copy cost is timed.
  This internal API makes the commit pin part of the adapter's compatibility
  contract. No update/remove operation is exposed.
  This pinned revision uses keyless leaves for `key_view`: complete keys are
  represented in inode paths and reconstructed by iterators. Single-child I4
  chains consume at most seven prefix bytes plus one dispatch byte per node.
  With nibble encoding, long unshared keys create many such nodes, so memory
  and traversal results are specific to this policy and adapter encoding.
- **Wormhole:** uses native `whsafe_get`/`whsafe_merge`, with one parked reference
  per participating thread, owned by the index. The native merge callback under
  the leaf lock gives accurate size accounting for concurrent upserts. Active
  cursors copy a record and park after each movement so a retained cursor cannot
  deadlock a write in the same thread. Frozen cursors use native `whunsafe`
  iteration after admitted writes drain. The assembly patch uses newline-separated
  instructions and portable 16-byte alignment for the coroutine helper symbols
  in the pinned upstream code. The unaligned-load patch replaces typed CRC/common-prefix
  reads from byte buffers with memcpy, preserving arbitrary view alignment.
  Legacy exact-key archives predate this fix; the formal MVCC archive includes it. Complete keys are capped at 65535 bytes; values must
  fit uint32. The default memory manager duplicates accepted key/value records.

None of these adapters constructs a separate sorted container for flush scans.
All three native concurrent research adapters include the admission/drain gate in
Insert/Freeze timing. Upsert adapters can retain old records to protect cursors;
append-only InternalKey workloads are the most representative common comparison.

## Layout

```text
include/memtable_bench/       Ordered-index/MVCC contracts, datasets and measurements
src/index.cc                 Registry, common Scan and InternalKey encoding
src/*_index.cc               RocksDB, BTreeOLC, UnoDB, Wormhole and CSE adapters
src/main.cc                  Exact-key diagnostic and CSV v3
src/mvcc_main.cc             Latest/historical MVCC workloads and CSV mvcc-v2
src/mvcc.cc                  Visibility, version cursors and flush
rust/cse_memtable/           Pinned Crossbeam bridge and source/dependency checks
cmake/                      Fixed dependency downloads and upstream patches
scripts/build_all.sh         Proxy-free retained-adapter build/test entry point
scripts/mvcc_matrix.py       OLTP/history workload matrices
scripts/mvcc_workloads.py    Group parameters and phase/comparison rules
scripts/summarize_mvcc.py    Cohort validation and median/quartile reports
scripts/plot_mvcc.py         Optional PNG/SVG figures
scripts/*matrix.py          Exact-key diagnostic matrices
scripts/*summarize*.py       Current and archived result reporting
tests/                      Contracts, workload/oracle and policy checks
docs/index-selection.md     Retained/removed candidates and reasons
benchmarks/                 Immutable measured archives and source snapshots
results/                    Ignored output for new experiments
```
