# Million-user-key MVCC groups — 2026-10-09

Completed **300 fresh processes / 840 phase rows**, with three repetitions,
for all five retained candidates: RocksDB InlineSkipList, BTreeOLC, UnoDB ART,
Wormhole and CSE Crossbeam. Both groups use one million present user keys,
an additional disjoint population of one million absent keys, and a one-million
operation budget. No candidate or configuration was excluded.

Linux x86-64 / GCC 11.3.1 / Rust 1.92.0, shared dual-socket Intel Xeon Gold 6240.
Processes ran serially on physical CPUs 2–9 and NUMA node 0. CPUs were not
reserved and frequency was not locked. Start/end time and resource snapshots
are preserved in [status.json](status.json) and `resources-{before,after}.json`.
The run started **2026-10-09 14:48:42** and finished **2026-10-09 19:59:04**
(Asia/Shanghai), about **5 h 10 min**. Results were archived on 2026-10-10.

## Two groups

| Group / profile | User keys | Initial versions/key | Initial stored versions | Read view | Processes / rows |
| --- | --- | --- | --- | --- | --- |
| OLTP / uniform | 1,000,000 | 2 | 2,000,000 | Latest completed batch at request start | 75 / 210 |
| OLTP / Zipf theta 1.1 | 1,000,000 | 2 | 2,000,000 | Latest completed batch at request start | 75 / 210 |
| History / v16 | 1,000,000 | 16 | 16,000,000 | Fixed first-round snapshot 1,000,000 | 75 / 210 |
| History / v64 | 1,000,000 | 64 | 64,000,000 | Fixed first-round snapshot 1,000,000 | 75 / 210 |

Key/value sizes are 16/32 bytes; batch size 32. Workload seeds are 42/43/44.
Keys and insertion order are random; Zipf hot ranks are spread across keys.
Later version rounds and timed updates generate 10% tombstones. Point reads
have 10% absent probes. OLTP starts with short chains but retains every update,
including hot-key chains; no garbage collection runs.

Stage 1 loads data, performs one million point reads and 1,024 dedicated
visible scans of up to 100 live rows. Stage 2 uses 80% reads in the budget of
read requests plus written versions: 800,000 point reads and 200,000 written
versions submitted in 6,250 batches, or 806,250 interface requests. There are
no scans in the mixed phase. One worker interleaves reads/writes; 4/8 workers
use one writer and 3/7 readers. All five candidates have native concurrency.
Stage 3 separately loads, freezes, hashes all retained versions/tombstones in
order and destroys the table. There is no WAL, SST encoding or disk I/O.

## Results

Single-thread point Get medians, in **million requests/s**. The final column
is RSS growth after input preparation and load for the 64-version profile.

| Index | Latest uniform | Latest Zipf | History v16 | History v64 | v64 RSS growth GiB |
| --- | --- | --- | --- | --- | --- |
| RocksDB InlineSkipList | 0.452 | 0.744 | 0.287 | 0.201 | 4.648 |
| BTreeOLC | 0.464 | 0.777 | 0.314 | 0.234 | 12.576 |
| UnoDB ART | 0.609 | 0.967 | 0.574 | 0.484 | 8.661 |
| Wormhole | 0.587 | 0.750 | 0.326 | 0.128 | 6.345 |
| CSE Crossbeam | 0.395 | 0.662 | 0.196 | 0.070 | 9.471 |

- UnoDB has the highest single-thread point-read throughput in all four
  profiles. Its RSS growth is larger than InlineSkipList's.
- InlineSkipList has the lowest after-load RSS growth in every profile and
  the highest latest-visible scan throughput. At v64, historical scans are
  about 0.065 Mlive rows/s for both InlineSkipList and CSE Crossbeam.
- Eight-worker uniform OLTP group throughput is about 2.9 Mrequests/s for
  both Wormhole and UnoDB, versus 2.091 for InlineSkipList. With Zipf access,
  UnoDB reaches 4.200 versus InlineSkipList's 3.260.
- CSE's oldest-version single-thread Get falls from 0.196 at v16 to 0.070 at
  v64. At v64/eight workers its writer service is 0.351 Mversions/s versus
  InlineSkipList's 0.248, while group throughput is 0.479 versus 0.999
  Mrequests/s. Writer service and complete-group results describe different
  parts of the workload.

- [OLTP/latest tables](summary/report-oltp.md)
- [Long-chain/history tables](summary/report-history.md)
- [Combined report](summary/report.md)
- [Metric medians, quartiles and samples](summary/summary.csv)
- [Completeness, comparison and PMU evidence](summary/validation.json)

The plots in `summary/` include operation, memory and SWMR panels for each
profile. Compare medians within each profile. Latest concurrent readers can
observe different published versions with different scheduling, so their
visible hit counts/checksums need not agree across candidates. Each such run
is verified independently using its captured snapshot trace; deterministic
request/write/dataset counts agree across adapters. Historical reads use the
same fixed snapshot and retain full cross-adapter content comparisons.

RSS growth is sampled after input preparation and includes allocator/runtime
retention. Bytes/version normalizes that growth by retained versions; it does
not measure live-user-key memory after compaction. Native CSE metadata,
ownership, FFI and version-chain traversal are timed, as are codec/cursor/value
copy costs in the other adapters. A native CSE chain and ordered InternalKeys
represent the same visible MVCC dataset with different physical layouts.

Three-repeat quartiles describe observed variation, not confidence intervals.
Dedicated scans have about 16 latency samples/repeat, so sampled p99 is not a
stable tail estimate. Freeze's instrumented phase duration includes PMU
control overhead. Missing PMU events remain blank. Reader throughput uses
the full group wall interval, including reader tail after writing; writer
throughput uses its service interval. These are SWMR finite-budget workloads,
not parallel-writer or pure-read scaling tests.

## Evidence and reproduction

All **144** deterministic content/count comparison groups agree; **24** latest
multiworker groups agree on deterministic request/write/dataset counts.
All **480** read/mixed/flush rows match their independent oracle digests.
The validator's **600** oracle-field rows also include **120** writer-only
rows whose read digests are empty; these do not validate read content.
Every one of the 60 latest SWMR runs observed newer publications, point hits
on newly written versions, and nonzero read/write overlap. Cycles,
instructions, L1/LLC and branch metrics are present in all 840 rows; DTLB
metrics in **776**. Missing events remain blank.

Measured source commit: `4c99d0f18af25918a4162e80617f127d251f28e8`.
Measured binary SHA-256:
`7ecb7d29c148a27b7ba1975f77f72daf5e7ecbbca8ab953b48f5bf508c24fbe5`.
Both cohorts use the same validated binary and the same 58 public source inputs.

- `run_formal.py`, `*-command.json` and `*.log` retain exact commands and progress.
- Each cohort preserves its measured `raw.csv`, `metadata.json` and packed
  original commands/CSVs/logs. The process manifest hashes every packed file.
- [records-verification.json](records-verification.json) verifies source snapshot
  bytes, raw rows against original process CSVs, and packed process records.
- [measurement-source.json](measurement-source.json), `source.tar.gz` and
  [build-provenance.json](build-provenance.json) record source hashes, build
  configuration, compiler/linker and topology. Dependency pins and the native
  CSE export manifest are recorded in each cohort's metadata.
- [archive.json](archive.json) hashes the published artifacts. The private CSE
  engine sources, linked executable and full dependency checkouts are excluded.
  The measured build passed [15/15 Linux tests](../../docs/test-results/2026-10-09/mvcc-groups/group-build-tests.log)
  before this run. Test evidence and performance evidence remain separate.

Reproduce with the current five-candidate Linux build and CPU IDs selected
for your host:

```sh
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/oltp-1m --group oltp --keys 1000000 --ops 1000000 \
  --repeats 3 --threads 1,4,8 --cpus 2,3,4,5,6,7,8,9 --numa-node 0
python3 scripts/mvcc_matrix.py --binary build-core/mvcc_bench \
  --output results/history-1m --group history --keys 1000000 --ops 1000000 \
  --repeats 3 --threads 1,4,8 --cpus 2,3,4,5,6,7,8,9 --numa-node 0
python3 scripts/summarize_mvcc.py results/oltp-1m results/history-1m \
  --output results/mvcc-groups-summary
python3 scripts/plot_mvcc.py results/mvcc-groups-summary
```

Revalidate this archive without modifying its measured files:

```sh
python3 scripts/summarize_mvcc.py \
  benchmarks/mvcc-groups-formal-1m-2026-10-09/{oltp-1m,history-1m} --validate-only
# Restore one cohort's original process files if needed.
tar -xzf benchmarks/mvcc-groups-formal-1m-2026-10-09/oltp-1m/process-records.tar.gz \
  -C benchmarks/mvcc-groups-formal-1m-2026-10-09/oltp-1m
```

The earlier twelve-candidate `mvcc-v1` archive remains unchanged and has a
different read protocol. Its performance figures are not interchangeable with
this `mvcc-v2` experiment.
