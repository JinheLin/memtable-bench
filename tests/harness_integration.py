#!/usr/bin/env python3
"""Check equivalent workloads, CSV metadata and early rejection in actual binaries."""
import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
placement = []
if "MEMTABLE_BENCH_TEST_NUMA_NODE" in os.environ:
    placement = ["--numa-node", os.environ["MEMTABLE_BENCH_TEST_NUMA_NODE"],
                 "--cpu-list", os.environ["MEMTABLE_BENCH_TEST_CPUS"]]

def invoke(*args, succeeds=True):
    result = subprocess.run([binary, *placement, *map(str, args)], text=True, capture_output=True, timeout=90)
    if (result.returncode == 0) != succeeds:
        raise AssertionError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout

adapters = {}
for line in invoke("--list-indexes").splitlines():
    fields = line.split("\t")
    metadata = dict(field.split("=", 1) for field in fields[3:])
    adapters[fields[0]] = (fields[1] == "available", metadata)
if os.environ.get("MEMTABLE_BENCH_REQUIRE_HOT") == "1" and not adapters["hot"][0]:
    raise AssertionError("HOT runtime validation requires a CPU with its advertised ISA features")

with tempfile.TemporaryDirectory(prefix="memtable-contract-") as directory:
    root = Path(directory)
    reference = None
    for name, (available, metadata) in adapters.items():
        output = root / (name + ".csv")
        if not available:
            invoke("--index", name, "--output", output, succeeds=False)
            assert not output.exists(), name
            continue
        invoke("--stage", "all", "--index", name, "--internal-key", "--keys", 2500,
               "--ops", 5000, "--threads", 4, "--key-size", 24, "--value-size", 64,
               "--scan-length", 37, "--distribution", "zipf", "--output", output)
        with output.open(newline="") as stream:
            reader = csv.DictReader(stream)
            assert len(reader.fieldnames) == 55, reader.fieldnames
            rows = list(reader)
        assert len(rows) == 8, name
        observed = []
        for row in rows:
            assert None not in row and None not in row.values(), row
            assert row["index"] == name and row["adapter_mode"], row
            assert row["adapter_key_encoding"] == metadata["key_encoding"], row
            assert row["key_size"] == "24" and row["internal_key"] == "1", row
            assert float(row["throughput_ops_s"]) > 0, row
            observed.append(tuple(row[field] for field in
                                  ("stage", "phase", "ops", "items_scanned", "checksum")))
        if reference is None:
            reference = observed
        assert observed == reference, f"workload/checksum mismatch: {name}"
        print(f"{name}: all stages, CSV and checksums match std_map")

        if name in ("unodb_art", "rocksdb_inlineskiplist"):
            rejected = root / (name + "-upsert.csv")
            invoke("--stage", 2, "--index", name, "--read-percent", 0,
                   "--output", rejected, succeeds=False)
            assert not rejected.exists(), name
        if "max_key_bytes" in metadata:
            rejected = root / (name + "-too-long.csv")
            invoke("--stage", 3, "--index", name, "--internal-key",
                   "--key-size", metadata["max_key_bytes"], "--output", rejected, succeeds=False)
            assert not rejected.exists(), name

    for layout, prefix, groups in [("random", 0, 1), ("global-prefix", 24, 1),
                                   ("group-prefix", 24, 16)]:
        reference = None
        dataset_reference = None
        for name, (available, metadata) in adapters.items():
            if not available:
                continue
            output = root / (layout + "-" + name + ".csv")
            dataset = root / (layout + "-" + name + ".json")
            invoke("--stage", "all", "--index", name, "--internal-key", "--keys", 2500,
                   "--ops", 5000, "--threads", 4, "--key-size", 64, "--value-size", 1024,
                   "--scan-length", 37, "--distribution", "zipf", "--measure-detail",
                   "--key-layout", layout, "--prefix-bytes", prefix, "--prefix-groups", groups,
                   "--key-preparation", "precomputed", "--insert-order", "reverse",
                   "--hotspot-placement", "clustered", "--dataset-output", dataset,
                   "--output", output)
            import json
            info = json.loads(dataset.read_text())
            assert sum(info["lcp_histogram"]) == 2499
            assert info["lcp_p50"] >= prefix and info["lcp_max"] < 64
            if dataset_reference is None:
                dataset_reference = info
            assert info == dataset_reference, name
            with output.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 11
            assert all(len(r) == 55 and None not in r and None not in r.values() for r in rows)
            for row in rows:
                assert row["schema_version"] == "3" and row["key_layout"] == layout
                assert row["logical_key_bytes"] == "73"
                assert row["physical_key_bytes"] == ("147" if metadata["key_encoding"] == "nibble_terminated" else "73")
                assert row["dataset_hash"] == info["dataset_hash_fnv1a64"]
                if row["phase"] in ("scan_iterate", "ordered_traverse", "lookup_only"):
                    assert row["payload_gb_s"] == ""
                if row["phase"] == "get":
                    assert float(row["logical_payload_bytes"]) == 5000 * 1024
            observed = [tuple(r[field] for field in
                              ("stage", "phase", "ops", "items_scanned", "checksum")) for r in rows]
            if reference is None:
                reference = observed
            assert observed == reference, (layout, name)
        print(layout + ": precomputed keys, split metrics and all-adapter checksums agree")

    for length, expected_rows in [(10, 40), (1000, 506)]:
        reference = None
        for name, (available, metadata) in adapters.items():
            if not available:
                continue
            output = root / f"range-{length}-{name}.csv"
            invoke("--stage", 1, "--scan-only", "--scan-ops", 4, "--scan-length", length,
                   "--index", name, "--keys", 128, "--key-size", 64, "--value-size", 64,
                   "--internal-key", "--key-preparation", "precomputed", "--key-layout", "random",
                   "--distribution", "sequential", "--output", output)
            with output.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            assert [r["phase"] for r in rows] == ["seek_only", "scan_iterate", "scan"]
            assert all(len(r)==55 and r["ops"]=="4" for r in rows)
            assert [int(r["items_scanned"]) for r in rows]==[4,expected_rows,expected_rows]
            assert rows[0]["payload_gb_s"]==rows[1]["payload_gb_s"]==""
            assert float(rows[2]["logical_payload_bytes"])==expected_rows*(73+64)
            observed=[tuple(r[f] for f in ("phase","ops","items_scanned","checksum")) for r in rows]
            if reference is None:
                reference=observed
            assert observed==reference, (length,name)
        print(f"range scans: limit {length}, actual rows {expected_rows}, all-adapter checksums agree")

    for args in [("--scan-only", "--stage", 2),
                 ("--stage", 1, "--scan-ops", 4),
                 ("--stage", 1, "--scan-only", "--scan-ops", 0),
                 ("--key-layout", "random"),
                 ("--key-preparation", "precomputed", "--key-layout", "global-prefix", "--prefix-bytes", 16, "--key-size", 16),
                 ("--key-preparation", "precomputed", "--key-layout", "group-prefix", "--prefix-bytes", 4, "--prefix-groups", 16)]:
        rejected = root / "bad-layout.csv"
        invoke(*args, "--output", rejected, succeeds=False)
        assert not rejected.exists()

    old_schema = root / "old-schema.csv"
    old_schema.write_text("index,checksum\nstd_map,1\n")
    invoke("--stage", 3, "--keys", 10, "--output", old_schema, succeeds=False)
    assert old_schema.read_text() == "index,checksum\nstd_map,1\n"
