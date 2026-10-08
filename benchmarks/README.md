# Published benchmark results

These are completed runs on a shared dual-socket Intel Xeon Gold 6240 server
(36 physical cores, 72 logical CPUs, approximately 376 GiB RAM). Processes run
serially with CPU affinity and NUMA binding. Frequency is not locked and CPUs
are not reserved. Dependency revisions, compiler options, binary hashes and
measurement source snapshots are recorded separately for each experiment.

## Formal experiments

| Experiment | Stored records | Repeats | Processes | Phase rows | Scope |
| --- | --- | --- | --- | --- | --- |
| [Original comparison](xeon79-2026-10-08/report.md) | 1,000,000 | 5 | 360 | 675 | Single-thread uniform/Zipf, 1/2/4/8/16-thread mixed workload, MemTable lifecycle |
| [Key/prefix/value screening](sensitivity-screening-2026-10-08/report.md) | 1,000,000 | 3 | 540 | 2,700 | 20 configurations, LookupOnly/GetCopy, cursor/payload scans, memory and PMU counters |
| [Range scan lengths](range-scan-1m-2026-10-08/report.md) | 1,000,000 | 3 | 270 | 810 | Random keys and 56 B common prefix; limits 1/10/100/1,000/10,000; SeekOnly, cursor and payload scans |

All three cover nine adapters. There are **1,170 formal processes and 4,185 phase
rows**. Counts and checksums agree across adapters within each comparison.
Three-repeat medians and quartiles are screening statistics, not confidence
intervals. The range suite has only 16 latency samples per phase/repeat; its
sampled p99 is not a stable tail estimate.

The original comparison uses 24 B user keys and inline generation of legacy
ID-based keys. The later experiments use precomputed random/prefix keys,
different key sizes and measurement/validation order. Compare indexes within
each experiment; throughput values across these experiment rounds are not
directly comparable.

The archives also precede the Wormhole unaligned-load sanitizer fix in the
current source. Formal performance measurements have not been rerun after that
patch. Their source snapshots and binary hashes identify the versions actually
measured; see [verification notes](../docs/testing.md#wormhole-alignment-regression).

## Functional pilots

| Pilot | Stored records | Repeats | Processes | Phase rows | Purpose |
| --- | --- | --- | --- | --- | --- |
| [Range scan pilot](range-scan-pilot-2026-10-08/report.md) | 10,000 | 1 | 90 | 270 | Validate scan lengths, row counts and checksums |
| [Representative workload pilot](representative-pilot-2026-10-08/report.md) | 10,000 | 1 | 144 | 288 | Validate four profiles at 1/4/16 threads and lifecycle |

Pilot timings are not used for formal performance rankings. The million-record
representative-profile concurrency/lifecycle experiment is still pending.

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

## Measurement boundaries

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
