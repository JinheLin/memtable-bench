#!/usr/bin/env python3
"""Verify unchanged deterministic workload content with the pre-change binary."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parent
repo = root.parents[1]
binaries = {'before': root/'mvcc_bench-before', 'after': repo/'build-linux-core/mvcc_bench'}
fields = ('phase', 'requests', 'point_reads', 'scan_requests', 'written_versions',
          'live_hits', 'tombstone_hits', 'not_found', 'items', 'stored_versions',
          'versions_tested', 'checksum', 'oracle_checksum', 'dataset_hash',
          'snapshot_min_ts', 'snapshot_max_ts', 'reads_with_newer_snapshot', 'newer_version_hits')
cases = []
for view, versions, lag in (('latest',2,0), ('historical',64,63)):
    for stage in (1,2,3):
        observed = {}
        wall = {}
        for label, binary in binaries.items():
            destination = root/f'fixture-{label}-{view}-s{stage}.csv'
            assert not destination.exists()
            command = [str(binary), '--stage',str(stage),'--read-view',view,
                       '--versions',str(versions),'--snapshot-lag',str(lag),
                       '--keys','4096','--ops','20000','--threads','1',
                       '--cpu-list','2','--numa-node','0','--output',str(destination)]
            began = time.monotonic()
            subprocess.run(command,stdout=subprocess.DEVNULL,check=True)
            wall[label] = time.monotonic()-began
            observed[label] = [tuple(row[field] for field in fields)
                               for row in csv.DictReader(destination.open())]
        assert observed['before'] == observed['after'], (view,stage)
        cases.append(dict(read_view=view,versions=versions,stage=stage,
                          phase_rows=len(observed['after']), deterministic_fields_match=True,
                          wall_seconds=wall))
proof = dict(status='verified', binary_sha256={name:hashlib.sha256(path.read_bytes()).hexdigest()
                                              for name,path in binaries.items()},
             compared_fields=fields,cases=cases,processes=12,
             conclusion='Deterministic inputs, counts and content unchanged; timings are functional probe data.')
(root/'fixture-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(dict(status='verified',cases=len(cases),processes=12),indent=2))
