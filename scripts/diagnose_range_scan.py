#!/usr/bin/env python3
"""Validate the default five-length range sweep and derive per-row costs."""
import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import statistics
import tarfile

from summarize_benchmark import LABEL

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
root = parser.parse_args().directory.resolve()
meta = json.loads((root / 'metadata.json').read_text())
assert meta['status'] == 'complete' and meta['suite'] == 'range-scan'
required = {f'range_{layout}_l{length}' for layout in ('random', 'prefix')
            for length in (1, 10, 100, 1000, 10000)}
if not required.issubset({c['config_id'] for c in meta['configs']}):
    parser.error('diagnostics require both layouts and the default five scan lengths')
rows = list(csv.DictReader((root / 'raw.csv').open(newline='')))
assert len(rows) == meta['planned_processes'] * 3
assert all(len(r) == 61 and None not in r for r in rows)
assert all(r['keys'] == str(meta['keys']) for r in rows)
assert all(r['ops'] == str(meta['scan_calls']) for r in rows)
commands = [json.loads(line) for line in (root / 'commands.jsonl').read_text().splitlines()]
assert len(commands) == meta['planned_processes'] + len(meta['indexes'])
assert all(c['returncode'] == 0 for c in commands)
assert sum(not c['warmup'] for c in commands) == meta['planned_processes']

checks, seeks, corpora, grouped = defaultdict(list), defaultdict(set), defaultdict(set), defaultdict(list)
for row in rows:
    checks[(row['config_id'], row['repeat'], row['phase'])].append(
        tuple(row[f] for f in ('ops', 'items_scanned', 'checksum', 'dataset_hash')))
    corpora[(row['key_layout'], row['seed'])].add(row['dataset_hash'])
    if row['phase'] == 'seek_only':
        seeks[(row['key_layout'], row['seed'])].add(row['checksum'])
    grouped[(row['config_id'], row['phase'], row['index'])].append(row)
assert all(len(c) == len(meta['indexes']) and len(set(c)) == 1 for c in checks.values())
assert all(len(c) == 1 for c in seeks.values())
assert all(len(c) == 1 for c in corpora.values())
assert all(len(c) == meta['repeats'] for c in grouped.values())
with tarfile.open(root / 'source.tar.gz') as archive:
    assert set(archive.getnames()) == set(meta['source']['files'])
    for name, digest in meta['source']['files'].items():
        assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == digest

cost_fields = {'cycles_per_op': 'cycles_per_row', 'instructions_per_op': 'instructions_per_row',
               'l1d_miss_per_op': 'l1d_miss_per_row', 'llc_miss_per_op': 'llc_miss_per_row',
               'branch_miss_per_op': 'branch_miss_per_row', 'dtlb_miss_per_op': 'dtlb_miss_per_row'}
derived = {}
for key, samples in grouped.items():
    if key[1] == 'seek_only':
        continue
    values = defaultdict(list)
    for row in samples:
        calls, count, elapsed = int(row['ops']), int(row['items_scanned']), int(row['elapsed_ns'])
        values['mean_call_us'].append(elapsed / calls / 1e3)
        values['ns_per_row'].append(elapsed / count)
        values['rows_per_call'].append(count / calls)
        for original, metric in cost_fields.items():
            if row[original] != '':
                values[metric].append(float(row[original]) * calls / count)
    for metric, nums in values.items():
        q1, _, q3 = statistics.quantiles(nums, n=4, method='inclusive') if len(nums) > 1 else [nums[0]] * 3
        derived[(*key, metric)] = dict(samples=len(nums), median=statistics.median(nums),
                                      q1=q1, q3=q3, min=min(nums), max=max(nums))
with (root / 'scan-costs.csv').open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=['config_id', 'phase', 'index', 'metric',
                                              'samples', 'median', 'q1', 'q3', 'min', 'max'])
    writer.writeheader()
    for (config, phase, index, metric), stats in sorted(derived.items()):
        writer.writerow(dict(config_id=config, phase=phase, index=index, metric=metric, **stats))

summary = {(r['config_id'], r['phase'], r['index'], r['metric']): r
           for r in csv.DictReader((root / 'summary.csv').open(newline=''))}
labels = LABEL
def val(config, phase, index, metric='items_per_s'):
    return float(summary[(config, phase, index, metric)]['median'])
def table(headers, data):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |',
                      *['| ' + ' | '.join(map(str, row)) + ' |' for row in data]])
def cost(config, phase, index, metric):
    stat = derived.get((config, phase, index, metric))
    return '—' if stat is None else f"{stat['median']:.2f} ({stat['samples']})"

parts = ['# 百万级 Range scan 摘要与每行成本',
         f"{meta['keys']:,} 条记录；64 B user key + 9 B MVCC、64 B value；"
         f"每长度 {meta['scan_calls']:,} 次调用、{meta['repeats']} 次重复。",
         '## 随机 key：吞吐和完整扫描平均调用时间',
         table(['实现', 'Seek M/s', '游标 L100 Mrows/s', '游标 L10000 Mrows/s',
                'payload L100 Mrows/s', 'payload L10000 Mrows/s', 'L10000 平均调用 ms'],
               [[labels[i], f"{val('range_random_l1','seek_only',i,'throughput_ops_s')/1e6:.2f}",
                 *[f"{val('range_random_l'+str(n),p,i)/1e6:.2f}"
                   for p,n in [('scan_iterate',100),('scan_iterate',10000),('scan',100),('scan',10000)]],
                 f"{derived[('range_random_l10000','scan',i,'mean_call_us')]['median']/1e3:.2f}"]
                for i in meta['indexes']]),
         '## 56 B 公共前缀：相对随机 key 的吞吐比例',
         '比例大于 1 表示在这两个已测配置中公共前缀配置更快。',
         table(['实现', 'Seek L1', '游标 L100', '游标 L10000', 'payload L10000'],
               [[labels[i], *[f"{val('range_prefix_l'+str(n),p,i,m)/val('range_random_l'+str(n),p,i,m):.2f}×"
                  for p,n,m in [('seek_only',1,'throughput_ops_s'),('scan_iterate',100,'items_per_s'),
                                ('scan_iterate',10000,'items_per_s'),('scan',10000,'items_per_s')]]]
                for i in meta['indexes']])]
for phase, title in [('scan_iterate', '游标遍历'), ('scan', '完整 payload 扫描')]:
    parts += [f'## 随机 key、L10000：{title}的每行成本',
              '数值为各次运行先换算后的中位数；括号为有效重复数。缺失事件不按零处理。',
              table(['实现', 'ns/row', 'cycles/row', 'instructions/row', 'LLC miss/row', 'DTLB miss/row'],
                    [[labels[i], *[cost('range_random_l10000',phase,i,m)
                       for m in ('ns_per_row','cycles_per_row','instructions_per_row',
                                 'llc_miss_per_row','dtlb_miss_per_row')]] for i in meta['indexes']])]
missing = {metric: sum(r[metric] == '' for r in rows) for metric in cost_fields}
samples = (meta['scan_calls'] + 63) // 64
parts += ['## 测量边界',
          f'- 每阶段每次运行只有 {samples} 个延迟样本。报告中的 sampled p99 不足以稳定估计尾延迟；平均调用时间使用全部调用。\n'
          '- Prefill、Freeze、全表内容/顺序校验在计时外执行；阶段按 SeekOnly → 游标 → payload 顺序运行。\n'
          '- 吞吐按真实返回行数计算，包含表尾截断。扫描均包含 NewCursor + Seek。\n'
          '- 完整 payload 扫描包含全部 key/value checksum，不包含 SSTable 编码和磁盘写入。\n'
          '- 当前 ART/HOT adapter 包含 nibble 编码；HOT 使用 SingleThreaded 实现。\n'
          '- 同 layout/seed 跨扫描长度的输入 corpus 和 Seek checksum 一致；所有 adapter 的行数/checksum 一致。\n'
          '- 共享 Xeon Gold 6240 服务器，CPU 2 / NUMA node 0；Turbo 开启，无 CPU 独占或频率锁定。\n'
          f'- 硬件计数器空值数：`{json.dumps(missing)}`。短阶段可能因 PMU 复用未调度而缺少事件。\n'
          '- 每行 PMU 成本仍包含 harness、adapter 和 checksum；它们不是单独的数据结构内核成本。',
          '## 完整材料',
          '[完整报告](report.md) · [图表](range-scan.png) · [各阶段统计](summary.csv) · '
          '[每行成本](scan-costs.csv) · [原始数据](raw.csv) · [源码归档](source.tar.gz)']
(root / 'diagnostics.md').write_text('\n\n'.join(parts) + '\n')
report_path = root / 'report.md'
report = report_path.read_text()
tail_note = (f'**延迟样本限制：每阶段每次运行仅 {samples} 个样本，sampled p99 '
             '不能用于稳定的尾延迟排名。全量平均调用时间与每行成本见 '
             '[摘要与成本分析](diagnostics.md)。**')
if tail_note not in report:
    marker = '表中数值为中位数 [Q1,Q3]；四分位范围描述波动，不是置信区间。'
    assert marker in report
    report_path.write_text(report.replace(marker, marker + '\n\n' + tail_note, 1))
validation = dict(formal_processes=meta['planned_processes'], phase_rows=len(rows),
                  adapter_checksum_groups=len(checks), cross_length_seek_checksum_groups=len(seeks),
                  distinct_corpora=len(corpora), source_archive_files=len(meta['source']['files']),
                  excluded_warmups=len(meta['indexes']), latency_samples_per_phase=samples,
                  counter_missing=missing)
(root / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
print(json.dumps(validation, indent=2))
