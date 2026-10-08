#!/usr/bin/env python3
"""Optional Matplotlib export for a completed full screening suite (PNG/SVG)."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
import numpy as np

from summarize_benchmark import LABEL

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory',type=Path)
root=parser.parse_args().directory.resolve()
meta=json.loads((root/'metadata.json').read_text())
assert meta['status']=='complete' and meta['suite']=='screening'
with (root/'summary.csv').open(newline='') as stream:
    stats={(r['config_id'],r['phase'],r['index'],r['metric']):r for r in csv.DictReader(stream)}
indexes=meta['indexes']
colors=dict(zip(indexes,['#6D7785','#007D87','#B07800','#7655AB','#2763AF',
                         '#AC448C','#C35A32','#54903D','#AA9730']))
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':12,
                     'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
fig,axes=plt.subplots(3,2,figsize=(16,13))
fig.subplots_adjust(top=.86,bottom=.10,hspace=.42,wspace=.22)

def curve(ax,configs,x,phase,metric,title,xlabel,scale=1e6,log=False):
    for index in indexes:
        selected=[stats[(c,phase,index,metric)] for c in configs]
        y=np.array([float(s['median'])/scale for s in selected])
        q1=np.array([float(s['q1'])/scale for s in selected])
        q3=np.array([float(s['q3'])/scale for s in selected])
        ax.plot(x,y,color=colors[index],marker='o',linewidth=1.8,label=LABEL[index])
        ax.fill_between(x,q1,q3,color=colors[index],alpha=.12)
    if log:
        ax.set_xscale('log',base=2)
        ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.set_xticks(x)
    ax.set_xlabel(xlabel)
    ax.set_ylabel('Million rows / second' if metric=='items_per_s' else 'Million operations / second')
    ax.set_title(title,loc='left',fontweight='bold',pad=10)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=.16)

curve(axes[0,0],[f'key_k{k}' for k in (8,16,32,64,112)],[8,16,32,64,112],
      'lookup_only','throughput_ops_s','A   Key length: LookupOnly','User key bytes (plus 9 B MVCC trailer)')
curve(axes[0,1],['key_k64','prefix_p8','prefix_p24','prefix_p56'],[0,8,24,56],
      'lookup_only','throughput_ops_s','B   Shared prefix: LookupOnly','Global shared prefix bytes (64 B user key)')
value_configs=['value_v8','key_k64','value_v1024']
curve(axes[1,0],value_configs,[8,64,1024],'lookup_only','throughput_ops_s',
      'C   Value size: LookupOnly (no value copy)','Value bytes',log=True)
curve(axes[1,1],value_configs,[8,64,1024],'get','throughput_ops_s',
      'D   Value size: GetCopy','Value bytes',log=True)
curve(axes[2,0],value_configs,[8,64,1024],'scan_iterate','items_per_s',
      'E   Value size: bounded cursor traversal','Value bytes',log=True)
curve(axes[2,1],value_configs,[8,64,1024],'scan','items_per_s',
      'F   Value size: full-payload checksum scan','Value bytes',log=True)
fig.suptitle('memtable-bench | Key / prefix / value sensitivity | '+f"{meta['keys']:,} stored versions",
             fontsize=16,fontweight='bold',y=.98)
handles,labels=axes[0,0].get_legend_handles_labels()
fig.legend(handles,labels,ncol=5,loc='upper center',bbox_to_anchor=(.5,.95),frameon=False)
fig.text(.5,.025,f"{meta['repeats']} repeats: median and Q1-Q3. Uniform hits, random inserts; precomputed logical keys.\n"
         'NUMA node 0; shared Xeon server, Turbo enabled. ART/HOT include nibble codec; HOT uses a coarse RW lock.\n'
         'Cursor scans consume key size/first byte; full scans hash all bytes. No disk I/O. Values remain stored in all cases.',
         ha='center',fontsize=10,color='#4C535B')
fig.savefig(root/'sensitivity.png',dpi=180,facecolor='white')
fig.savefig(root/'sensitivity.svg',facecolor='white')
print(root/'sensitivity.png')
