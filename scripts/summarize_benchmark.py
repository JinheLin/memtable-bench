#!/usr/bin/env python3
"""Validate a completed matrix and produce median/IQR CSV and Markdown report."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics

from adapter_policy import ARCHIVED_NATIVE_CONCURRENT as NATIVE_CONCURRENT, select_rows, validate_rows

LABEL = {'std_map': 'std::map', 'abseil_btree': 'Abseil B-tree', 'tlx_btree': 'TLX B+Tree',
         'rocksdb_inlineskiplist': 'RocksDB InlineSkipList', 'btreeolc': 'BTreeOLC',
         'unodb_art': 'UnoDB ART', 'masstree': 'Masstree', 'hot': 'HOT', 'wormhole': 'Wormhole'}
METRICS = {'throughput_ops_s': 'operations/s', 'items_per_s': 'rows/s', 'elapsed_ns': 'ns',
           'latency_p50_ns': 'ns', 'latency_p95_ns': 'ns', 'latency_p99_ns': 'ns',
           'rss_delta_bytes': 'bytes', 'bytes_per_key': 'bytes/key',
           'cycles_per_op': 'cycles/op', 'instructions_per_op': 'instructions/op', 'ipc': 'instructions/cycle',
           'l1d_miss_per_op': 'misses/op', 'llc_miss_per_op': 'misses/op',
           'branch_miss_per_op': 'misses/op', 'dtlb_miss_per_op': 'misses/op'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path, help='Write a derived view without changing the measured archive')
    args = parser.parse_args()
    root = args.directory.resolve()
    destination = args.output.resolve() if args.output else root
    meta = json.loads((root / 'metadata.json').read_text())
    assert meta['status'] == 'complete' and meta['completed_processes'] == meta['planned_processes'], meta['status']
    indexes = meta['indexes']
    repeats = meta['repeats']
    with (root / 'raw.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    workloads = [(s[0], s[1], s[3]) for s in meta['scenarios']]
    validate_rows(meta, rows, workloads, {1: ['insert', 'get', 'scan'], 2: ['mixed'],
                                        3: ['insert', 'freeze', 'ordered_flush', 'destroy']})
    rows, excluded, selection = select_rows(rows, root, destination)
    groups = defaultdict(list)
    for row in rows:
        groups[(row['scenario'], row['phase'], row['index'])].append(row)
    native_indexes = [index for index in indexes if index in NATIVE_CONCURRENT]
    stats = {}

    def describe(values):
        q1, _, q3 = statistics.quantiles(values, n=4, method='inclusive') if len(values) > 1 else [values[0]] * 3
        return dict(samples=len(values), median=statistics.median(values), q1=q1, q3=q3,
                    min=min(values), max=max(values))

    for key, samples in groups.items():
        for metric in METRICS:
            values = [float(row[metric]) for row in samples if row[metric] != '']
            if values:
                stats[(*key, metric)] = describe(values)
    for index in indexes:
        totals = []
        for repeat in range(1, repeats + 1):
            phases = [r for r in rows if r['scenario'] == 'lifecycle_uniform' and
                      r['index'] == index and int(r['repeat']) == repeat]
            assert len(phases) == 4
            totals.append(sum(float(r['elapsed_ns']) for r in phases))
        stats[('lifecycle_uniform', 'measured_phase_sum', index, 'elapsed_ns')] = describe(totals)
    with (destination / 'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['scenario', 'phase', 'index', 'metric', 'unit',
                                                    'samples', 'median', 'q1', 'q3', 'min', 'max'])
        writer.writeheader()
        for (scenario, phase, index, metric), values in sorted(stats.items()):
            writer.writerow(dict(scenario=scenario, phase=phase, index=index, metric=metric,
                                 unit=METRICS[metric], **values))

    def med(scenario, phase, index, metric='throughput_ops_s'):
        return stats[(scenario, phase, index, metric)]['median']

    def value(scenario, phase, index, metric='throughput_ops_s', scale=1e6, digits=2):
        if (scenario, phase, index, metric) not in stats:
            return '—'
        return f'{med(scenario, phase, index, metric) / scale:.{digits}f}'

    def rate(scenario, phase, index, metric='throughput_ops_s', scale=1e6):
        row = stats[(scenario, phase, index, metric)]
        return f"{row['median']/scale:.2f} [{row['q1']/scale:.2f}, {row['q3']/scale:.2f}]"

    def table(header, values):
        return '\n'.join(['| ' + ' | '.join(header) + ' |',
                          '| ' + ' | '.join(['---'] * len(header)) + ' |',
                          *['| ' + ' | '.join(map(str, row)) + ' |' for row in values]])

    threads = [s[3] for s in meta['scenarios'] if s[1] == 2]
    maximum = max(threads)
    best_get = max(indexes, key=lambda i: med('single_uniform', 'get', i))
    best_insert = max(indexes, key=lambda i: med('single_uniform', 'insert', i))
    best_mix = max(native_indexes, key=lambda i: med(f'mixed_t{maximum}', 'mixed', i))
    best_flush = max(indexes, key=lambda i: med('lifecycle_uniform', 'ordered_flush', i, 'items_per_s'))
    least_rss = min(indexes, key=lambda i: med('single_uniform', 'insert', i, 'bytes_per_key'))
    least_life = min(indexes, key=lambda i: med('lifecycle_uniform', 'measured_phase_sum', i, 'elapsed_ns'))
    single = table(['实现', 'Insert Mops/s [Q1,Q3]', 'Get Mops/s [Q1,Q3]', '冻结后 Scan Mrows/s', 'Get p99 µs'],
                   [[LABEL[i], rate('single_uniform', 'insert', i), rate('single_uniform', 'get', i),
                     rate('single_uniform', 'scan', i, 'items_per_s'),
                     value('single_uniform', 'get', i, 'latency_p99_ns', 1000)] for i in indexes])
    zipf = table(['实现', 'Zipf Get Mops/s [Q1,Q3]', 'Scan Mrows/s', 'Get p99 µs', 'Get / uniform'],
                 [[LABEL[i], rate('single_zipf', 'get', i), rate('single_zipf', 'scan', i, 'items_per_s'),
                   value('single_zipf', 'get', i, 'latency_p99_ns', 1000),
                   f"{med('single_zipf', 'get', i)/med('single_uniform', 'get', i):.2f}×"] for i in indexes])
    single_mixed = table(['实现', '单线程 mixed Mops/s [Q1,Q3]'],
                         [[LABEL[i], rate('mixed_t1', 'mixed', i)] for i in indexes])
    concurrent = table(['实现', *[f'{t} 线程 Mops/s' for t in threads], f'{maximum}/1 加速比'],
                       [[LABEL[i], *[rate(f'mixed_t{t}', 'mixed', i) for t in threads],
                         f"{med(f'mixed_t{maximum}', 'mixed', i)/med('mixed_t1', 'mixed', i):.2f}×"] for i in native_indexes])
    memory = table(['实现', 'RSS 增量 MiB', 'RSS B/key', 'adapter mode', 'key encoding'],
                   [[LABEL[i], value('single_uniform', 'insert', i, 'rss_delta_bytes', 2**20, 1),
                     value('single_uniform', 'insert', i, 'bytes_per_key', 1, 1),
                     groups[('single_uniform', 'insert', i)][0]['adapter_mode'],
                     groups[('single_uniform', 'insert', i)][0]['adapter_key_encoding']] for i in indexes])
    lifecycle = table(['实现', 'Insert ms', 'Freeze µs', 'Flush ms', 'Flush Mrows/s', 'Destroy ms', '阶段总和 ms'],
                      [[LABEL[i], value('lifecycle_uniform', 'insert', i, 'elapsed_ns'),
                        value('lifecycle_uniform', 'freeze', i, 'elapsed_ns', 1000),
                        value('lifecycle_uniform', 'ordered_flush', i, 'elapsed_ns'),
                        rate('lifecycle_uniform', 'ordered_flush', i, 'items_per_s'),
                        value('lifecycle_uniform', 'destroy', i, 'elapsed_ns'),
                        value('lifecycle_uniform', 'measured_phase_sum', i, 'elapsed_ns')] for i in indexes])
    counter_table = table(['实现', 'cycles/op', 'instructions/op', 'IPC', 'L1D miss/op', 'LLC miss/op',
                           'branch miss/op', 'DTLB miss/op'],
                          [[LABEL[i], *[value('single_uniform', 'get', i, metric, 1, 3)
                                        for metric in ('cycles_per_op', 'instructions_per_op', 'ipc',
                                                       'l1d_miss_per_op', 'llc_miss_per_op',
                                                       'branch_miss_per_op', 'dtlb_miss_per_op')]] for i in indexes])
    latency = table(['实现', '1 线程 p50/p95/p99 µs', f'{maximum} 线程 p50/p95/p99 µs'],
                    [[LABEL[i], *[' / '.join(value(f'mixed_t{t}', 'mixed', i, f'latency_{p}_ns', 1000)
                                             for p in ('p50', 'p95', 'p99')) for t in (1, maximum)]] for i in native_indexes])
    missing_counters = {metric: sum(r[metric] == '' for r in rows) for metric in
                        ('cycles_per_op', 'instructions_per_op', 'ipc', 'l1d_miss_per_op',
                         'llc_miss_per_op', 'branch_miss_per_op', 'dtlb_miss_per_op')}
    pins = table(['依赖', 'commit'], [[name, '`' + pin + '`'] for name, pin in meta['dependencies'].items()])
    cpu_name = next(line.split(':', 1)[1].strip() for line in meta['cpu_topology'].splitlines()
                    if line.startswith('Model name:'))
    source_id = meta['source']['source_sha256'] if meta.get('source') else 'not recorded'
    harness_columns = len(rows[0]) - 5
    report = f'''# memtable-bench：Xeon 6240 / 10.2.12.79 对比结果

运行时间：{meta['started_at']} — {meta['finished_at']}（Asia/Shanghai）。

## 本轮结果

- 单线程 uniform Insert 最高：{LABEL[best_insert]}，{value('single_uniform', 'insert', best_insert)} Mops/s。
- 单线程 uniform 精确 Get 最高：{LABEL[best_get]}，{value('single_uniform', 'get', best_get)} Mops/s。
- 有序全量 flush 最高：{LABEL[best_flush]}，{value('lifecycle_uniform', 'ordered_flush', best_flush, 'items_per_s')} Mrows/s。
- {maximum} 线程 80% Get / 20% 新版本 Insert 最高：{LABEL[best_mix]}，{value(f'mixed_t{maximum}', 'mixed', best_mix)} Mops/s。
- 插入后 RSS B/key 最低：{LABEL[least_rss]}，{value('single_uniform', 'insert', least_rss, 'bytes_per_key', 1, 1)} B/key。
- 生命周期测量阶段总和最低：{LABEL[least_life]}，{value('lifecycle_uniform', 'measured_phase_sum', least_life, 'elapsed_ns')} ms。

这些结论仅对应当前 adapter、机器和参数。以下所有数值为 {repeats} 次运行的中位数；
[Q1,Q3] 是 inclusive 插值的四分位范围，表示本次波动，不是置信区间。

## 机器和方法

| 项目 | 本轮设置 |
| --- | --- |
| 机器 | {cpu_name}；双路、36 物理核、72 逻辑 CPU |
| 内存 | 约 376 GiB；共享服务器，后台负载未停止 |
| CPU 绑定 | NUMA node {meta['numa_node']}；逻辑 CPU {','.join(map(str, meta['selected_cpus']))}，每个来自不同物理核；各线程使用列表前 N 个核 |
| NUMA 内存 | numactl 在进程启动前 membind；harness 再设置每线程策略 |
| 频率 | governor={meta['cpu_governor']}；Turbo disabled={meta['turbo_disabled']}；未锁定频率 |
| 构建 | {meta['compiler']}；Release；各依赖的 ISA 选项保存在测量构建配置中 |
| 数据规模 | {meta['keys']:,} 条初始记录；{meta['ops']:,} 次读取/混合操作 |
| Key / value | 24 B user key + 9 B sequence/type = 33 B logical key；64 B value |
| MVCC | 开启；读 sequence=1，写唯一新 sequence；不做 snapshot/latest-visible 查找 |
| Stage 1 | 随机排列 Insert、精确 Get；Freeze 后最多 100 行的原生游标 Scan |
| 分布 | uniform 和 Zipf 1.1；Zipf 改变 Get/Scan 起点，不改变随机插入顺序 |
| Stage 2 | 80% Get / 20% 新版本 Insert；线程数 {','.join(map(str, threads))} |
| Stage 3 | Insert → Freeze → 全量有序 Scan/checksum → Destroy |
| 重复和顺序 | seed 42–{41+repeats}；串行新进程；随机交错 scenario 和 adapter；各 adapter 100k-key 预热排除 |
| 延迟 | 每 64 次操作抽样；对各轮分位数取中位数，不合并原始延迟样本 |
| 硬件计数器 | perf_event_open 用户态事件；独立计数器按 enabled/running 时间缩放；缺失保留空值 |

源码目录已同步到 `/DATA/disk1/jinhelin/github/memtable-bench`。
源码 manifest SHA256：`{source_id}`；对应本轮实际测量时保存的源码快照。
统一二进制 SHA256：`{meta['binary_sha256']}`。

## 1. 单线程 uniform

{single}

Scan 以实际返回行数计算 Mrows/s，每行遍历全部 key/value 字节累积 checksum。
Get 拷贝 64 B value。计时还包括 key 编码、adapter 同步、记录管理和延迟抽样。

### Zipf 热点访问

{zipf}

### 内存与 adapter 差异

{memory}

RSS 为进程级、按页统计的插入前后差值；不是精确节点大小。共同逻辑 payload 为 97 B。
UnoDB 的 nibble 编码将 33 B logical key 变成 67 B；历史 HOT adapter 也使用该编码。
额外编码、解码和存储开销计入结果，不能把它们当作同样物理 key 长度的裸索引比较。
BTreeOLC 使用不可变记录、额外查找和 256 个 key 分片锁。历史 Masstree/HOT 的
分配与回收范围见对应源码快照。同步、所有权和回收选择都会影响 RSS 和生命周期。

## 2. 混合 workload

### 单线程：全部实现

{single_mixed}

### 原生并发实现的扩展性

{concurrent}

{latency}

本轮多线程候选：{', '.join(LABEL[i] for i in native_indexes)}。候选资格取决于
实际接入实现的原生并发能力。历史 wrapper 多线程记录单独列入 `excluded.csv`。
这些曲线比较当前接入方式的扩展性。不同线程数会生成相应线程 trace；同一线程数下所有
adapter 的 trace 一致。核固定在同一个 socket，未使用 SMT，但共享服务器仍可能有干扰。

## 3. MemTable 生命周期

{lifecycle}

Flush 检查严格 key 顺序、精确行数，复制前一条 key 并计算所有字节的 checksum。
它没有写 SSTable、压缩或磁盘 I/O。阶段总和先在每轮求和、再取中位数；不包括索引构造、
trace 准备、CSV 输出和阶段间 RSS 采样。单次 Freeze 很短，perf 启停/read 系统调用和计时
开销可能占主要部分，不按这项作索引排名。释放后 RSS 不一定随 allocator/pool 立即下降。

## 4. 硬件计数器：uniform 精确 Get

{counter_table}

这些是每次操作的事件数，不是 cache/branch miss 百分比；没有相应访问总数可用于分母。
IPC 来自 instructions/cycles。各 metric 分别对每轮结果取中位数，因此表中三个中位数
不保证满足精确的除法等式。完整 Insert/Scan/并发计数器均保存在原始和汇总 CSV 中。
缺失字段计数（纳入的 {len(rows)} 条 phase 记录）：`{json.dumps(missing_counters)}`。

## 可复现性

原始测量完成 {meta['completed_processes']} 个正式进程；另有 {len(indexes)} 个预热进程。
本报告纳入 {selection['included_processes']} 个进程、{len(rows)} 条 phase 记录；
排除 {selection['excluded_processes']} 个 wrapper 多线程进程、{len(excluded)} 条记录。
所有原始记录先核对完整性和同场景 checksum，再按 `native-concurrency-v1` 选择。
单线程场景覆盖全部 {len(indexes)} 个 adapter，多线程场景只覆盖原生并发 adapter。
所有全量 flush 返回 {meta['keys']:,} 行且严格有序。

`selection.json` 保存原始 raw.csv 的 SHA256、来源和纳入/排除计数。
本报告是对已有测量的重整，没有重新运行性能测量；Wormhole 的源码版本以原始快照为准。

起始负载：`{meta['load_before']}`；结束负载：`{meta['load_after']}`。
没有独占 CPU、关闭后台程序或锁定频率。只测试一组规模、key/value 长度、命中读和 80/20 mix，
结果不代表所有 MemTable workload；也不与此前 M4 测量做直接排名。
Checksum 是辅助核对，不能代替完整的正确性测试。

### 依赖版本

{pins}

Boost headers 为 1.86.0。`source-manifest.json`、`build-config.txt`、`build-server.log`
包含源码、构建配置及编译/接口测试证据。上游修改见项目 `cmake/patches/`。

### 文件与重跑

- 原始 `raw.csv`：{harness_columns} 列 harness schema + scenario/repeat/seed/run_sequence/process_elapsed_s。
- `summary.csv`：各 metric 的 median/Q1/Q3/min/max 和有效样本数。
- `metadata.json`、`commands.jsonl`：机器、版本、执行顺序、完整命令、负载和退出码。
- `runs/`：每个进程的 CSV 和日志；预热有明确标记。
- `comparison.png` / `comparison.svg`：结果图，误差线/色带为 Q1–Q3。

在服务器项目目录重跑，输出必须指定新的目录：

```sh
python3 scripts/benchmark_matrix.py --binary build-linux/memtable_bench \\
  --output results/new-run --cpus {','.join(map(str, meta['selected_cpus']))} --numa-node {meta['numa_node']} \\
  --keys {meta['keys']} --ops {meta['ops']} --repeats {repeats} --threads {','.join(map(str, threads))}
python3 scripts/summarize_benchmark.py results/new-run
```
'''
    (destination / 'report.md').write_text(report)
    print(f'Validated {len(rows)} phase rows; {len(stats)} metric summaries; report: {destination / "report.md"}')


if __name__ == '__main__':
    main()
