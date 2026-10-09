#!/usr/bin/env python3
import csv
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
listing = subprocess.check_output([binary, '--list-indexes'], text=True)
assert {line.split('\t')[0] for line in listing.splitlines()} == {
    'rocksdb_inlineskiplist', 'btreeolc', 'unodb_art', 'wormhole', 'cse_crossbeam'}
adapters = [(fields[0], 'native_concurrent=1' in fields)
            for line in listing.splitlines()
            if (fields := line.split('\t'))[1] == 'available']
with tempfile.TemporaryDirectory() as directory:
    default = Path(directory)/'default.csv'
    subprocess.run([binary, '--keys', '10', '--ops', '20', '--output', str(default)],
                   stdout=subprocess.DEVNULL, check=True)
    assert {row['index'] for row in csv.DictReader(default.open())} == {'rocksdb_inlineskiplist'}
    for retired in ('std_map', 'abseil_btree', 'tlx_btree', 'masstree', 'hot', 'oceanbase_keybtree', 'cse_arena'):
        dest = Path(directory)/(retired+'-retired.csv')
        result = subprocess.run([binary, '--index', retired, '--output', str(dest)], capture_output=True)
        assert result.returncode != 0 and not dest.exists(), retired
    checks = {}
    for name, native in adapters:
        for view in ('latest', 'historical'):
            cases = [('normal', []), ('empty_deleted', ['--value-size','0','--delete-percent','100'])]
            if view == 'historical': cases.append(('before_first', ['--snapshot-lag','4']))
            for case, extra in cases:
                dest = Path(directory)/f'{name}-{view}-{case}.csv'
                command = [binary, '--index',name,'--stage','all','--keys','50','--versions','4',
                           '--read-view',view,'--snapshot-lag','0' if view=='latest' else '2',
                           '--ops','1000','--batch-size','7','--scan-length','9','--scan-percent','10',
                           '--key-size','24','--key-layout','global-prefix','--prefix-bytes','16',
                           '--output',str(dest),*extra]
                subprocess.run(command, stdout=subprocess.DEVNULL, check=True)
                rows = list(csv.DictReader(dest.open()))
                assert len(rows) == 8
                for row in rows:
                    assert row['schema_version']=='mvcc-v2' and row['read_view']==view
                    assert row['native_batch']==str(int(name.startswith('cse_')))
                    if row['oracle_checksum']: assert row['checksum']==row['oracle_checksum']
                    key=(view,case,row['stage'],row['phase'])
                    fields = ('checksum','requests','items','stored_versions','live_hits','tombstone_hits','not_found')
                    if view=='latest' and row['stage']=='2':
                        assert int(row['reads_with_newer_snapshot'])>0
                        assert int(row['snapshot_max_ts'])>200
                        if case=='normal': assert int(row['newer_version_hits'])>0
                    observed=tuple(row[k] for k in fields)
                    assert key not in checks or checks[key]==observed, (name,key)
                    checks[key]=observed
            dest=Path(directory)/f'{name}-{view}-threads.csv'
            result=subprocess.run([binary,'--index',name,'--stage','2','--keys','100','--ops','3000',
                                   '--read-view',view,'--snapshot-lag','0' if view=='latest' else '1',
                                   '--scan-percent','25','--scan-length','9',
                                   '--threads','4','--output',str(dest)],capture_output=True,text=True)
            if native:
                assert result.returncode==0,result.stderr
                rows=list(csv.DictReader(dest.open()))
                assert len(rows)==3
                assert all(row['checksum']==row['oracle_checksum'] for row in rows)
                if view=='historical':
                    assert all(row['reads_with_newer_snapshot']==row['newer_version_hits']=='0' for row in rows)
            else:
                assert result.returncode!=0 and not dest.exists()
        dest=Path(directory)/f'{name}-readonly.csv'
        subprocess.run([binary,'--index',name,'--stage','2','--keys','50','--ops','300',
                        '--threads','4' if native else '1','--read-percent','100',
                        '--output',str(dest)],stdout=subprocess.DEVNULL,check=True)
        row=next(csv.DictReader(dest.open()))
        assert row['written_versions']=='0' and row['reads_with_newer_snapshot']=='0'
        assert row['checksum']==row['oracle_checksum']
    for extra in (['--read-view','invalid'], ['--read-view','latest','--snapshot-lag','1']):
        dest=Path(directory)/'invalid-view.csv'
        result=subprocess.run([binary,*extra,'--output',str(dest)],capture_output=True)
        assert result.returncode!=0 and not dest.exists()
    print(f'{len(adapters)} adapters: latest publication/oracle, historical views, empty/tombstones, scans and SWMR passed')
