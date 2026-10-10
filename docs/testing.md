# Verification results

Current support is **native Linux x86-64 with GCC/Clang**. The current adapter
set has five candidates with InlineSkipList as its default baseline; see
[index selection](index-selection.md). Entries below preserve earlier measured
candidate sets and test counts. The build now rejects
other platforms. Earlier macOS/ARM entries below describe historical verification
and do not imply current platform support.

## Million-key OLTP/latest and history completion (2026-10-09)

The run completed at 19:59 Asia/Shanghai after about 5 h 10 min and was
archived on 2026-10-10. It reused the validated five-candidate Linux x86-64
binary, SHA-256 `7ecb7d29c148a27b7ba1975f77f72daf5e7ecbbca8ab953b48f5bf508c24fbe5`.
The source revision is `4c99d0f18af25918a4162e80617f127d251f28e8`.

- **300 fresh processes / 840 phase rows**, **150 / 420 per group**, three
  repetitions, 1/4/8 workers, all five retained candidates. Each profile has
  one million user keys and a one-million operation budget. Initial retained
  versions are 2M for OLTP, and 16M/64M for history. No exclusions or failures.
- **144** deterministic count/content comparison groups agree; **24** latest
  multiworker groups agree on deterministic request/write/dataset counts.
  **480** read/mixed/flush rows match independent oracle digests. The reported
  600 oracle-field rows also include 120 writer-only empty-read digests.
  All 60 latest
  SWMR runs observed newly published bounds, point hits on new versions and
  nonzero reader/writer overlap.
- Both cohorts have the same binary hash and the same 58 source digests.
  Raw rows match all 300 original process CSVs; packed commands/logs/CSVs
  match all **900** file hashes. The copied source and process archives were
  checked again locally. Private engine source and linked binaries are excluded.
- Cycles, instructions, L1/LLC and branch data are available in all **840**
  rows; DTLB data in **776**. Missing fields remain blank. CPU/NUMA placement
  is fixed, while frequency and background activity are uncontrolled.

See [protocol, tables and figures](../benchmarks/mvcc-groups-formal-1m-2026-10-09/README.md),
[matrix validation](../benchmarks/mvcc-groups-formal-1m-2026-10-09/summary/validation.json)
and [record verification](../benchmarks/mvcc-groups-formal-1m-2026-10-09/records-verification.json).
The preceding build/test evidence is recorded in the pilot section below.

## OLTP/latest and long-history groups (2026-10-09)

Linux x86-64 / Xeon Gold 6240 / GCC 11.3.1:

- Full five-candidate build: **15/15 CTest tests passed**;
  [build/test log](test-results/2026-10-09/mvcc-groups/group-build-tests.log).
  Fresh default-baseline reconfiguration: **11/11 passed**;
  [baseline log](test-results/2026-10-09/mvcc-groups/baseline-build-tests.log).
  Both latest and historical modes exercise empty values, tombstones,
  resurrection, before-first snapshots, scans, single-worker mixing and SWMR.
- The two-group pilot completed **100 fresh processes / 280 phase rows**:
  **50 / 140 per group**, 1,000 user keys, 4,000 operation budgets, one repeat,
  1/4/8 workers and all five candidates. OLTP has uniform/Zipf latest reads;
  history has 16/64 retained versions with first-round fixed snapshots.
  [Run log](test-results/2026-10-09/mvcc-groups/pilot.log),
  [metadata](test-results/2026-10-09/mvcc-groups/pilot-metadata.json) and
  [validation](test-results/2026-10-09/mvcc-groups/pilot-validation.json).
- **48** deterministic content comparison groups agree. **8** latest
  multiworker comparison groups agree on deterministic request/write/dataset
  counts; their visible results depend on scheduling. **200** read/mixed/flush
  rows match their independent oracle digests. All 20 latest multiworker runs
  observed newer publications, point hits on newly written versions and a
  nonzero common active interval. Snapshot traces are captured in memory for
  timed-run oracle replay; the CSV retains bounds/counts/digests rather than
  every request timestamp.
- The final group reporting/count refinements passed the dedicated runner/report
  integration test: **1/1**;
  [test log](test-results/2026-10-09/mvcc-groups/final-report-test.log).
  Invalid group/view, snapshot-range and oracle evidence is rejected.
  Summaries export separate `report-oltp.md` and `report-history.md` files.
  Four-profile plotting completed with Matplotlib/NumPy; latest and history
  figures were visually checked. These pilot timings do not establish rankings.
- The [source snapshot](test-results/2026-10-09/mvcc-groups/source-snapshot.tar.gz)
  matches all 58 measured public inputs. Two subsequent reporting/test edits
  have a separate [reporting snapshot](test-results/2026-10-09/mvcc-groups/reporting-source.tar.gz).
  [Raw records](test-results/2026-10-09/mvcc-groups/pilot-records.tar.gz),
  [derived pilot summaries](test-results/2026-10-09/mvcc-groups/pilot-summary.tar.gz)
  and [verification manifest](test-results/2026-10-09/mvcc-groups/verification.json)
  preserve commands, hashes, actual availability and new plan counts.
  Private engine source and linked binaries remain excluded.
- All 280 rows have cycles/instructions/L1/LLC/branch data; 205 have DTLB data.
  Unavailable fields remain blank. Original `mvcc-v1` formal archives still
  validate at **906 / 2,928**, and their contents and CSE pins are unchanged;
  [archive validation](test-results/2026-10-09/mvcc-groups/historical-validation.json).

The subsequent full run completed **150 processes / 420 rows per group**,
**300 / 840** together, as recorded above. The pilot logs here preserve the
earlier functional validation and are separate from performance evidence.
All builds cleared proxy variables and no formatting target was run.
See [group semantics, parameters and run commands](mvcc.md#two-workload-groups).

## Five-candidate pruning validation (2026-10-09)

Linux x86-64 / Xeon Gold 6240 / GCC 11.3.1 / Rust 1.92.0:

- All five retained candidates: **14/14 CTest tests passed**;
  [final build/test log](test-results/2026-10-09/core-indexes/final-build-tests.log).
  Both executable defaults are InlineSkipList. Integration tests reject all
  seven retired names before creating CSV files, and exercise visibility,
  tombstones, concurrent readers/writer, ordered scans and lifecycle checks.
- Fresh default build with only InlineSkipList available: **10/10 passed**;
  [baseline build/test log](test-results/2026-10-09/core-indexes/baseline-build-tests.log).
- The compact MVCC pilot completed **100 fresh processes / 320 phase rows**:
  1,000 user keys, 2,000 operation budgets, four profiles, one repetition and
  1/4/8 workers. All **64** content/count comparison groups agree. This is
  functional validation; its timings do not establish a performance ranking.
  See [run log](test-results/2026-10-09/core-indexes/pilot.log),
  [metadata](test-results/2026-10-09/core-indexes/pilot-metadata.json) and
  [independent validation](test-results/2026-10-09/core-indexes/pilot-validation.json).
- All 56 measured public source/build/test inputs match the current files.
  The [source snapshot](test-results/2026-10-09/core-indexes/source-snapshot.tar.gz)
  preserves those inputs; private CSE engine sources and linked binaries are
  excluded. Its native source pins are unchanged.
  [Pilot records](test-results/2026-10-09/core-indexes/pilot-records.tar.gz)
  contain the raw CSV and every process's command/result/log.
  [Verification manifest](test-results/2026-10-09/core-indexes/verification.json)
  records binary/artifact hashes, availability and plan counts.
- Cycles, instructions, L1/LLC and branch fields are present in all 320 rows;
  DTLB fields in 238. Missing events remain empty.
- The pruning change's then-current million-key plan had **300 processes / 960 phase rows**, but was
  not run in this change. The previous 906-process archive still validates,
  and its recorded file hashes are unchanged.

Builds cleared all HTTP/HTTPS/ALL proxy variables. No formatting target was run.
See [selection reasons and CSE default evidence](index-selection.md).

## Historical formal MVCC matrix completion

Completed on Linux x86-64 / GCC 11.3.1 on 2026-10-09:

- **906 processes / 2,928 phase rows** across six cohorts, with three fresh-process
  repetitions each. Completeness, native concurrency participation and all
  **288** count/content comparison groups passed independent archive validation.
- All cohorts used the same binary SHA-256 and the same 69 source/build/test
  inputs. The final remote integrity check verified all 75 files in the measured
  public source snapshot, including its documentation, plus the binary hash.
- **17/17 CTest tests passed** after performance runs finished; see
  [test log](../benchmarks/mvcc-formal-1m-2026-10-08/ctest.log).
- CSE Arena's million-key deep prefill exhausted its native block index; the
  million-key 1 KiB value case is rejected by its allocation guard. The archive
  preserves exclusions and failure evidence. All twelve candidates completed
  separate matched deep-500k/value-100k cohorts without changing native sources.
- Cycles, instructions, L1/LLC and branch fields are available in all 2,928 rows;
  DTLB fields in 2,709. Empty PMU fields remain empty.

See [protocol, findings and evidence](../benchmarks/mvcc-formal-1m-2026-10-08/README.md)
and [validation](../benchmarks/mvcc-formal-1m-2026-10-08/summary/validation.json).
The reporting scripts were added after measurement; their separate source
snapshot does not replace the measured c306312 source snapshot.

## OceanBase KeyBtree core integration

Linux x86-64 / GCC 11.3.1, on 2026-10-08:

- All twelve runnable MVCC candidates, including the new `oceanbase_keybtree`:
  **17/17 CTest tests passed**. The [test and pilot log](test-results/2026-10-08/oceanbase/all-candidates-pilot.log)
  records this run and all 176 pilot processes.
- Standalone std::map + OceanBase core build: **10/10 passed**;
  [build/test log](test-results/2026-10-08/oceanbase/standalone-build-tests.log).
- Dependency-free baseline: **8/8 passed**;
  [baseline and integrity log](test-results/2026-10-08/oceanbase/baseline-integrity-tests.log).
- Four-worker MVCC operations and lifecycle under Valgrind 3.19:
  **zero memory errors, zero bytes retained at process exit**;
  [memory-check log](test-results/2026-10-08/oceanbase/valgrind.log).
- Original or generated source tampering is rejected by the verifier;
  evidence is in the baseline/integrity log. Captured logs and pilot source
  snapshots preserve the measured revision, which included two subsequently
  removed placeholder candidates.

The [functional pilot](../benchmarks/oceanbase-core-pilot-2026-10-08/README.md)
completed **176 processes / 576 rows**, across four profiles and 1/4 workers.
All 52 comparison groups match counts and contents; all rows have PMU cycles.
Measured source and binary hashes were verified when archiving. This does not
establish a performance ranking or measure native OceanBase transaction MVCC.

The host lacks the GCC compiler's required `libasan.so.6.0.0`, so the ASan
configuration did not compile and no ASan success is claimed;
[compiler diagnostic](test-results/2026-10-08/oceanbase/asan-unavailable.log).
The memory check used the available Valgrind runtime. All builds cleared proxy
variables and no formatting target was run. See [KeyBtree scope](oceanbase.md).

## Prior Linux platform validation

The final platform cleanup was rebuilt and verified on the Linux host; the
[Linux-only validation log](test-results/2026-10-08/mvcc/linux-only-validation.log)
includes the 15/15 test run and a fresh all-eleven, 1/4-worker MVCC runner check.
The runner completed 40 processes / 131 phase rows, with matching counts and
contents; [metadata](test-results/2026-10-08/mvcc/linux-only-metadata.json) records
the tested binary and source hashes.
Raw results and per-process commands/logs are in
`test-results/2026-10-08/mvcc/linux-only-records.tar.gz`.

The concurrent MVCC contract exposed an intermittent UnoDB cursor failure:
OLC restart probes referenced the iterator's mutable key buffer. An explicit
patch retains an owned probe and fixes keyless-leaf seek comparison direction.
The strengthened contract starts readers and the writer together;
[100 consecutive runs passed](test-results/2026-10-08/mvcc/cursor-regression-fixed.log).
The new single-record, binary-prefix lower-bound test also exposed HOT's
reversed comparison and inclusive upper bound; its explicit patch passed the
complete adapter contract. All nine adapters exercise this boundary while live
and frozen. See [the original failure](test-results/2026-10-08/mvcc/cursor-regression-before-fix.log).

## CSE and MVCC workload integration

Linux x86-64 / GCC 11.3.1 / Rust stable 1.92.0, on 2026-10-08:
**15/15 CTest tests passed**, including all eleven MVCC implementations and HOT.
See [final test log](test-results/2026-10-08/mvcc/linux-only-validation.log).
The CSE contract also tests native snapshot reads, empty live values, tombstones,
resurrection, concurrent readers, retained history, permanent Freeze and complete
version flush. A 16 MiB payload exercises Crossbeam's separate-value backing;
Arena rejects it before insertion. The final contract run passed for all eleven
implementations. All compilation cleared proxy variables.

The [MVCC functional pilot](../benchmarks/mvcc-pilot-2026-10-08/README.md)
completed **160 independent processes / 524 phase rows**: 10,000 present user keys,
10,000 operation budgets, one repeat, four profiles, 1/4 workers. All eleven
implementations ran single-thread phases; the seven native concurrent candidates
ran SWMR. Every comparison's counts, contents and checksums matched. All 524
phase rows have PMU cycle data; this is a functional pilot, not a stable ranking.
Source snapshots and build inputs preserve the version actually measured.

The dependency-free default build was verified on Linux at **8/8 tests**;
see [Linux baseline log](test-results/2026-10-08/mvcc/linux-baseline-tests.log).
CSE correctness and benchmark qualification for this change are based on Linux.

See [MVCC semantics and schema](mvcc.md) for the scope of native CSE source reuse,
FFI costs, snapshot model, batch operation units and memory accounting.

## Native concurrency policy validation

Fresh checks after the participation change, on 2026-10-08:

| Environment | Result | Evidence |
| --- | --- | --- |
| Linux x86-64, GCC 11.3.1, all nine adapters; HOT required; CPUs 2/3/4/5, NUMA node 0 | **12/12 passed** | [CTest](test-results/2026-10-08/native-concurrency-policy/linux-ctest.log) |
| macOS ARM64/M4, dependency-free Debug ASan/UBSan | **5/5 passed** | [CTest](test-results/2026-10-08/native-concurrency-policy/local-baseline-ctest.log) |
| macOS ARM64/M4, std::map + BTreeOLC/UnoDB/Masstree/Wormhole Debug ASan/UBSan | **10/10 passed** | [CTest](test-results/2026-10-08/native-concurrency-policy/local-research-ctest.log) |

The policy test validates advertised capabilities and both matrix plans,
including subsets with no concurrent candidates and thread lists omitting 1.
It checks historical selection and rejection of missing, duplicate, or
ineligible rows. Harness tests run all adapters at one worker, native concurrent
adapters at four workers, and reject non-native adapters with multiple workers
before writing CSV or dataset files. Concurrent contract tests run only for the
five native concurrent implementations. Proxy variables were unset for builds.

Fresh runner pilots on the same Xeon server use 2,500 keys, 5,000 operations,
one repeat, pinned physical cores and NUMA memory binding:

| Pilot | Counted processes | Phase rows | Warmup processes | Participants |
| --- | --- | --- | --- | --- |
| Standard matrix, 1/2/4 workers | **46** | **109** | 9 | Nine single-thread indexes, five native concurrent indexes |
| Representative `random` profile, 1/4 workers + lifecycle | **23** | **59** | 9 | Nine single-thread indexes, five native concurrent indexes |

All planned processes completed; contents/counts/checksums agree within every
eligible comparison. No wrapper multithreaded process was scheduled. These
pilots verify execution and reporting and are not used for performance rankings.
The [runner log](test-results/2026-10-08/native-concurrency-policy/linux-matrix-pilots.log),
[counts and binary hashes](test-results/2026-10-08/native-concurrency-policy/runner-checks.json),
captured raw CSV/metadata/commands and measurement source manifest accompany
the tests. The [current comparison view](../benchmarks/native-concurrency-2026-10-08/README.md)
uses existing million-record measurements with wrapper concurrency excluded;
this legacy exact-key experiment has not been rerun after this change. The
completed formal MVCC matrix above applies the current concurrency policy.

## Verification before the concurrency policy update (2026-10-08)

| Environment | Configuration | Result | Evidence |
| --- | --- | --- | --- |
| Linux x86-64, Xeon Gold 6240, GCC 11.3.1 | Release, all nine adapters; HOT required; harness threads pinned to CPUs 2/3/4/5 and NUMA node 0 | **11/11 passed** | [CTest log](test-results/2026-10-08/linux-native-ctest.log) |
| macOS ARM64/M4, AppleClang | Debug baseline with ASan and UBSan | **4/4 passed** | [CTest log](test-results/2026-10-08/local-baseline-asan-ubsan.log) |
| macOS ARM64/M4, AppleClang | Debug std::map + BTreeOLC/UnoDB/Masstree/Wormhole with ASan and UBSan | **9/9 passed** | [CTest log](test-results/2026-10-08/local-research-asan-ubsan.log) |

The builds were checked against the current sources before testing. Current
source digests, the patched Wormhole source and binary hashes are recorded in
[verification.json](test-results/2026-10-08/verification.json).
Proxy environment variables were unset during builds.

## Coverage

- `key_dataset_contract`: unique binary keys, balanced prefix groups, exact LCP
  histograms, stable access permutations and descending MVCC sequence ordering.
- `adapter_contract`: empty/prefix/binary keys, misses, lower bounds, ordered
  traversal, byte views at all eight alignments, CRC tail lengths,
  append-only/upsert policy, native key limits and retained cursors. Concurrent
  readers/writers and Freeze/drain races run only for native concurrent adapters. BTreeOLC exercises multiple inner
  tree levels.
- Smoke tests run all three workload stages for enabled adapters; append-only
  adapters reject unsupported exact-key upsert workloads.
- `benchmark_policy`: runner participation/counts, advertised native capability,
  historical/new matrix completeness, and missing/duplicate/ineligible row rejection.
- `harness_integration`: single-thread contents/checksums against InlineSkipList,
  multithreaded checksums within the native concurrent group, early rejection of
  non-native multithreaded requests (including read-only workloads), CSV
  schema and parameter checks, controlled key layouts, split measurements,
  range limits and deterministic EOF truncation, and invalid inputs rejected
  before output creation.
- [Earlier exact-key benchmark archives](../benchmarks/README.md) retain 1,170
  formal processes and 4,185 phase rows, with cross-adapter count/checksum
  validation. The formal MVCC archive above is separate.

ASan/UBSan checks detect memory and undefined-behavior errors in the tested
workloads; TSan cleanliness is not claimed. Historical ARM64 runs excluded HOT.
Older pilot test logs stay with their measured experiments and are distinct from
these fresh checks.

## Wormhole alignment regression

The new controlled dataset passes views into a contiguous buffer with a 73-byte
stride. The strict ARM64 sanitizer run exposed typed 16/32/64-bit reads from
unaligned byte buffers in upstream Wormhole's CRC helper. The same pattern also
appeared in its common-prefix helper. The explicit
[patch](../cmake/patches/wormhole-unaligned.patch) replaces these reads with
fixed-size memcpy loads, preserving byte order and hash behavior.

The [initial failing log](test-results/2026-10-08/local-research-asan-ubsan-before-fix.log)
is retained alongside the passing rerun. `VerifyUnalignedInputs` checks Insert,
Contains, Get, Seek and frozen traversal across alignments and word-tail lengths.
Published performance archives precede this patch; the current Linux binary
has a different hash. Formal performance measurements have not been rerun after
the fix, and the archives retain their original measurement snapshots.

## Reproduce

Linux with the required x86 ISA:

```sh
./scripts/build_all.sh build-core -G Ninja
MEMTABLE_BENCH_TEST_NUMA_NODE=0 \
  MEMTABLE_BENCH_TEST_CPUS=2,3,4,5 \
  ctest --test-dir build-core --output-on-failure
```

Choose CPU IDs and the NUMA node from your own topology. For a RocksDB
sanitized baseline:

```sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cmake -S . -B build-baseline-sanitize -DCMAKE_BUILD_TYPE=Debug \
  '-DCMAKE_CXX_FLAGS=-fsanitize=address,undefined -fno-omit-frame-pointer'
cmake --build build-baseline-sanitize -j 4
ASAN_OPTIONS=halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  ctest --test-dir build-baseline-sanitize --output-on-failure
```

The GitHub Actions workflow builds the all-adapter configuration with GCC and
Clang on Linux for the four retained C++ adapters. Local checks above are separate from
GitHub Actions results.
