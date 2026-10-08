# memtable-bench

A C++20 harness for comparing ordered in-memory indexes as LSM MemTable candidates.
Supported environment: **native Linux x86-64 with GCC or Clang**. CMake rejects
other operating systems, architectures and cross builds before fetching dependencies.
The reference `std::map` adapter has no external dependencies. Nine optional
index adapters are implemented with pinned upstream sources. The actual binary's
`--list-indexes` output is authoritative, including CPU restrictions and key limits.

For MVCC databases, use **`mvcc_bench`**. It adds `cse_arena` and `cse_crossbeam`
from cloud-storage-engine, and runs twelve candidates with snapshot reads,
tombstones, visible-row range scans, batched writes and complete-version flushes.
See [MVCC workloads, CSE build instructions and CSV schema](docs/mvcc.md).
The new `oceanbase_keybtree` is a port of OceanBase's actual MemTable ordered
index core. Its MVCC workload uses the common InternalKey adapter.
OceanBase integration is limited to KeyBtree; `ObMemtable` is outside the project's scope.
See [OceanBase KeyBtree scope and build instructions](docs/oceanbase.md).
The original `memtable_bench` remains the exact-key structural diagnostic;
its `--internal-key` option alone does not implement snapshot visibility.

## Status

| Adapter | CMake option suffix | Concurrency in this harness | Benchmark workers | Key limit |
| --- | --- | --- | --- | --- |
| `std_map` | Default | Coarse reader/writer lock | 1 only | Allocation limits |
| `abseil_btree` | `ABSEIL` | Coarse reader/writer lock | 1 only | Allocation limits |
| `tlx_btree` | `TLX` | Coarse reader/writer lock | 1 only | Allocation limits |
| `rocksdb_inlineskiplist` | `ROCKSDB` | Native concurrent insert; append-only | 1 and multiple | uint32 record lengths |
| `btreeolc` | `BTREEOLC` | Native OLC pages + 256 key stripes for exact size/upsert | 1 and multiple | Allocation limits |
| `unodb_art` | `UNODB` | UnoDB `olc_db`, QSBR; append-only | 1 and multiple | Encoded key/value lengths fit uint32 |
| `masstree` | `MASSTREE` | Native Masstree locks + deferred node/value reclamation | 1 and multiple | 1024 bytes |
| `hot` | `HOT` | HOTSingleThreaded + coarse reader/writer lock | 1 only | 127 bytes |
| `wormhole` | `WORMHOLE` | Native `whsafe` API + parked thread references | 1 and multiple | 65535 bytes |
| `oceanbase_keybtree` | `OCEANBASE` | KeyBtree core port; native COW/epoch algorithms; append-only | 1 and multiple | Allocation limits |
| `cse_arena` (`mvcc_bench`) | `CSE_SOURCE_DIR` | Native version chains, concurrent reads, serialized batch writer | 1 and SWMR | 65535-byte user key |
| `cse_crossbeam` (`mvcc_bench`) | `CSE_SOURCE_DIR` | Native version chains, concurrent reads, serialized batch writer | 1 and SWMR | 65535-byte user key |

Multithreaded workloads are restricted to the integrated implementation's
**native** read/write concurrency. `std_map`, Abseil, TLX and the current
HOTSingleThreaded adapter run only with `--threads 1`, including read-only
workloads. Their compatibility locks remain part of single-thread measurements.
HOT ROWEX is not integrated. `--list-indexes` publishes `native_concurrent=0/1`;
the runners check this capability before executing a matrix, and the harness
rejects an ineligible thread count before creating CSV or dataset output.

The nine optional index switches are named `MEMTABLE_BENCH_FETCH_<SUFFIX>` and
default to OFF. CSE uses `MEMTABLE_BENCH_CSE_SOURCE_DIR`, an optional path to the
verified local export; its two candidates are listed by `mvcc_bench`.
These adapters use the actual upstream index; unavailable adapters fail before
creating a result file. HOT requires x86-64 with AVX2, BMI, BMI2, POPCNT and LZCNT.
The compiled binary checks HOT CPU features before entering its translation unit.

**Native Linux validation (2026-10-08):** GCC 11.3.1 on Xeon Gold 6240:
all twelve runnable MVCC candidates, including OceanBase KeyBtree, HOT and both
CSE backends, passed 17/17 contract/workload/policy tests. The prior eleven-candidate run passed 15/15
contract/workload/policy tests. The existing exact-key harness remains covered.
The MVCC pilot completed 160 processes / 524 phase rows with matching contents;
see [verification](docs/testing.md) and [pilot records](benchmarks/mvcc-pilot-2026-10-08/README.md).
The workload tests also run with node 0 memory binding and pinned physical cores.

**Completed MVCC matrix (2026-10-09):** six cohorts, three repetitions each,
**906 processes / 2,928 phase rows**, with matching counts and contents in all
288 comparisons. Four cohorts with one million user keys cover base, deep history,
shared prefix and 1 KiB values. CSE Arena reaches its native capacity limits in
the deep-history and large-value cases; separate matched
500k/100k-key cohorts include all twelve candidates. Single-thread-only indexes
do not enter multithreaded runs. See the
[protocol and findings](benchmarks/mvcc-formal-1m-2026-10-08/README.md) and
[complete tables](benchmarks/mvcc-formal-1m-2026-10-08/summary/report.md).

**Measured on that server:** the original 1M-record matrix has five repetitions.
The [current comparison view](benchmarks/native-concurrency-2026-10-08/README.md)
keeps nine single-thread indexes and five native concurrent indexes at
1/2/4/8/16 physical cores. See its
[report](benchmarks/native-concurrency-2026-10-08/original/report.md),
[comparison](benchmarks/native-concurrency-2026-10-08/original/comparison.png) and
[raw CSV](benchmarks/xeon79-2026-10-08/raw.csv).
The report states the workload, synchronization/codec differences and limitations;
new runs in `results/` are ignored by Git. Selected completed experiments are
published in [benchmarks/](benchmarks/README.md), with raw data and compressed
per-process records. [Verification logs](docs/testing.md) accompany the source.

All adapters receive identical logical binary keys and values. UnoDB and HOT
store order-preserving terminated nibble keys: `2 * logical_key_bytes + 1` bytes.
CSV records this as `adapter_key_encoding=nibble_terminated`; other adapters use
`binary`. Encoding, decoding and record ownership costs are included in results.
See the integration notes below before comparing memory or concurrent throughput.

## Layout

```text
include/memtable_bench/  Index/cursor contracts and dataset definitions
src/                    Harness, datasets and concrete index adapters
cmake/                  Pinned dependency setup and explicit upstream patches
rust/                   Standalone CSE bridge, locked Rust dependencies and source pins
vendor/oceanbase-port/  Pinned source digests and standalone runtime glue
tests/                  Adapter, dataset and workload checks
scripts/                Build, experiment, summary and plotting tools
benchmarks/             Published measurements and compressed per-process records
docs/                   Verification notes and captured test logs
results/                Ignored output directory for new experiments
```

## Build

```sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 4
ctest --test-dir build --output-on-failure
```

The default build has no downloaded dependencies. Enable all optional adapters
with the proxy-free build script:

```sh
./scripts/build_all.sh build-all -G Ninja
```

To enable only the five research indexes:

```sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cmake -S . -B build-research -DCMAKE_BUILD_TYPE=Release \
  -DMEMTABLE_BENCH_FETCH_BTREEOLC=ON -DMEMTABLE_BENCH_FETCH_UNODB=ON \
  -DMEMTABLE_BENCH_FETCH_MASSTREE=ON -DMEMTABLE_BENCH_FETCH_HOT=ON \
  -DMEMTABLE_BENCH_FETCH_WORMHOLE=ON
cmake --build build-research -j 4
ctest --test-dir build-research --output-on-failure
./build-research/memtable_bench --list-indexes
```

Optional indexes may require additional CPU instructions. HOT requires AVX2,
BMI/BMI2, POPCNT and LZCNT; Wormhole uses SSE4.2. UnoDB uses SSE4.1, with AVX2
explicitly disabled in this integration. Run on native hardware supporting the
requested adapters. CSE also requires a native Linux x86-64 stable Rust toolchain.

The five new integrations use full commit pins, and configuration verifies the checked-out
commit even with `FETCHCONTENT_SOURCE_DIR_<NAME>` overrides. For the five new
libraries, `cmake/FetchGit.cmake` performs a proxy-free shallow fetch;
`cmake/patches/` contains all changes to upstream code. Reconfiguration is
idempotent and fails if a patch cannot apply to the expected sources.
An installed Boost is used for UnoDB; otherwise pinned Boost 1.86 headers are
fetched with a SHA-256 check. Upstream developer static-analysis tools, tests,
servers and benchmarks are excluded from this embedded build.
RocksDB compiles its support library with tools, tests and optional compression
libraries disabled. Pins and license details are in [THIRD_PARTY.md](THIRD_PARTY.md).

## Run

```sh
./build/memtable_bench --stage all --index std_map \
  --keys 100000 --ops 1000000 --key-size 16 --value-size 64 \
  --distribution uniform --threads 1 --read-percent 80 \
  --scan-length 100 --output results.csv

./build/memtable_bench --stage 3 --index std_map --internal-key \
  --keys 100000 --key-size 24 --value-size 128 \
  --distribution zipf --output lifecycle.csv

./build-rocksdb/memtable_bench --stage all --index rocksdb_inlineskiplist \
  --internal-key --keys 100000 --ops 1000000 --threads 8 \
  --key-size 24 --value-size 64 --output rocksdb.csv
```

For the native concurrent indexes, use the exact-key append workload below for
structure diagnostics (one result file per index). Use `mvcc_bench` for database
snapshot visibility; its workloads and CSV schema are described in [docs/mvcc.md](docs/mvcc.md):

```sh
for index in btreeolc unodb_art masstree wormhole; do
  ./build-research/memtable_bench --stage all --index "$index" --internal-key \
    --keys 100000 --ops 1000000 --threads 8 --key-size 24 --value-size 64 \
    --scan-length 100 --distribution uniform --output "$index.csv"
done
# HOTSingleThreaded uses --threads 1, even on a supported native x86 CPU.
```

On Linux, pin worker threads and bind their future allocations to a NUMA node:

```sh
./build-research/memtable_bench --stage 2 --threads 4 --cpu-list 0,2,4,6 \
  --numa-node 0 --index btreeolc --internal-key --output numa.csv
```

CPU IDs must belong to the process's allowed CPU set. The NUMA option uses Linux
`set_mempolicy(MPOL_BIND)` per thread and fails if the requested binding is not
permitted. For a full process memory/CPU policy, launch through `numactl` as well. Build commands should be run
with proxy environment variables unset on hosts where that is required.

### Reproducible Linux matrix

The standard-library-only runner requires all nine adapters and `numactl`.
It verifies that the chosen CPUs are allowed, belong to the selected NUMA node,
and contain no SMT siblings. Select CPU IDs from your own machine's topology.
This example uses 16 physical cores on node 0 of the Xeon test server:

```sh
python3 scripts/benchmark_matrix.py --list-plan
python3 scripts/benchmark_matrix.py --binary build-linux/memtable_bench \
  --output results/new-run --cpus 2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17 \
  --numa-node 0 --keys 1000000 --ops 1000000 --repeats 5 --threads 1,2,4,8,16
python3 scripts/summarize_benchmark.py results/new-run
```

The output directory must be new. Runs are serial in randomized interleaved
order, each in a fresh process. Nine excluded warmups precede **280 formal runs** at defaults:
uniform/Zipf single-thread, uniform lifecycle, and uniform 80/20 mixed workloads
at five thread counts. Single-thread scenarios (including mixed_t1) use all nine
indexes; counts above one use only the five native concurrent indexes. Both
runners add mixed_t1 if --threads omits it. Each scenario uses identical seeds
across its eligible adapters;
operation counts, returned row counts and checksums must agree.
`metadata.json` records CPU topology, affinity, NUMA policy, background load,
compiler, dependency pins, binary hash, `concurrency_policy` and per-scenario
`scenario_indexes`. `raw.csv` adds scenario/repeat/seed/
run_sequence/process_elapsed_s to the harness schema. The summarizer validates
completeness and produces `summary.csv` (median/Q1/Q3/min/max/sample count) and
`report.md`. Retain per-process `runs/` logs and `commands.jsonl` with the report.
Frequency is not locked, and CPUs are not reserved against unrelated processes.

To exercise NUMA binding during the Linux harness integration test:

```sh
MEMTABLE_BENCH_REQUIRE_HOT=1 MEMTABLE_BENCH_TEST_NUMA_NODE=0 \
  MEMTABLE_BENCH_TEST_CPUS=2,3,4,5 ctest --test-dir build-linux --output-on-failure
```

## Controlled key / prefix / value experiments

`--key-layout` and `--distribution` are independent: the former controls key
bytes; the latter selects access ranks. Defaults remain `legacy` and `inline`
for historical workloads. New layouts require `--key-preparation precomputed`:

| Layout | Parameters and guarantees |
| --- | --- |
| `legacy` | Original big-endian ID plus deterministic suffix |
| `random` | No artificial prefix; reversible uint64 ID permutation ensures unique first 8 suffix bytes |
| `global-prefix` | All user keys share `--prefix-bytes P`; requires `P > 0` and `K-P >= 8` |
| `group-prefix` | `--prefix-groups G` balanced ID-modulo groups; each shares P bytes; requires P >= 8, K-P >= 8, 2 <= G <= keys |

Generated keys are synthetic pseudorandom bytes, not cryptographic samples or
production traces. Distinct group prefixes are guaranteed by their first eight
bytes. The same seed and IDs share a suffix across key-length sweeps. Keys and
all new MVCC write versions are materialized outside timing into contiguous
buffers. Input buffers remain resident during measurement; insertion RSS growth
starts after input preparation. They still affect cache traffic and memory use.

`--insert-order random|sorted|reverse` controls insertion independently of access.
`auto` preserves the original rule: sequential access uses sorted insertion,
otherwise random. With precomputed keys, `--hotspot-placement spread` maps access
ranks through an independently seeded random ID permutation; `clustered` maps
ranks through lexicographic order. This matters for Zipf's hottest ranks.
Sequential accesses always follow lexicographic order. Legacy inline traces use
original IDs. Changing byte layouts preserves the spread trace's ID ordering.

`--dataset-output FILE.json` writes an exact histogram of sorted adjacent **user
key** LCP, excluding the MVCC trailer. It includes min/p50/p95/p99/max/mean and a
non-cryptographic FNV-1a dataset digest. Quantiles use the lower rank
`floor(q*(pairs-1))`; a one-key dataset has zero pairs and zero statistics.

```sh
./build/memtable_bench --stage all --index std_map --internal-key \
  --key-preparation precomputed --key-layout group-prefix \
  --key-size 64 --prefix-bytes 24 --prefix-groups 1024 --value-size 1024 \
  --insert-order random --distribution zipf --hotspot-placement clustered \
  --measure-detail --keys 100000 --ops 100000 --threads 1 \
  --dataset-output dataset.json --output detail.csv
```

### Split measurements

`--measure-detail` adds exact `lookup_only` through each index's native `Contains`
without value copies, `scan_iterate` with bounded Seek/Next, and
`ordered_traverse` in the lifecycle stage. Cursor-only measurements consume row
count, key length and first byte; they retain native cursor/codec costs and do
not hash/copy the full value. Existing `get` remains GetCopy. `scan` and
`ordered_flush` retain full key/value checksum processing. Complete frozen key,
value, order and row-count validation runs outside cursor timing first.
Fixed phase order measures warmed steady-state paths: Insert, LookupOnly,
GetCopy, frozen validation, cursor scan, payload scan. It is not a cold-cache
comparison; LookupOnly and GetCopy are descriptive measurements, and subtracting
their times does not isolate a precise memcpy cost.

`payload_gb_s` uses decimal GB: GetCopy counts copied value bytes; Insert and full
Scan count logical key+value bytes. It is not measured physical memory bandwidth.
LookupOnly, cursor-only, mixed, Freeze and Destroy leave this metric blank.
`physical_key_bytes` is the encoded key length, not total per-record storage;
HOT also retains the original logical key.

### Screening and representative suites

```sh
python3 scripts/sensitivity_matrix.py --list-plan
python3 scripts/sensitivity_matrix.py --binary build-linux/memtable_bench \
  --output results/key-screening --cpus 2 --numa-node 0 \
  --keys 1000000 --ops 1000000 --repeats 3
python3 scripts/summarize_sensitivity.py results/key-screening

python3 scripts/sensitivity_matrix.py --suite representative \
  --binary build-linux/memtable_bench --output results/key-representative \
  --cpus 2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17 --numa-node 0 \
  --keys 1000000 --ops 1000000 --repeats 3 --threads 1,4,16
python3 scripts/summarize_sensitivity.py results/key-representative
```

Choose physical CPU IDs from your server's topology. Output directories must be
new; all selected adapters must be available. `--indexes` and `--configs` select
explicit subsets for pilots or follow-up experiments. The plan is deterministic;
config/workload/adapter execution order is shuffled and recorded. Each process
gets the same logical dataset/trace for its comparison. Warmups are excluded.

The screening suite has 12 one-factor/group configurations around K=64/V=64,
then eight K=32/112, P=0/24, V=8/1024 factorial combinations: **20 configs × 9
adapters × 3 repeats = 540 formal processes, 2700 phase rows**. User key lengths
8/16/32/64/112 B, global prefixes 0/8/24/56 B, values 8/64/1024 B and 16/1024
balanced prefix groups all fit HOT's current key limit with the MVCC trailer.
The representative suite has random/global-56/group-1024/large-value profiles,
three mixed thread counts and lifecycle: **336 formal processes** at defaults
(`4 profiles × (9 mixed_t1 + 5 mixed_t4 + 5 mixed_t16 + 9 lifecycle) × 3 repeats`).
It exercises existing stages without multiplying every screening configuration.

**Completed screening (2026-10-08):** all 540 formal processes and 2700 phase
rows completed on the Xeon server with 1M records/operations, three seeds,
CPU 2 and NUMA node 0. Cross-adapter contents/counts/checksums matched, and no
hardware-counter fields were missing. See the local
[report](benchmarks/sensitivity-screening-2026-10-08/report.md),
[memory/cache diagnostics](benchmarks/sensitivity-screening-2026-10-08/diagnostics.md),
[figure](benchmarks/sensitivity-screening-2026-10-08/sensitivity.png), and
[raw CSV](benchmarks/sensitivity-screening-2026-10-08/raw.csv).
The archived source and build/test logs accompany the results.
The representative suite also passed a 10k-record, one-repeat pilot across all
nine single-thread adapters and five native concurrent adapters at 4/16 workers
in the [current view](benchmarks/native-concurrency-2026-10-08/representative-pilot/report.md);
its full-size run is pending. Historical wrapper multithreaded data are excluded
from that view and preserved in the original archive.
The dependency-free local baseline passed four ASan/UBSan tests.

Raw sensitivity CSV adds config_id/scenario/repeat/seed/run_sequence/
process_elapsed_s to harness v3. The summarizer requires complete runs, validates
cross-adapter counts/digests and dataset histograms, then exports metric
median/Q1/Q3/min/max/sample counts, dataset statistics, and a report.
Optional figures require Matplotlib and NumPy:

```sh
python3 scripts/plot_sensitivity.py results/key-screening
```

Three repeats
are screening estimates; extend selected cases to five before making close
ranking claims. These results are not directly comparable to old inline-ID runs.
Fixed memory-budget stopping, external-value-handle diagnostics, variable key
lengths within a dataset and >118 B user-key extension groups are future work.

### Dedicated range-scan auxiliary suite

The ordinary stage-1 `scan_iterate` and `scan` already perform bounded range
scans from `lower_bound(start)`. The screening suite fixes their limit at 100.
Use `--scan-only --stage 1` to prefill/freeze/validate outside timing and measure
three separate phases: `seek_only`, `scan_iterate`, and `scan`. SeekOnly includes
cursor creation, Seek and bounded key consumption, with no Next or value access.
The other two phases also include Seek; subtracting times does not isolate pure
Next cost. All measurements use frozen indexes and warm paths.

`--scan-ops N` explicitly chooses the number of calls for this mode; without it,
the count remains `max(1, ops/scan-length)`. Actual CSV `ops` is the call count.
`items_scanned` is the true returned row count, including EOF truncation.
The CSV remains schema v3/55 columns; `seek_only` identifies this auxiliary mode.

```sh
./build/memtable_bench --stage 1 --scan-only --scan-ops 1000 \
  --scan-length 1000 --index std_map --internal-key \
  --key-preparation precomputed --key-layout random --key-size 64 --value-size 64 \
  --keys 1000000 --output range.csv

python3 scripts/sensitivity_matrix.py --suite range-scan --list-plan
python3 scripts/sensitivity_matrix.py --suite range-scan \
  --binary build-linux/memtable_bench --output results/range-scans \
  --cpus 2 --numa-node 0 --keys 1000000 --repeats 3 \
  --scan-lengths 1,10,100,1000,10000 --scan-calls 1000
python3 scripts/summarize_sensitivity.py results/range-scans
python3 scripts/diagnose_range_scan.py results/range-scans
python3 scripts/plot_range_scan.py results/range-scans
```

Defaults compare 64 B user keys/64 B values with random keys and a 56 B shared
prefix: 10 configurations, 270 formal processes and 810 phase rows. Lengths use
identical start sequences and call counts per layout/seed. Longer lengths do more
work; the report shows actual rows, rows/s and whole-scan latency. Enough calls
are needed for tail latency (one-in-64 sampling); short pilots are functional
checks. These are start-plus-row-limit scans. Explicit end-key bounds, concurrent
scan/write mixtures and snapshot-visible version filtering are not implemented.

**Measured (2026-10-08):** all nine adapters on the native Xeon completed the million-record
sweep: 1,000 calls per length, three repeats, 270 processes and 810 phase rows.
All adapter row counts/checksums agree; all six PMU events were available.
See the [full report](benchmarks/range-scan-1m-2026-10-08/report.md),
[summary and per-row costs](benchmarks/range-scan-1m-2026-10-08/diagnostics.md),
[figure](benchmarks/range-scan-1m-2026-10-08/range-scan.png) and
[cost CSV](benchmarks/range-scan-1m-2026-10-08/scan-costs.csv).
For random keys and a 10,000-row limit, TLX achieved 18.93 Mrows/s cursor traversal
and 3.83 Mrows/s full-payload checksum scanning; InlineSkipList achieved 9.85 and
3.59 Mrows/s. These include Seek and actual EOF truncation. Each phase/repeat has
only 16 latency samples, so sampled p99 is not a stable tail estimate.

The earlier [10k pilot](benchmarks/range-scan-pilot-2026-10-08/report.md) validated the
suite. The unchanged native binary previously passed 11/11 contract/workload
tests; the local baseline passed 4/4 with ASan/UBSan. Measurement sources, binary
hash, dependency revisions and the reused-build provenance are archived with
the full results.

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
   Only native concurrent adapters run with multiple workers; the other adapters
   run this mixed workload with one worker. This also applies to read-only mixes.
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

Frozen std/Abseil/TLX cursors hold a native const iterator: `Seek` calls `lower_bound`
once, and each `Next` increments the iterator without a key/value copy or another
lookup. Full traversal is linear. Cursors created before Freeze retain their safe
active-table behavior, which re-seeks on `Next` to tolerate iterator invalidation
from writes. Stage 1 scan and stage 3 flush always create cursors after Freeze.
RocksDB cursors use its native iterator in both modes and return views into arena
records. The research adapters also traverse their native structures after Freeze, as
detailed below. An index must outlive every cursor.

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
- **Masstree:** uses `basic_table` with owned immutable record pointers and a
  custom per-index allocation context. Retired suffix/node memory and overwritten
  records are deferred until Destroy, avoiding the upstream server's global RCU
  thread lists and allocator pools. Live cursors use native range-scan callbacks;
  frozen cursors traverse leaf permutations, sibling links and trie layers.
  The permutation patch handles the empty remainder of a
  full 64-bit permutation without shifting by 64. With `--internal-key`, maximum
  user key size is 1015 bytes.
- **HOT:** uses the upstream `HOTSingleThreaded` trie, C-string key extraction
  over terminated nibble keys, owned original keys/values and a reader/writer
  lock. The upstream process-wide node pool can retain memory after Destroy;
  run one HOT index at a time per process. Only single-thread benchmark workloads are permitted; **native HOTRowex
  concurrency is not integrated**. Frozen cursors use its native iterator. Upstream's 255-byte key
  buffer gives a 127-byte complete logical binary key limit, or a 118-byte user
  key with `--internal-key`. Clang patches fix restrict/alignment declarations,
  template definition ordering/specializations and replace an equivalent MMX
  byte-mask operation with SSE2. ISA flags apply only to the HOT source file.
  A separate patch fixes lower/upper bounds when the tree has one record.
  Native x86 contract/workload tests have passed on the Xeon server. A separate
  ROWEX adapter remains future work if native HOT concurrency is needed.
- **Wormhole:** uses native `whsafe_get`/`whsafe_merge`, with one parked reference
  per participating thread, owned by the index. The native merge callback under
  the leaf lock gives accurate size accounting for concurrent upserts. Active
  cursors copy a record and park after each movement so a retained cursor cannot
  deadlock a write in the same thread. Frozen cursors use native `whunsafe`
  iteration after admitted writes drain. The assembly patch uses newline-separated
  instructions and portable 16-byte alignment for the coroutine helper symbols
  in the pinned upstream code. The unaligned-load patch replaces typed CRC/common-prefix
  reads from byte buffers with memcpy, preserving arbitrary view alignment.
  Published experiments preserve their original source snapshots from before
  this sanitizer fix. Complete keys are capped at 65535 bytes; values must
  fit uint32. The default memory manager duplicates accepted key/value records.

None of these adapters constructs a separate sorted container for flush scans.
All four native concurrent research adapters include the admission/drain gate in
Insert/Freeze timing. Upsert adapters can retain old records to protect cursors;
append-only InternalKey workloads are the most representative common comparison.

## Verification

`adapter_contract` verifies empty/binary/prefix keys, misses, MVCC ordering, seek
across gaps and leaves, full scans, duplicate/upsert policy, concurrent readers,
writers, scans and Freeze, key limits, and active cursors retained across writes.
The BTreeOLC case forces a tree with multiple inner levels. CTest also exercises
all three workload stages for enabled adapters. If Python 3 is available,
`harness_integration` compares single-thread checksums and row counts against
`std_map`, then compares native concurrent adapters at four workers. It validates
55-column CSV metadata, controlled layouts and split phases, and checks rejection
of non-native multithreaded workloads before output creation. `benchmark_policy`
checks plans and completeness of the selected matrices. Unavailable
indexes are tested as unavailable; `MEMTABLE_BENCH_REQUIRE_HOT=1` makes missing HOT
CPU support a test failure, as used by the Linux x86 CI job.

For ASan/UBSan, use a separate Debug build and pass both compiler flags:

```sh
./scripts/build_all.sh build-sanitize -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  '-DCMAKE_C_FLAGS=-fsanitize=address,undefined -fno-omit-frame-pointer' \
  '-DCMAKE_CXX_FLAGS=-fsanitize=address,undefined -fno-omit-frame-pointer'
```

Set `UBSAN_OPTIONS=halt_on_error=1 ASAN_OPTIONS=halt_on_error=1` when running tests.
Sanitized builds are correctness checks and should not be used for rankings.

## Layout

```text
CMakeLists.txt                 Build options, targets, CTest
include/memtable_bench/key_dataset.h Controlled key configuration and corpus
src/key_dataset.cc             Unique synthetic keys, precomputation, exact LCP
scripts/sensitivity_matrix.py  20 screening/four representative profiles
scripts/summarize_sensitivity.py Completeness validation and sensitivity report
tests/key_dataset_contract.cc Key generation/ordering/LCP regression tests
include/memtable_bench/index.h Unified ordered-index interface and metadata
src/index.cc                   std/Abseil/TLX adapters, registry, InternalKey encoding
src/main.cc                    Exact-key diagnostic workloads and CSV v3
include/memtable_bench/measurement.h Shared Linux placement, RSS, PMU and latency
include/memtable_bench/mvcc.h   MVCC table, version cursor and visibility contracts
src/mvcc_main.cc               MVCC workloads and CSV mvcc-v1
src/mvcc.cc                    InternalKey MVCC wrappers and visible scans
src/cse_index.cc               CSE native version-chain C ABI adapter
src/oceanbase_index.cc          OceanBase KeyBtree core port with binary keys
vendor/oceanbase-port/          Runtime glue and pinned upstream source digests
scripts/vendor_oceanbase.py     Verified source subset and include isolation
docs/oceanbase.md               KeyBtree core scope and build instructions
rust/cse_memtable/             Pinned Rust bridge and source digests
scripts/mvcc_matrix.py          MVCC screening matrix and validation
scripts/summarize_mvcc.py       MVCC cohort validation and median/quartile report
scripts/plot_mvcc.py            Optional MVCC operation and SWMR figures
scripts/export_cse_memtable.py  Verified local CSE source export
docs/mvcc.md                    CSE scope, workload semantics, schema and examples
src/adapter_common.h           Write admission, immutable records, nibble codec
src/*_index.cc                 RocksDB and five research adapters
cmake/*.cmake                  Pinned downloads and embedded upstream builds
cmake/patches/                 Reproducible upstream fixes and platform patches
scripts/build_all.sh            Proxy-free all-adapter build/test entry point
tests/adapter_contract.cc       Binary/MVCC/cursor/concurrency/freeze contracts
tests/harness_integration.py    Workload checksum, CSV and rejection checks
.github/workflows/adapters.yml Native x86 GCC/Clang validation (requires HOT ISA)
THIRD_PARTY.md                  Pins, licenses and redistribution considerations
```
