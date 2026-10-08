# Verification results

Current support is **native Linux x86-64 with GCC/Clang**. The build now rejects
other platforms. Earlier macOS/ARM entries below describe historical verification
and do not imply current platform support.

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
the formal performance experiment has not been rerun after this change.

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
- `harness_integration`: single-thread contents/checksums against `std_map`,
  multithreaded checksums within the native concurrent group, early rejection of
  non-native multithreaded requests (including read-only workloads), CSV
  schema and parameter checks, controlled key layouts, split measurements,
  range limits and deterministic EOF truncation, and invalid inputs rejected
  before output creation.
- [Benchmark archives](../benchmarks/README.md) retain 1,170 formal processes and
  4,185 phase rows, with cross-adapter count/checksum validation.

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
MEMTABLE_BENCH_REQUIRE_HOT=1 ./scripts/build_all.sh build-all -G Ninja
MEMTABLE_BENCH_REQUIRE_HOT=1 MEMTABLE_BENCH_TEST_NUMA_NODE=0 \
  MEMTABLE_BENCH_TEST_CPUS=2,3,4,5 \
  ctest --test-dir build-all --output-on-failure
```

Choose CPU IDs and the NUMA node from your own topology. For a dependency-free
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
Clang on Linux and requires HOT at runtime. Local checks above are separate from
GitHub Actions results.
