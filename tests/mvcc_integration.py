#!/usr/bin/env python3
import csv
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
listing = subprocess.check_output([binary, '--list-indexes'], text=True)
adapters = [(fields[0], 'native_concurrent=1' in fields)
            for line in listing.splitlines()
            if (fields := line.split('\t'))[1] == 'available']
with tempfile.TemporaryDirectory() as directory:
    checks = {}
    for name, native in adapters:
        for case, extra in [('normal', []), ('empty_deleted', ['--value-size','0','--delete-percent','100']),
                            ('before_first', ['--snapshot-lag','4'])]:
            dest = Path(directory)/f'{name}-{case}.csv'
            command = [binary, '--index',name,'--stage','all','--keys','50','--versions','4',
                       '--ops','180','--batch-size','7','--scan-length','9',
                       '--key-size','24','--key-layout','global-prefix','--prefix-bytes','16',
                       '--output',str(dest),*extra]
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True)
            rows = list(csv.DictReader(dest.open()))
            assert len(rows) == 10
            for row in rows:
                assert row['schema_version']=='mvcc-v1'
                assert row['native_batch']==str(int(name.startswith('cse_')))
                key=(case,row['stage'],row['phase'])
                observed=tuple(row[k] for k in ('checksum','requests','items','stored_versions','live_hits','tombstone_hits','not_found'))
                assert key not in checks or checks[key]==observed, (name,key)
                checks[key]=observed
        dest=Path(directory)/f'{name}-threads.csv'
        result=subprocess.run([binary,'--index',name,'--stage','2','--keys','50','--ops','300',
                               '--threads','4','--output',str(dest)],capture_output=True,text=True)
        if native:
            assert result.returncode==0,result.stderr
            assert len(list(csv.DictReader(dest.open())))==3
        else:
            assert result.returncode!=0 and not dest.exists()
    print(f'{len(adapters)} adapters: MVCC cross-check, empty values, tombstones, absent snapshots, SWMR policy passed')
