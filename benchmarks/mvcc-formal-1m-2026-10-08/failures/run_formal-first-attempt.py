#!/usr/bin/env python3
"""Execute supported million-user-key profiles and a matched 500k large-value cohort."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
BINARY=REPO/'build-linux/mvcc_bench'
ENV={k:v for k,v in os.environ.items() if k.lower() not in {'http_proxy','https_proxy','all_proxy'}}
listing=subprocess.check_output([str(BINARY),'--list-indexes'],text=True,env=ENV)
indexes=[line.split('\t')[0] for line in listing.splitlines() if line.split('\t')[1]=='available']
if len(indexes)!=12: raise RuntimeError('Expected twelve available candidates')
record=json.loads((ROOT/'build-record.json').read_text())
plan=[]
for name,profile,keys,cohort in [('base-1m','base',1000000,indexes),('deep-1m','deep',1000000,indexes),('prefix-1m','prefix',1000000,indexes),('value-1m','value',1000000,[i for i in indexes if i!='cse_arena']),('value-500k','value',500000,indexes)]:
    command=['python3','-u','scripts/mvcc_matrix.py','--binary',str(BINARY),'--output',str(ROOT/name),'--keys',str(keys),'--ops','1000000','--repeats','3','--profiles',profile,'--threads','1,4,8','--cpus','2,3,4,5,6,7,8,9','--numa-node','0','--indexes',','.join(cohort)]
    details=json.loads(subprocess.check_output(command+['--list-plan'],cwd=REPO,text=True,env=ENV))
    plan.append(dict(name=name,profile=profile,keys=keys,indexes=cohort,command=command,processes=details['processes']))
rejected=BINARY.parent/'unsupported-cse-arena-value-1m.csv'
check=subprocess.run([str(BINARY),'--index','cse_arena','--stage','1','--keys','1000000','--versions','4','--value-size','1024','--output',str(rejected)],capture_output=True,text=True,env=ENV)
if check.returncode==0 or rejected.exists() or 'uint32 allocation counter' not in check.stderr:
    raise RuntimeError('Expected CSE Arena capacity rejection before output')
unsupported=dict(profile='value',index='cse_arena',user_keys=1000000,versions=4,value_size=1024,reason=check.stderr.strip(),excluded_processes=15,matched_comparison='value-500k',returncode=check.returncode)
(ROOT/'unsupported-cases.json').write_text(json.dumps([unsupported],indent=2)+'\n')
state=dict(status='running',started_at=time.time(),source_commit=record['source_commit'],binary_sha256=record['binary_sha256'],formal_processes=sum(p['processes'] for p in plan[:4]),supplemental_processes=plan[4]['processes'],plan=plan,completed_batches=[],current_batch=None)
def save():
    tmp=ROOT/'coordinator.json.tmp'; tmp.write_text(json.dumps(state,indent=2)+'\n'); tmp.replace(ROOT/'coordinator.json')
save()
try:
    for item in plan:
        if hashlib.sha256(BINARY.read_bytes()).hexdigest()!=record['binary_sha256']: raise RuntimeError('Binary changed')
        state['current_batch']=item['name']; state['batch_started_at']=time.time(); save()
        print('START',item['name'],item['processes'],'processes',flush=True)
        with (ROOT/(item['name']+'.log')).open('w') as log:
            subprocess.run(item['command'],cwd=REPO,env=ENV,stdout=log,stderr=subprocess.STDOUT,check=True)
        state['completed_batches'].append(item['name']); save()
        print('DONE',item['name'],flush=True)
    state['status']='complete'; state['current_batch']=None
except BaseException as error:
    state['status']='failed'; state['error']=repr(error)
    raise
finally:
    state['finished_at']=time.time(); save()
