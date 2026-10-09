#!/usr/bin/env python3
"""Optional PNG/SVG export for completed range-scan length sweeps."""
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

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
root = parser.parse_args().directory.resolve()
meta = json.loads((root/'metadata.json').read_text())
assert meta['status']=='complete' and meta['suite']=='range-scan'
with (root/'summary.csv').open(newline='') as stream:
    stats = {(r['config_id'],r['phase'],r['index'],r['metric']):r for r in csv.DictReader(stream)}
layouts = [layout for layout in ('random','global-prefix')
           if any(c['key_layout']==layout for c in meta['configs'])]
indexes = meta['indexes']
colors = dict(zip(indexes,['#6D7785','#007D87','#B07800','#7655AB','#2763AF',
                          '#AC448C','#C35A32','#54903D','#AA9730']))
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':12,
                     'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
fig,axes = plt.subplots(len(layouts),3,figsize=(18,4.2*len(layouts)+2.2),squeeze=False)
fig.subplots_adjust(top=.79,bottom=.14,hspace=.45,wspace=.25)
for row,layout in enumerate(layouts):
    configs = sorted((c for c in meta['configs'] if c['key_layout']==layout),key=lambda c:c['scan_length'])
    x = [c['scan_length'] for c in configs]
    for column,(phase,metric,title) in enumerate([
        ('seek_only','throughput_ops_s','SeekOnly (NewCursor + Seek)'),
        ('scan_iterate','items_per_s','Bounded cursor traversal'),
        ('scan','items_per_s','Full-payload checksum scan')]):
        ax = axes[row,column]
        for index in indexes:
            selected = [stats[(c['config_id'],phase,index,metric)] for c in configs]
            median = np.array([float(s['median'])/1e6 for s in selected])
            q1 = np.array([float(s['q1'])/1e6 for s in selected])
            q3 = np.array([float(s['q3'])/1e6 for s in selected])
            ax.plot(x,median,color=colors[index],marker='o',linewidth=1.8,label=LABEL[index])
            ax.fill_between(x,q1,q3,color=colors[index],alpha=.12)
        ax.set_xscale('log',base=10)
        ax.xaxis.set_major_formatter(ScalarFormatter())
        ax.set_xticks(x)
        ax.set_ylim(bottom=0)
        ax.set_xlabel('Maximum rows per scan call')
        ax.set_ylabel('Million calls / second' if phase=='seek_only' else 'Million actual rows / second')
        ax.set_title(('Random keys' if layout=='random' else '56 B shared prefix')+' | '+title,
                     loc='left',fontweight='bold',pad=10)
        ax.grid(alpha=.16)
fig.suptitle(f"memtable-bench | Range scans | {meta['keys']:,} stored versions | {meta['scan_calls']:,} calls per length",
             fontsize=16,fontweight='bold',y=.97)
handles,labels = axes[0,0].get_legend_handles_labels()
fig.legend(handles,labels,ncol=5,loc='upper center',bbox_to_anchor=(.5,.92),frameon=False)
repeat_label = 'repeat' if meta['repeats']==1 else 'repeats'
fig.text(.5,.035,f"{meta['repeats']} {repeat_label}: median and Q1-Q3. Same hit-start traces across lengths; random inserts, frozen indexes.\n"
         f"NUMA node {meta['numa_node']}; shared server, no CPU reservation. Prefill/freeze/full validation outside timing.\n"
         'Row limits can truncate at EOF. All scans include Seek; Key encoding, copying and synchronization costs included. No disk I/O.',
         ha='center',fontsize=10,color='#4C535B')
fig.savefig(root/'range-scan.png',dpi=180,facecolor='white')
fig.savefig(root/'range-scan.svg',facecolor='white')
print(root/'range-scan.png')
