#!/usr/bin/env python3
"""Export the completed nine-index comparison as PNG and editable SVG."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
meta = json.loads((OUT / 'metadata.json').read_text())
INDEXES = meta['indexes']
LABEL = {'std_map': 'std::map', 'abseil_btree': 'Abseil B-tree', 'tlx_btree': 'TLX B+Tree',
         'rocksdb_inlineskiplist': 'RocksDB InlineSkipList', 'btreeolc': 'BTreeOLC',
         'unodb_art': 'UnoDB ART', 'masstree': 'Masstree', 'hot': 'HOT (coarse RW lock)',
         'wormhole': 'Wormhole'}
COLORS = ['#6D7785', '#007D87', '#B07800', '#7655AB', '#2763AF',
          '#AC448C', '#C35A32', '#54903D', '#AA9730']
with (OUT / 'summary.csv').open(newline='') as stream:
    stats = {(r['scenario'], r['phase'], r['index'], r['metric']): r
             for r in csv.DictReader(stream)}

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                     'axes.titlesize': 12, 'axes.labelsize': 10,
                     'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.edgecolor': '#9CA5AF', 'savefig.facecolor': 'white',
                     'svg.fonttype': 'none'})
fig, axes = plt.subplots(3, 2, figsize=(17, 14), layout='constrained')

def bars(ax, scenario, phase, metric, scale, title, xlabel):
    selected = [stats[(scenario, phase, i, metric)] for i in INDEXES]
    med = np.array([float(s['median']) / scale for s in selected])
    q1 = np.array([float(s['q1']) / scale for s in selected])
    q3 = np.array([float(s['q3']) / scale for s in selected])
    positions = np.arange(len(INDEXES))
    ax.barh(positions, med, color=COLORS, height=0.60,
            xerr=np.array([med - q1, q3 - med]),
            error_kw={'ecolor': '#202630', 'capsize': 3, 'elinewidth': 1})
    ax.set_yticks(positions, [LABEL[i] for i in INDEXES])
    ax.invert_yaxis()
    ax.set_xlim(0, max(q3) * 1.22)
    ax.set_title(title, loc='left', fontweight='bold', pad=12)
    ax.set_xlabel(xlabel)
    ax.xaxis.grid(True, alpha=0.16)
    ax.set_axisbelow(True)
    for position, (value, high) in enumerate(zip(med, q3)):
        ax.text(high + max(q3) * 0.023, position, f'{value:.2f}', va='center', fontsize=9)

bars(axes[0, 0], 'single_uniform', 'insert', 'throughput_ops_s', 1e6,
     'A   Single-thread random Insert', 'Million operations / second')
bars(axes[0, 1], 'single_uniform', 'get', 'throughput_ops_s', 1e6,
     'B   Single-thread exact Get (uniform, all hits)', 'Million operations / second')
bars(axes[1, 0], 'lifecycle_uniform', 'ordered_flush', 'items_per_s', 1e6,
     'C   Frozen full scan + order/checksum validation', 'Million rows / second')
bars(axes[1, 1], 'single_uniform', 'insert', 'bytes_per_key', 1,
     'D   Resident memory growth after Insert', 'RSS bytes / stored version')
axes[1, 1].axvline(97, color='#31343B', linestyle='--', linewidth=1)
axes[1, 1].text(97, len(INDEXES) - 0.17, '97 B logical key + value', fontsize=9,
                ha='center', va='top', color='#31343B')
axes[1, 1].set_ylim(len(INDEXES) + 0.25, -0.6)
bars(axes[2, 0], 'lifecycle_uniform', 'measured_phase_sum', 'elapsed_ns', 1e6,
     'E   Insert + Freeze + full scan + Destroy', 'Measured lifecycle milliseconds (lower is faster)')

ax = axes[2, 1]
threads = [s[3] for s in meta['scenarios'] if s[1] == 2]
for index, color in zip(INDEXES, COLORS):
    selected = [stats[(f'mixed_t{t}', 'mixed', index, 'throughput_ops_s')] for t in threads]
    values = [float(s['median']) / 1e6 for s in selected]
    lows = [float(s['q1']) / 1e6 for s in selected]
    highs = [float(s['q3']) / 1e6 for s in selected]
    coarse = index in ('std_map', 'abseil_btree', 'tlx_btree', 'hot')
    ax.plot(threads, values, color=color, marker='o', label=LABEL[index],
            linewidth=1.9, linestyle='--' if coarse else '-')
    ax.fill_between(threads, lows, highs, color=color, alpha=0.11)
ax.set_title('F   80% exact Get / 20% new-version Insert', loc='left', fontweight='bold', pad=12)
ax.set_xlabel('Worker threads (one physical core per worker)')
ax.set_ylabel('Million operations / second')
ax.set_xticks(threads)
ax.set_xlim(0.6, max(threads) + 0.6)
ax.set_ylim(bottom=0)
ax.grid(alpha=0.16)
ax.legend(loc='upper left', fontsize=8, frameon=True, facecolor='white', framealpha=1, ncol=1)

fig.suptitle('memtable-bench | Xeon Gold 6240 | 1M stored versions | 33 B logical key + 64 B value',
             fontsize=16, fontweight='bold')
fig.supxlabel('5 runs: median and Q1-Q3; NUMA node 0, physical CPUs 2-17; shared server, Turbo enabled.\n'
              'ART/HOT store 67 B nibble keys; codec and synchronization costs included. Dashed curves: coarse RW lock.\n'
              'Scans validate order/checksum; no SSTable compression or disk I/O. RSS is an allocation/allocator estimate.',
              fontsize=10, color='#4C535B')
fig.savefig(OUT / 'comparison.png', dpi=180)
fig.savefig(OUT / 'comparison.svg')
print(OUT / 'comparison.png')
