#!/usr/bin/env python3
"""Additional memory/cache diagnostics from a completed screening run."""
import csv
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
meta = json.loads((root / 'metadata.json').read_text())
assert meta['status'] == 'complete' and meta['suite'] == 'screening'
with (root / 'summary.csv').open(newline='') as stream:
    stats = {(r['config_id'], r['phase'], r['index'], r['metric']): r
             for r in csv.DictReader(stream)}

labels = {'std_map': 'std::map', 'abseil_btree': 'Abseil B-tree',
          'tlx_btree': 'TLX B+Tree', 'rocksdb_inlineskiplist': 'RocksDB InlineSkipList',
          'btreeolc': 'BTreeOLC', 'unodb_art': 'UnoDB ART', 'masstree': 'Masstree',
          'hot': 'HOT', 'wormhole': 'Wormhole'}

def median(config, index, phase='lookup_only', metric='throughput_ops_s'):
    return float(stats[(config, phase, index, metric)]['median'])

def cell(config, index, phase, metric, scale=1, digits=2):
    s = stats[(config, phase, index, metric)]
    return f"{float(s['median'])/scale:.{digits}f} [{float(s['q1'])/scale:.{digits}f}, {float(s['q3'])/scale:.{digits}f}]"

def table(header, rows):
    return '\n'.join(['| ' + ' | '.join(header) + ' |',
                      '| ' + ' | '.join(['---'] * len(header)) + ' |',
                      *['| ' + ' | '.join(row) + ' |' for row in rows]])

indexes = meta['indexes']
baseline = table(['实现', 'Insert Mops/s', 'LookupOnly Mops/s', 'GetCopy Mops/s',
                  '游标 Mrows/s', '完整扫描 Mrows/s', '插入后 RSS B/key'],
                 [[labels[i],
                   cell('key_k64', i, 'insert', 'throughput_ops_s', 1e6),
                   cell('key_k64', i, 'lookup_only', 'throughput_ops_s', 1e6),
                   cell('key_k64', i, 'get', 'throughput_ops_s', 1e6),
                   cell('key_k64', i, 'scan_iterate', 'items_per_s', 1e6),
                   cell('key_k64', i, 'scan', 'items_per_s', 1e6),
                   cell('key_k64', i, 'insert', 'bytes_per_key')]
                  for i in indexes])

counters = table(['实现', 'cycles/op', 'instructions/op', 'IPC', 'L1D miss/op',
                  'LLC miss/op', 'branch miss/op', 'DTLB miss/op', '采样 p99 ns'],
                 [[labels[i], *[cell('key_k64', i, 'lookup_only', metric)
                    for metric in ('cycles_per_op', 'instructions_per_op', 'ipc',
                                   'l1d_miss_per_op', 'llc_miss_per_op',
                                   'branch_miss_per_op', 'dtlb_miss_per_op',
                                   'latency_p99_ns')]] for i in indexes])

memory = table(['实现', 'V=8 RSS B/key', 'V=64 RSS B/key', 'V=1024 RSS B/key',
                'V=8 LLC miss/lookup', 'V=1024 LLC miss/lookup'],
               [[labels[i],
                 *[cell(c, i, 'insert', 'bytes_per_key')
                   for c in ('value_v8', 'key_k64', 'value_v1024')],
                 *[cell(c, i, 'lookup_only', 'llc_miss_per_op')
                   for c in ('value_v8', 'value_v1024')]] for i in indexes])

effect_specs = [('key112_over_key8', 'key_k112', 'key_k8', 'lookup_only', 'throughput_ops_s'),
                ('prefix56_over_prefix0', 'prefix_p56', 'key_k64', 'lookup_only', 'throughput_ops_s'),
                ('value1024_over_value8_lookup', 'value_v1024', 'value_v8', 'lookup_only', 'throughput_ops_s'),
                ('value1024_over_value8_copy', 'value_v1024', 'value_v8', 'get', 'throughput_ops_s'),
                ('value1024_over_value8_cursor', 'value_v1024', 'value_v8', 'scan_iterate', 'items_per_s'),
                ('value1024_over_value8_scan', 'value_v1024', 'value_v8', 'scan', 'items_per_s')]
with (root / 'effects.csv').open('w', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['index', 'effect', 'numerator_config', 'denominator_config', 'phase',
                     'metric', 'median_rate_ratio'])
    for i in indexes:
        for name, numerator, denominator, phase, metric in effect_specs:
            writer.writerow([i, name, numerator, denominator, phase, metric,
                             median(numerator, i, phase, metric) / median(denominator, i, phase, metric)])
effects = table(['实现', 'K112/K8 查找', 'P56/P0 查找', 'V1024/V8 查找',
                 'V1024/V8 GetCopy', 'V1024/V8 游标', 'V1024/V8 完整扫描'],
                [[labels[i], *[f'{median(n, i, p, m)/median(d, i, p, m):.3f}×'
                              for _, n, d, p, m in effect_specs]] for i in indexes])

(root / 'diagnostics.md').write_text(f'''# 内存、cache 与吞吐补充诊断

本文件来自同一轮完整筛选实验的 `summary.csv`。原始测量方法和边界见 `report.md`。
K 均指 user key，另附 9 B MVCC trailer；固定 {meta['keys']:,} 条记录、uniform 命中读、随机插入。
数值为 {meta['repeats']} 次重复的中位数 [Q1,Q3]，不是置信区间。吞吐接近时需要增加重复后再判断。

## 中心配置：K=64 B，V=64 B，无人工公共前缀

{baseline}

## 中心配置：LookupOnly 的硬件计数器与延迟

{counters}

延迟每 64 次操作采样一次。硬件事件排除 kernel/hypervisor，并按 PMU enabled/running 时间缩放；
这些数据描述整体 harness + adapter，不能直接视为裸索引算法的指令数。

## Value 大小：内存增长与不拷贝 value 的查找

{memory}

RSS 在预生成 key/trace 后、索引构造前开始取差，B/key 使用插入阶段的增长。
进程 RSS 有页粒度和 allocator 影响；这不是精确的节点或 value 内存统计。
即使不复制 value，value 仍被存储，因此不同 value 大小会改变索引分配布局和工作集。
固定条数实验也让总内存随 value 大小变化；尚不能回答固定 MemTable 内存预算下的优劣。

## 描述性吞吐比值

{effects}

上述比值取两个配置吞吐中位数之比，1 表示相同，大于 1 表示分子配置更快。
K 对比固定 V=64、P=0；P 对比固定 K=64、V=64；V 对比固定 K=64、P=0。
不对这些比值给出显著性判断。LookupOnly 与 GetCopy 的阶段顺序固定，不能相减得到精确拷贝成本。
完整扫描包含逐字节 checksum，其吞吐还受逻辑 payload 大小影响；它没有 SSTable 编码或磁盘 I/O。
ART/HOT 的 nibble 编码、HOT 的粗锁以及各 adapter 的所有权策略都保留在测量中。

## UnoDB 长 key 的实现边界

当前 pin 的 `olc_db<key_view,value_view>` 使用 keyless leaf：完整 key 字节由 inode 路径表示，
迭代器沿路径重建 key。单子节点 I4 链每个节点最多消费 7 B prefix 加 1 B dispatch。
这与本 adapter 的 nibble 编码叠加后，长而不共享的 key 会产生较长节点链。
源码依据是 [key policy](https://github.com/unodb-dev/unodb/blob/89f52799743ec2093426bdcf7a7cbaaa95ca848c/art_common.hpp#L89)
和 [chain builder](https://github.com/unodb-dev/unodb/blob/89f52799743ec2093426bdcf7a7cbaaa95ca848c/art.hpp#L208)。
本轮 K=64/V=64 的无人工前缀配置约 {median('key_k64', 'unodb_art', 'insert', 'bytes_per_key'):.2f} RSS B/key，
P=56 时约 {median('prefix_p56', 'unodb_art', 'insert', 'bytes_per_key'):.2f} B/key；
这些是当前版本、key policy 和 adapter 的实际测量，不能推广到所有 ART 实现。

`effects.csv` 保存未四舍五入的比值；`analysis_script.py` 保存本文件的生成过程。
''')
print(root / 'diagnostics.md')
