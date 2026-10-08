#!/usr/bin/env python3
"""Validate completed sensitivity runs; export statistics and a Chinese report."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics

from summarize_benchmark import LABEL, METRICS

METRICS = dict(METRICS, payload_gb_s='logical GB/s')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    root = parser.parse_args().directory.resolve()
    meta = json.loads((root/'metadata.json').read_text())
    assert meta['status']=='complete' and meta['completed_processes']==meta['planned_processes']
    with (root/'raw.csv').open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    phase_count={1:3 if meta['suite']=='range-scan' else 5,2:1,3:5}
    assert len(rows)==len(meta['configs'])*len(meta['indexes'])*meta['repeats']*sum(
        phase_count[w[1]] for w in meta['workloads'])
    groups, checks, datasets = defaultdict(list), defaultdict(list), {}
    for row in rows:
        assert row['schema_version']=='3' and row['key_preparation']=='precomputed'
        groups[(row['config_id'],row['scenario'],row['phase'],row['index'])].append(row)
        checks[(row['config_id'],row['scenario'],row['phase'],row['repeat'])].append(
            tuple(row[f] for f in ('ops','items_scanned','checksum','dataset_hash')))
    assert all(len(group)==meta['repeats'] for group in groups.values())
    assert all(len(group)==len(meta['indexes']) and len(set(group))==1 for group in checks.values())
    for path in sorted((root/'runs').glob('*-dataset.json')):
        info=json.loads(path.read_text())
        if '-warmup-' in path.name:
            continue
        identity=(info['layout'],info['user_key_bytes'],info['prefix_bytes'],info['prefix_groups'],info['seed'])
        if identity in datasets:
            assert datasets[identity]==info
        datasets[identity]=info
        assert sum(info['lcp_histogram'])==meta['keys']-1
    stats={}
    for key,samples in groups.items():
        for metric in METRICS:
            values=[float(row[metric]) for row in samples if row[metric]!='']
            if not values:
                continue
            q1,_,q3=statistics.quantiles(values,n=4,method='inclusive') if len(values)>1 else [values[0]]*3
            stats[(*key,metric)]=dict(samples=len(values),median=statistics.median(values),
                                     q1=q1,q3=q3,min=min(values),max=max(values))
    with (root/'summary.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['config_id','scenario','phase','index','metric','unit',
                                                'samples','median','q1','q3','min','max'])
        writer.writeheader()
        for (config,scenario,phase,index,metric),values in sorted(stats.items()):
            writer.writerow(dict(config_id=config,scenario=scenario,phase=phase,index=index,
                                 metric=metric,unit=METRICS[metric],**values))
    with (root/'dataset-summary.csv').open('w',newline='') as stream:
        fields=['layout','user_key_bytes','prefix_bytes','prefix_groups','seed','keys','logical_key_bytes',
                'dataset_hash_fnv1a64','lcp_pairs','lcp_min','lcp_p50','lcp_p95','lcp_p99','lcp_max','lcp_mean']
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for _,info in sorted(datasets.items()):
            writer.writerow({f:info[f] for f in fields})

    def med(config,index,phase='lookup_only',metric='throughput_ops_s',scenario='single_uniform'):
        return stats[(config,scenario,phase,index,metric)]['median']

    def cell(config,index,phase='lookup_only',metric='throughput_ops_s',scale=1e6,scenario='single_uniform'):
        key=(config,scenario,phase,index,metric)
        if key not in stats:
            return '—'
        value=stats[key]
        return f"{value['median']/scale:.2f} [{value['q1']/scale:.2f}, {value['q3']/scale:.2f}]"

    def table(header,data):
        return '\n'.join(['| '+' | '.join(header)+' |','| '+' | '.join(['---']*len(header))+' |',
                          *['| '+' | '.join(map(str,r))+' |' for r in data]])

    indexes=meta['indexes']
    configs={c['config_id']:c for c in meta['configs']}
    sections=[]
    if meta['suite']=='screening':
        key_configs=[f'key_k{k}' for k in (8,16,32,64,112) if f'key_k{k}' in configs]
        prefix_configs=[c for c in ('key_k64','prefix_p8','prefix_p24','prefix_p56') if c in configs]
        value_configs=[c for c in ('value_v8','key_k64','value_v1024') if c in configs]
        if key_configs:
            sections.append('## Key 长度：LookupOnly Mops/s\n\n'+table(
                ['实现',*[str(configs[c]['key_size'])+' B' for c in key_configs]],
                [[LABEL[i],*[cell(c,i) for c in key_configs]] for i in indexes]))
        if prefix_configs:
            sections.append('## 公共前缀：固定 64 B user key，LookupOnly Mops/s\n\n'+table(
                ['实现',*[str(configs[c]['prefix_bytes'])+' B 前缀' for c in prefix_configs]],
                [[LABEL[i],*[cell(c,i) for c in prefix_configs]] for i in indexes]))
        if value_configs:
            for phase,title in [('lookup_only','LookupOnly Mops/s'),('get','GetCopy Mops/s'),
                                ('scan_iterate','游标遍历 Mrows/s'),('scan','完整 payload 扫描 Mrows/s')]:
                metric='items_per_s' if phase.startswith('scan') else 'throughput_ops_s'
                sections.append('## Value 大小：'+title+'\n\n'+table(
                    ['实现',*[str(configs[c]['value_size'])+' B value' for c in value_configs]],
                    [[LABEL[i],*[cell(c,i,phase,metric) for c in value_configs]] for i in indexes]))
            sections.append('## Value 拷贝：GetCopy 逻辑 GB/s\n\n'+table(
                ['实现',*[str(configs[c]['value_size'])+' B value' for c in value_configs]],
                [[LABEL[i],*[cell(c,i,'get','payload_gb_s',1) for c in value_configs]] for i in indexes]))
        grouped=[c for c in ('key_k64','prefix_p24','groups_g16','groups_g1024') if c in configs]
        if grouped:
            sections.append('## 前缀分组：LookupOnly Mops/s\n\n'+table(
                ['实现',*grouped],[[LABEL[i],*[cell(c,i) for c in grouped]] for i in indexes]))
        interactions=[c for c in configs if c.startswith('interaction_')]
        if interactions:
            sections.append('## 交互配置：LookupOnly Mops/s\n\n'+table(
                ['实现',*[c.removeprefix('interaction_') for c in interactions]],
                [[LABEL[i],*[cell(c,i) for c in interactions]] for i in indexes]))
        # Ratio of ratios: positive values mean the length penalty decreases
        # with a shared prefix. This is a descriptive effect, not a p-value.
        if len(interactions)==8:
            effects=[]
            for index in indexes:
                row=[LABEL[index]]
                for value in (8,1024):
                    def rate(k,p):
                        return med(f'interaction_k{k}_p{p}_v{value}',index)
                    ratio=(rate(112,24)/rate(32,24))/(rate(112,0)/rate(32,0))
                    row.append(f'{ratio:.3f}×')
                effects.append(row)
            sections.append('## Key 长度 × 前缀的描述性交互\n\n'+table(
                ['实现','8 B value','1024 B value'],effects)+
                '\n\n计算 `(T112,P24 / T32,P24) / (T112,P0 / T32,P0)`，T 为 LookupOnly 吞吐中位数。'
                '大于 1 表示此处长 key 的相对性能随公共前缀改善；小于 1 表示相反。'
                '这是局部 ratio-of-ratios，不是显著性检验或全局模型。')
    elif meta['suite']=='range-scan':
        for layout in ('random','global-prefix'):
            selected=sorted((c for c in configs.values() if c['key_layout']==layout),
                            key=lambda c:c['scan_length'])
            if not selected:
                continue
            for phase,title,metric,scale in [
                ('seek_only','SeekOnly Mops/s','throughput_ops_s',1e6),
                ('scan_iterate','游标遍历 Mrows/s','items_per_s',1e6),
                ('scan','完整 payload 扫描 Mrows/s','items_per_s',1e6),
                ('scan','完整 scan 调用 p99 µs','latency_p99_ns',1e3)]:
                sections.append('## '+layout+'：'+title+'\n\n'+table(
                    ['实现',*[str(c['scan_length'])+' 条上限' for c in selected]],
                    [[LABEL[i],*[cell(c['config_id'],i,phase,metric,scale,scenario='range_uniform')
                                 for c in selected]] for i in indexes]))
            actual_rows=[]
            for config in selected:
                sample=next(r for r in rows if r['config_id']==config['config_id'] and
                            r['phase']=='scan' and r['repeat']=='1')
                count=int(sample['items_scanned'])
                actual_rows.append([str(config['scan_length']),str(meta['scan_calls']),str(count),
                                    f"{count/meta['scan_calls']:.2f}"])
            sections.append('## '+layout+'：实际返回行数（seed 42）\n\n'+table(
                ['条数上限','scan 调用数','实际 rows','平均 rows/call'],
                actual_rows))
        sections.append('## Range scan 解释\n\n'
                        f"每个配置 {meta['scan_calls']:,} 次调用；同一个 seed/layout 的不同长度使用相同起点序列。"
                        '条数是最大上限，接近表尾时实际返回更少，吞吐使用真实 rows。\n\n'
                        'SeekOnly 包括 NewCursor、Seek 和 bounded key 消费；游标与完整扫描也包括 Seek。'
                        '不把两项时间相减解释为纯 Next 成本。完整扫描读取并 checksum 全部 key/value，未写磁盘。'
                        '\n\n这些是 Freeze 后的只读扫描；未实现显式 end-key、并发 scan/write 或 snapshot-visible 去重。'
                        '扫描延迟每 64 次调用采样一次；少量调用的 p99 不足以判断尾延迟。')
    else:
        for config in configs:
            mixed=[w for w in meta['workloads'] if w[1]==2]
            sections.append('## '+config+'：并发混合吞吐 Mops/s\n\n'+table(
                ['实现',*[str(w[2])+' 线程' for w in mixed]],
                [[LABEL[i],*[cell(config,i,'mixed',scenario=w[0]) for w in mixed]] for i in indexes]))
            sections.append('## '+config+'：生命周期阶段耗时 ms\n\n'+table(
                ['实现','Insert','Freeze','游标遍历','完整 Flush','Destroy'],
                [[LABEL[i],*[cell(config,i,p,'elapsed_ns',scenario='lifecycle_uniform')
                             for p in ('insert','freeze','ordered_traverse','ordered_flush','destroy')]]
                 for i in indexes]))
    missing={metric:sum(r[metric]=='' for r in rows) for metric in
             ('cycles_per_op','instructions_per_op','ipc','l1d_miss_per_op','llc_miss_per_op',
              'branch_miss_per_op','dtlb_miss_per_op')}
    factor_rows=[]
    for c in configs.values():
        example=next(r for r in rows if r['config_id']==c['config_id'] and r['repeat']=='1')
        factor_rows.append([c['config_id'],c['key_size'],c['value_size'],c['key_layout'],
                            c['prefix_bytes'],c['prefix_groups'],example['lcp_p50'],example['lcp_p95'],
                            example['lcp_p99']])
    phase_order=('Prefill → Freeze → 完整校验 → SeekOnly → 游标遍历 → payload 扫描'
                 if meta['suite']=='range-scan' else
                 'LookupOnly → GetCopy → 完整校验 → 游标遍历 → payload 扫描')
    scale_description=(f"{meta['keys']:,} 条、每配置 {meta['scan_calls']:,} 次 scan 调用"
                       if meta['suite']=='range-scan' else f"{meta['keys']:,} 条、{meta['ops']:,} 次操作")
    lookup_description=('SeekOnly 测量 NewCursor + Seek，消费 key 的长度/首字节，不调用 Next 或复制 value。'
                        if meta['suite']=='range-scan' else
                        'LookupOnly 使用原生存在性查询，不拷贝 value。GetCopy 返回 owned string，包含分配和 value 拷贝。')
    report=f'''# memtable-bench：{'Range scan 长度实验' if meta['suite']=='range-scan' else 'Key / 前缀 / Value 敏感性实验'}

Suite：`{meta['suite']}`；时间：{meta['started_at']} — {meta['finished_at']}。
完成 {meta['completed_processes']} 个正式进程、{len(rows)} 条 phase 记录；每组 {meta['repeats']} 次重复。
{meta['checksum_groups_verified']} 个配置/workload/repeat 组合的全部 adapter checksum、操作数和行数一致。
表中数值为中位数 [Q1,Q3]；四分位范围描述波动，不是置信区间。

## 方法

- 规模：{scale_description}；InternalKey 开启，user key 后附 9 B sequence/type。
- 输入 key 使用连续缓冲区预生成，计时外完成排序、LCP、访问 trace；MVCC 新版本写入 key 也在计时外准备。
- 随机字节 key 的首 8 个后缀字节是 uint64 ID 的可逆置换，保证唯一，避免递增 ID 的人工零前缀。
- 分组公共前缀按 ID modulo groups 均衡分组，不同组的前 8 个前缀字节唯一；组内后缀保持唯一。
- 热点 spread 使用独立随机 ID 排列，clustered 使用字典序 rank；插入顺序独立选择。本轮配置均为随机插入和 uniform 命中读。
- {lookup_description}
- 游标测量只消费行数、key 长度及首字节；各 adapter 自身的解码/游标开销仍保留。完整扫描哈希全部 key/value 字节。
- 完整冻结内容校验在游标计时前执行。固定阶段顺序为 {phase_order}，属于预热后的测量。
- RSS 是预生成输入之后、索引构造前到各阶段结束的进程 RSS 增量；输入缓冲区不计入增量但占用内存并参与 cache 流量。
- GetCopy GB/s 仅按复制的 value 字节计算；Insert/完整 Scan 按逻辑 key+value 字节计算，不是物理内存带宽。游标/LookupOnly 不给 GB/s。
- ART/HOT nibble key 为 `2*(user key+9)+1` B，改变长度和分支字母表；成本保留在 adapter 中。HOT 为粗粒度读写锁 SingleThreaded。
- NUMA node {meta['numa_node']}，CPU {','.join(map(str,meta['selected_cpus']))}，不同物理核；governor={meta['cpu_governor']}，Turbo disabled={meta['turbo_disabled']}。
- 共享服务器，无频率锁定或 CPU 独占。起始负载 `{meta['load_before']}`；结束负载 `{meta['load_after']}`。
- 编译器：{meta['compiler']}。二进制 SHA256：`{meta['binary_sha256']}`。

## 配置与实际 LCP

{table(['配置','User K B','V B','布局','P B','groups','LCP p50','p95','p99'],factor_rows)}

LCP 统计的是排序后相邻不同 user key，排除 MVCC trailer；分组之间的低 LCP 也计入。
`dataset-summary.csv` 保留每个 seed 的统计，`runs/*-dataset.json` 保存完整 histogram。

{chr(10).join(chr(10)+section+chr(10) for section in sections)}

## 完整数据与边界

- `raw.csv`：55 列 harness v3 + config_id/scenario/repeat/seed/run_sequence/process_elapsed_s。
- `summary.csv`：本 suite 各阶段的吞吐、延迟、RSS、CPU/cache 事件统计。
- 硬件计数器空值数：`{json.dumps(missing)}`；空值不作为零。L1D/LLC/DTLB 是通用 read-miss 事件。
- `metadata.json`、`commands.jsonl`、`build-config.txt`、`source-manifest.json` 和 `runs/` 保留复现材料。
- 不与上一轮 inline 生成、递增 ID key 的结果直接比较；输入结构、计时边界和预热顺序已改变。
- 本轮固定记录数；固定 MemTable 内存预算、外置 value handle、长 key 扩展组尚未实现。
- 不做 snapshot-visible Get、SSTable 压缩或磁盘 I/O；hash 一致性不能替代正确性测试。
'''
    (root/'report.md').write_text(report)
    print(f'Validated {len(rows)} rows; {len(stats)} summaries; {len(datasets)} distinct datasets: {root/"report.md"}')


if __name__=='__main__':
    main()
