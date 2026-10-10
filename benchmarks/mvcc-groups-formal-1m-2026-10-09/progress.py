#!/usr/bin/env python3
"""Compact read-only progress snapshot; no benchmark scheduling changes."""
import csv
import json
from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parent
status = json.loads((root / 'status.json').read_text())
result = dict(status=status['status'], elapsed_minutes=round((time.time()-status['started_at'])/60, 1),
              completed_groups=status['completed_groups'])
for group in ('oltp', 'history'):
    log = root / (group + '.log')
    if log.exists():
        lines = log.read_text().splitlines()
        result[group] = lines[-1] if lines else 'Preparing first process'
for line in subprocess.check_output(['ps', '-eo', 'pid,etimes,pcpu,rss,args'], text=True).splitlines():
    fields = line.split(None, 4)
    if len(fields) < 5 or not fields[4].startswith(str(root.parents[1] / 'build-linux-core/mvcc_bench') + ' '):
        continue
    command = fields[4].split()
    dest = Path(command[command.index('--output')+1])
    result['active'] = dict(name=dest.stem, seconds=int(fields[1]), cpu_percent=float(fields[2]),
                            rss_gib=round(int(fields[3])/2**20, 2))
    if dest.exists():
        result['active']['emitted_phases'] = [r.get('phase') for r in csv.DictReader(dest.open())]
mem = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
result['available_gib'] = round(mem['MemAvailable']/2**20, 1)
result['swap_used_gib'] = round((mem['SwapTotal']-mem['SwapFree'])/2**20, 1)
print(json.dumps(result))
