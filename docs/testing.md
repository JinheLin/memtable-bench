# Verification results

## Fresh checks on 2026-10-08

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
  append-only/upsert policy, native key limits, concurrent readers and
  writers, Freeze/drain, and retained cursors. BTreeOLC exercises multiple inner
  tree levels.
- Smoke tests run all three workload stages for enabled adapters; append-only
  adapters reject unsupported exact-key upsert workloads.
- `harness_integration`: equivalent contents/checksums against `std_map`, CSV
  schema and parameter checks, controlled key layouts, split measurements,
  range limits and deterministic EOF truncation, and invalid inputs rejected
  before output creation.
- [Benchmark archives](../benchmarks/README.md) retain 1,170 formal processes and
  4,185 phase rows, with cross-adapter count/checksum validation.

ASan/UBSan checks detect memory and undefined-behavior errors in the tested
workloads; TSan cleanliness is not claimed. HOT cannot run on this ARM64 host.
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
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
  cmake -S . -B build-baseline-sanitize -DCMAKE_BUILD_TYPE=Debug \
  '-DCMAKE_CXX_FLAGS=-fsanitize=address,undefined -fno-omit-frame-pointer'
cmake --build build-baseline-sanitize -j 4
ASAN_OPTIONS=halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  ctest --test-dir build-baseline-sanitize --output-on-failure
```

The GitHub Actions workflow builds the all-adapter configuration with GCC and
Clang on Linux and requires HOT at runtime. Local checks above are separate from
GitHub Actions results.
