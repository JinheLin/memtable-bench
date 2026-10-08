#!/usr/bin/env python3
"""Optional PNG/SVG figures from validated MVCC summaries."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    proof = json.loads((root / 'validation.json').read_text())
    if proof['status'] != 'complete':
        raise ValueError('Only complete, validated summaries can be plotted')
    with (root / 'summary.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    combinations = list(dict.fromkeys((row['cohort'], row['profile']) for row in rows))
    colors = {index: plt.get_cmap('tab20')(ordinal) for ordinal, index in enumerate(
        dict.fromkeys(row['index'] for row in rows))}
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False, 'svg.fonttype': 'none'})
    panels = [('batch_load', 'throughput_versions_s', 'Load: million written versions/s', 1),
              ('get_snapshot', 'throughput_requests_s', 'Historical Get: million requests/s', 1),
              ('scan_snapshot', 'items_s', 'Historical scan: million live rows/s', 1),
              ('batch_load', 'bytes_per_version', 'RSS growth after load: bytes/version', 1)]
    for cohort, profile in combinations:
        samples = [row for row in rows if row['cohort'] == cohort and row['profile'] == profile]
        stem = cohort if sum(name == cohort for name, _ in combinations) == 1 else f'{cohort}-{profile}'
        stats = {(row['phase'], row['metric'], int(row['stage']), int(row['scenario_threads']), row['index']): row
                 for row in samples}
        indexes = list(dict.fromkeys(row['index'] for row in samples))
        # Summary rows are sorted by index. Use the same order in every panel.
        positions = np.arange(len(indexes))
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        for ax, (phase, metric, title, stage) in zip(axes.flat, panels):
            chosen = [stats[(phase, metric, stage, 1, index)] for index in indexes]
            scale = 1 if metric == 'bytes_per_version' else 1e6
            median = np.array([float(row['median']) / scale for row in chosen])
            q1 = np.array([float(row['q1']) / scale for row in chosen])
            q3 = np.array([float(row['q3']) / scale for row in chosen])
            ax.barh(positions, median, color=[colors[index] for index in indexes], height=.7,
                    xerr=np.array([median - q1, q3 - median]), capsize=3)
            ax.set_yticks(positions, indexes)
            ax.invert_yaxis()
            ax.set_title(title, loc='left', fontweight='bold')
            ax.set_xlim(left=0)
            ax.grid(axis='x', alpha=.18)
        fig.suptitle(f'MVCC benchmark | {stem}', fontsize=17, fontweight='bold')
        fig.text(.5, .015, 'Fresh processes; medians with Q1-Q3. Fixed historical snapshots. '
                 'Adapter, codec, copies and checksums included.\n'
                 'Shared Xeon host; CPU/NUMA binding; no CPU reservation or frequency lock. '
                 'No disk I/O. Cohorts with different key counts stay separate.', ha='center', fontsize=10)
        fig.tight_layout(rect=(0, .05, 1, .95))
        fig.savefig(root / f'{stem}.png', dpi=160, facecolor='white')
        fig.savefig(root / f'{stem}.svg', facecolor='white')
        plt.close(fig)
        counts = sorted({int(row['scenario_threads']) for row in samples if row['phase'] == 'swmr_total'})
        native = [index for index in indexes if counts and
                  ('swmr_total', 'throughput_requests_s', 2, counts[0], index) in stats]
        if not native:
            continue
        fig, axes = plt.subplots(1, 3, figsize=(17, 5.8))
        for ax, (phase, metric, title) in zip(axes, [
                ('swmr_total', 'throughput_requests_s', 'Group wall throughput: Mrequests/s'),
                ('swmr_readers', 'throughput_requests_s', 'Readers / group wall: Mrequests/s'),
                ('swmr_writer_batch', 'throughput_versions_s', 'Writer service: Mversions/s')]):
            for index in native:
                chosen = [stats[(phase, metric, 2, count, index)] for count in counts]
                median = [float(row['median']) / 1e6 for row in chosen]
                ax.plot(counts, median, marker='o', color=colors[index], label=index)
            ax.set_title(title, loc='left', fontsize=11)
            ax.set_xticks(counts)
            ax.set_xlabel('Workers: one writer + N-1 readers')
            ax.set_ylim(bottom=0)
            ax.grid(alpha=.18)
        fig.suptitle(f'MVCC SWMR | {stem}', fontsize=16, fontweight='bold')
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, ncol=4, loc='lower center', bbox_to_anchor=(.5, .035), frameon=False)
        fig.text(.5, .01, 'Fixed finite read/write budgets; reader tail included in group wall time. '
                 'This does not measure parallel writers or pure read-only scaling.', ha='center', fontsize=10)
        fig.tight_layout(rect=(0, .16, 1, .94))
        fig.savefig(root / f'{stem}-swmr.png', dpi=160, facecolor='white')
        fig.savefig(root / f'{stem}-swmr.svg', facecolor='white')
        plt.close(fig)
        print(root / f'{stem}.png')


if __name__ == '__main__':
    main()
