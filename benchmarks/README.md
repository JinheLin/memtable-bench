# Published benchmark results

These are completed runs on a shared dual-socket Intel Xeon Gold 6240 server
(36 physical cores, 72 logical CPUs, approximately 376 GiB RAM). Processes run
serially with CPU affinity and NUMA binding. Frequency is not locked and CPUs
are not reserved. Dependency revisions, compiler options, binary hashes and
measurement source snapshots are recorded separately for each experiment.

## Current code and historical measurements

The current benchmark retains RocksDB InlineSkipList (default baseline),
BTreeOLC, UnoDB ART, Wormhole and CSE Crossbeam. [Index selection](../docs/index-selection.md)
records why seven adapters were removed. The archives below preserve the
candidate sets, source snapshots and original statistics actually measured;
retired names remain valid for historical reporting only.
The current `mvcc-v2` workload has separate OLTP/latest and long-history groups.
The [completed million-user-key experiment](mvcc-groups-formal-1m-2026-10-09/README.md)
has **300 processes / 840 phase rows**, all five candidates, three repetitions
and 1/4/8 workers. Its [OLTP](mvcc-groups-formal-1m-2026-10-09/summary/report-oltp.md)
and [history](mvcc-groups-formal-1m-2026-10-09/summary/report-history.md) reports
keep the groups separate. See [the protocol](../docs/mvcc.md#two-workload-groups)
and [verification notes](../docs/testing.md).
The formal `mvcc-v1` archive below retains its original read protocol.

## Historical comparison policy

For snapshot-visible database workloads, use the
[completed MVCC matrix](mvcc-formal-1m-2026-10-08/README.md): **906 processes /
2,928 phase rows**, six cohorts and three repetitions. It includes twelve
candidates, with eight native concurrent implementations eligible for SWMR;
CSE Arena's two capacity exclusions have separate matched smaller cohorts.
The [tables](mvcc-formal-1m-2026-10-08/summary/report.md) keep populations separate.

Use the [native-concurrency comparison view](native-concurrency-2026-10-08/README.md)
for legacy exact-key tables and scaling curves. All nine indexes participate
at one worker;
RocksDB InlineSkipList, BTreeOLC, UnoDB ART, Masstree and Wormhole participate
above one worker. std::map, Abseil, TLX and the integrated HOTSingleThreaded
implementation are excluded from multithreaded comparisons.

That view retains **280 of 360 processes / 595 of 675 phase rows** from the
original formal matrix, and **112 of 144 processes / 256 of 288 phase rows**
from the representative pilot. `excluded.csv` preserves historical wrapper
multithreaded rows; `selection.json` identifies each original raw CSV by SHA256.
No performance measurements were rerun to create these views. The archives
below keep the historical protocol and original data unchanged.

## Formal experiment archives

| Experiment | Stored records | Repeats | Processes | Phase rows | Scope |
| --- | --- | --- | --- | --- | --- |
| [OLTP/latest and long history](mvcc-groups-formal-1m-2026-10-09/README.md) | 1M user keys; 2M/16M/64M retained versions | 3 | 300 | 840 | Five retained candidates; uniform/Zipf latest reads; v16/v64 oldest reads; 1/4/8 workers; scans and full lifecycle |
| [Original comparison](xeon79-2026-10-08/report.md) | 1,000,000 | 5 | 360 | 675 | Single-thread uniform/Zipf, 1/2/4/8/16-thread mixed workload, MemTable lifecycle |
| [Key/prefix/value screening](sensitivity-screening-2026-10-08/report.md) | 1,000,000 | 3 | 540 | 2,700 | 20 configurations, LookupOnly/GetCopy, cursor/payload scans, memory and PMU counters |
| [Range scan lengths](range-scan-1m-2026-10-08/report.md) | 1,000,000 | 3 | 270 | 810 | Random keys and 56 B common prefix; limits 1/10/100/1,000/10,000; SeekOnly, cursor and payload scans |
| [MVCC operations and lifecycle](mvcc-formal-1m-2026-10-08/README.md) | 1M user keys (4/16 versions); matched 500k/100k supplements | 3 | 906 | 2,928 | Base/deep/prefix/value; latest/historical Get and scans; 1/4/8-worker mixed/SWMR; all-version flush and Destroy |

The three legacy exact-key experiments cover nine adapters. There are **1,170 legacy exact-key formal
processes and 4,185 phase rows**. Counts and checksums agree across adapters within each comparison.
Three-repeat medians and quartiles are screening statistics, not confidence
intervals. The range suite has only 16 latency samples per phase/repeat; its
sampled p99 is not a stable tail estimate.

The original comparison uses 24 B user keys and inline generation of legacy
ID-based keys. The later experiments use precomputed random/prefix keys,
different key sizes and measurement/validation order. Compare indexes within
each experiment; throughput values across these experiment rounds are not
directly comparable.

The three legacy archives also precede the Wormhole unaligned-load sanitizer
fix in the current source. These exact-key suites have not been rerun after
that patch. The new MVCC matrix includes the fix and uses a different workload.
Their source snapshots and binary hashes identify the versions actually
measured; see [verification notes](../docs/testing.md#wormhole-alignment-regression).

## Functional pilots

The [OceanBase KeyBtree integration pilot](oceanbase-core-pilot-2026-10-08/README.md)
adds the runnable core port: twelve candidates, 176 processes / 576 phase rows,
four profiles and 1/4 workers. All counts, contents and retained-version checks
match. It measures the common InternalKey MVCC wrapper on KeyBtree, not full
native OceanBase transaction MemTable operation paths.

The [MVCC/CSE pilot](mvcc-pilot-2026-10-08/README.md) uses the new `mvcc-v1`
model: eleven implementations, 10,000 present user keys with 4/16 versions,
four profiles, one repeat, 160 processes and 524 phase rows. Seven native
concurrent implementations run SWMR. Its contents and version counts agree
across candidates. Its times are not comparable to the legacy exact-key suites.

| Pilot | Stored records | Repeats | Processes | Phase rows | Purpose |
| --- | --- | --- | --- | --- | --- |
| [Range scan pilot](range-scan-pilot-2026-10-08/report.md) | 10,000 | 1 | 90 | 270 | Validate scan lengths, row counts and checksums |
| [Representative workload pilot](representative-pilot-2026-10-08/report.md) | 10,000 | 1 | 144 | 288 | Validate four profiles at 1/4/16 threads and lifecycle |

Pilot timings are not used for formal performance rankings. The legacy
exact-key million-record representative-profile concurrency/lifecycle experiment
is still pending. Both formal MVCC experiments above are complete.

## Archive layout and verification

Each directory contains the unchanged measured `raw.csv`, `summary.csv`,
`metadata.json`, reports, commands and available source/build/test provenance.
`archive.json` records the export and checksum checks. Per-process CSV, logs and
dataset metadata are packed in `runs.tar.gz`, preserving file contents and names.
Extract it inside that experiment directory to restore `runs/`:

```sh
cd benchmarks/range-scan-1m-2026-10-08
tar -xzf runs.tar.gz
```

For the range suite, `result-files-sha256.json` is the original result manifest.
Extract `runs.tar.gz` before checking all its entries. `source.tar.gz` (or
`benchmark-source.tar.gz` in the original comparison) is the measured source
snapshot, which can differ from the current repository's documentation and
reporting scripts. Recorded absolute build paths describe the original machine;
adapt them when rebuilding on another host.

Run reporting scripts in a scratch copy to preserve the published reports:

```sh
mkdir -p results
cp -R benchmarks/range-scan-1m-2026-10-08 results/range-review
tar -xzf results/range-review/runs.tar.gz -C results/range-review
python3 scripts/summarize_sensitivity.py results/range-review
python3 scripts/diagnose_range_scan.py results/range-review
python3 scripts/plot_range_scan.py results/range-review
```

The plot needs Matplotlib and NumPy; validation and CSV summaries use the Python
standard library. Captured generator scripts preserve older postprocessing
versions. New measurements belong in the ignored `results/` directory.

## Legacy exact-key measurement boundaries

- Reads use exact encoded keys; snapshot-visible filtering is not implemented.
- Range scans use frozen indexes and uniform existing-key start points. The row
  limit can truncate at EOF; throughput uses actual returned rows.
- Cursor and payload scans include cursor creation and Seek. Payload scans hash
  every key/value byte; they do not encode SSTables or perform disk I/O.
- ART/HOT include the adapter's terminated nibble encoding. HOT uses
  HOTSingleThreaded with a coarse reader/writer lock, not HOT ROWEX.
- RSS deltas, allocator retention and input-buffer boundaries are described in
  each report. PMU costs include harness and adapter work; unavailable fields are
  empty rather than zero-filled.

See [current code verification](../docs/testing.md) for the fresh test evidence.
