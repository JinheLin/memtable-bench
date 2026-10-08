# Benchmark comparisons by native concurrency

## Participation

| Integrated implementation | One worker | Multiple workers |
| --- | --- | --- |
| std::map | Yes | Excluded |
| Abseil B-tree | Yes | Excluded |
| TLX B+Tree | Yes | Excluded |
| HOTSingleThreaded | Yes | Excluded; HOT ROWEX is not integrated |
| RocksDB InlineSkipList | Yes | Yes; append-only concurrent insert |
| BTreeOLC | Yes | Yes; native OLC with adapter key stripes |
| UnoDB ART | Yes | Yes; olc_db + QSBR, append-only |
| Masstree | Yes | Yes; native synchronization + deferred reclamation |
| Wormhole | Yes | Yes; whsafe thread references |

Eligibility follows the implementation actually integrated. The compatibility
reader/writer locks on the four single-thread adapters remain included in their
single-thread timings. Even read-only multithreaded workloads are excluded for
this group. All indexes receive the same logical dataset within each comparison.

## Reorganized measurements

| View | Original processes / phase rows | Included | Excluded wrapper concurrency |
| --- | --- | --- | --- |
| [Million-record comparison](original/report.md) | 360 / 675 | **280 / 595** | 80 / 80 |
| [Representative pilot](representative-pilot/report.md) | 144 / 288 | **112 / 256** | 32 / 32 |

The [comparison figure](original/comparison.png) has nine indexes in its
single-thread, memory and lifecycle panels, and five in its scaling panel.
Representative pilot timings are functional checks and are not used for formal
performance rankings.

These views select existing measurements; **no formal benchmark was rerun**.
The original raw CSV, reports, source snapshots and per-process archives are
unchanged. Each view contains:

- `summary.csv`: statistics for eligible measurements only.
- `excluded.csv`: the original wrapper multithreaded phase rows, kept separately.
- `selection.json`: source directory, original raw CSV SHA256, selection policy
  and included/excluded process counts.
- `report.md`: nine-index single-thread tables and five-index concurrency tables.

Source archives: [original comparison](../xeon79-2026-10-08/report.md) and
[representative pilot](../representative-pilot-2026-10-08/report.md).
Both precede the Wormhole unaligned-load fix; no post-fix performance conclusion
is inferred from these data. The single-thread key/value screening and million-
record range-scan archives already satisfy this policy and remain unchanged.

## Reproduce the views

From the repository root:

```sh
python3 scripts/summarize_benchmark.py benchmarks/xeon79-2026-10-08 \
  --output benchmarks/native-concurrency-2026-10-08/original
python3 scripts/summarize_sensitivity.py benchmarks/representative-pilot-2026-10-08 \
  --output benchmarks/native-concurrency-2026-10-08/representative-pilot
python3 scripts/plot_benchmark.py benchmarks/native-concurrency-2026-10-08/original
```

Plotting requires Matplotlib and NumPy. The summarizers validate completeness and
checksums for the entire historical matrix before selecting eligible rows.
For new matrices, metadata records `concurrency_policy=native-concurrency-v1`
and the participant list for every scenario. Missing, duplicate or ineligible
rows fail validation rather than appearing as unavailable performance numbers.

## Future runs

```sh
python3 scripts/benchmark_matrix.py --list-plan
python3 scripts/sensitivity_matrix.py --suite representative --list-plan
```

Defaults schedule **280** formal processes for the original matrix and **336**
for the representative suite. Both retain `mixed_t1` for all nine indexes even
when `--threads` omits 1. The screening and range-scan suites remain entirely
single-threaded (540 and 270 formal processes at defaults).

The binary advertises `native_concurrent=0/1` via `--list-indexes`; runners check
it against their policy before execution. Ineligible `--threads > 1` requests
are rejected before CSV or dataset files are created. See
[verification evidence](../../docs/testing.md#native-concurrency-policy-validation)
for the tests and fresh small-scale runner checks.
