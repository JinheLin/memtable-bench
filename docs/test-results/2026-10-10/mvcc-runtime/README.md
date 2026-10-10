# MVCC runtime verification — 2026-10-10

These are functional and runtime checks on Linux x86-64, not a replacement
for the three-repeat million-key formal archive. All five retained candidates
were available. Processes ran serially on physical CPUs 2–9 / NUMA node 0;
the single-thread million-key run used CPU 2. The Xeon host remained shared.

| Run | Keys / ops | Scope | Processes / phase rows | Wall time |
| --- | --- | --- | --- | --- |
| Default quick | 100k / 100k | Latest uniform/Zipf; history v16; 8-worker SWMR; all stages; one repetition | 45 / 150 | 62.35 s |
| Focused million-key | 1M / 1M | Latest uniform Get/scan; stage 1; one repetition | 5 / 15 | 36.53 s |
| Completed quick resume | Same configuration and output | All 45 jobs reused; zero executed | 45 / 150 | 0.22 s |

Wall intervals come from each runner invocation, including process setup,
prefill, oracle validation, destruction and checkpoint overhead. Completed
resume timing excludes initial dependency/host discovery before the invocation.
These scopes differ from the 300-process formal matrix; the differences in
time are not a speedup measurement for an identical workload.

## Evidence

- [Build log](build.log), [15/15 CTest log](ctest.log).
- [Quick plan](quick-plan.json), [full plan](full-plan.json), [smoke plan](smoke-plan.json).
- [Quick metadata](quick-metadata.json), [quick validation](quick-validation.json),
  [quick report](quick-report.md), [progress](quick.log), [resume log](resume.log).
- [Million-key metadata](point-1m-metadata.json), [validation](point-1m-validation.json),
  [report](point-1m-report.md), [progress](point-1m.log).
- [Before/after fixture equivalence](fixture-equivalence.json) compares six cases,
  12 fresh processes, on the baseline. The preserved old binary is SHA-256
  `7ecb7d29c148a27b7ba1975f77f72daf5e7ecbbca8ab953b48f5bf508c24fbe5`;
  the new binary is `bce3aac78fc94dcbb91071c461937ec8f4e1d431dff5fcb941f800e38d343237`.
  The [probe script](compare_fixture.py) records its original results-directory
  execution context; both executables stay private. Small probe timings are
  not used for performance conclusions.
- [Earlier full-matrix validation](historical-validation.json) retains 300 / 840.
- [Verification summary](verification.json) and [published-file hashes](files-sha256.json).

The quick and million-key record tarballs include their combined `raw.csv`,
original process commands/CSVs/logs, and completion markers. Their manifests
hash all 181 and 21 packed files respectively. Private CSE source and linked
binaries are excluded. Public source fingerprints and dependency pins remain
in each metadata file. Fixture allocation changes can affect RSS baselines;
compare candidates within each cohort rather than pooling old and new runs.

To reconstruct the quick cohort in an ignored directory and revalidate:

```sh
mkdir -p results/runtime-quick
cp docs/test-results/2026-10-10/mvcc-runtime/quick-metadata.json \
  results/runtime-quick/metadata.json
tar -xzf docs/test-results/2026-10-10/mvcc-runtime/quick-records.tar.gz \
  -C results/runtime-quick
python3 scripts/summarize_mvcc.py results/runtime-quick --validate-only
```

The records can be validated after relocation. Resume is stricter: it requires
the original output/binary paths, source, dependencies, host and configuration.
