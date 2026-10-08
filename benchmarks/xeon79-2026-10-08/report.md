# memtable-bench：Xeon 6240 / 10.2.12.79 对比结果

运行时间：2026-10-08T13:45:01.787139+08:00 — 2026-10-08T14:02:27.833640+08:00（Asia/Shanghai）。

## 本轮结果

- 单线程 uniform Insert 最高：Wormhole，1.55 Mops/s。
- 单线程 uniform 精确 Get 最高：Wormhole，2.25 Mops/s。
- 有序全量 flush 最高：TLX B+Tree，4.77 Mrows/s。
- 16 线程 80% Get / 20% 新版本 Insert 最高：Wormhole，11.99 Mops/s。
- 插入后 RSS B/key 最低：RocksDB InlineSkipList，116.6 B/key。
- 生命周期测量阶段总和最低：Wormhole，1297.23 ms。

这些结论仅对应当前 adapter、机器和参数。以下所有数值为 5 次运行的中位数；
[Q1,Q3] 是 inclusive 插值的四分位范围，表示本次波动，不是置信区间。

## 机器和方法

| 项目 | 本轮设置 |
| --- | --- |
| 机器 | Intel(R) Xeon(R) Gold 6240 CPU @ 2.60GHz；双路、36 物理核、72 逻辑 CPU |
| 内存 | 约 376 GiB；共享服务器，后台负载未停止 |
| CPU 绑定 | NUMA node 0；逻辑 CPU 2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17，每个来自不同物理核；各线程使用列表前 N 个核 |
| NUMA 内存 | numactl 在进程启动前 membind；harness 再设置每线程策略 |
| 频率 | governor=performance；Turbo disabled=0；未锁定频率 |
| 构建 | g++ (GCC) 11.3.1 20220421 (Red Hat 11.3.1-2)；Release；HOT 使用单独的 AVX2/BMI 等编译选项 |
| 数据规模 | 1,000,000 条初始记录；1,000,000 次读取/混合操作 |
| Key / value | 24 B user key + 9 B sequence/type = 33 B logical key；64 B value |
| MVCC | 开启；读 sequence=1，写唯一新 sequence；不做 snapshot/latest-visible 查找 |
| Stage 1 | 随机排列 Insert、精确 Get；Freeze 后最多 100 行的原生游标 Scan |
| 分布 | uniform 和 Zipf 1.1；Zipf 改变 Get/Scan 起点，不改变随机插入顺序 |
| Stage 2 | 80% Get / 20% 新版本 Insert；线程数 1,2,4,8,16 |
| Stage 3 | Insert → Freeze → 全量有序 Scan/checksum → Destroy |
| 重复和顺序 | seed 42–46；串行新进程；随机交错 scenario 和 adapter；各 adapter 100k-key 预热排除 |
| 延迟 | 每 64 次操作抽样；对各轮分位数取中位数，不合并原始延迟样本 |
| 硬件计数器 | perf_event_open 用户态事件；独立计数器按 enabled/running 时间缩放；缺失保留空值 |

源码目录已同步到 `/DATA/disk1/jinhelin/github/memtable-bench`。
源码 manifest SHA256：`44a678fdfe688be1217c180426593820262569cdd775bfce5a13457016359bfb`；对应本地工作区的未提交 adapter 接入代码。
统一二进制 SHA256：`b5b0f96edccdbdd36bb08982c3f58ddec69fb98099b3633f4ea77d49c927b480`。

## 1. 单线程 uniform

| 实现 | Insert Mops/s [Q1,Q3] | Get Mops/s [Q1,Q3] | 冻结后 Scan Mrows/s | Get p99 µs |
| --- | --- | --- | --- | --- |
| std::map | 0.68 [0.66, 0.68] | 0.66 [0.66, 0.67] | 2.31 [2.31, 2.32] | 2.34 |
| Abseil B-tree | 0.63 [0.62, 0.63] | 0.67 [0.66, 0.68] | 2.75 [2.75, 2.76] | 2.46 |
| TLX B+Tree | 0.49 [0.48, 0.49] | 0.77 [0.76, 0.77] | 4.51 [4.51, 4.52] | 2.08 |
| RocksDB InlineSkipList | 0.80 [0.80, 0.80] | 0.64 [0.64, 0.65] | 4.23 [4.23, 4.23] | 3.45 |
| BTreeOLC | 0.56 [0.56, 0.56] | 0.74 [0.74, 0.76] | 2.80 [2.80, 2.82] | 2.29 |
| UnoDB ART | 1.00 [0.99, 1.00] | 0.98 [0.97, 0.98] | 1.27 [1.27, 1.28] | 1.65 |
| Masstree | 1.18 [1.17, 1.18] | 1.52 [1.51, 1.53] | 2.57 [2.57, 2.57] | 1.12 |
| HOT | 1.05 [1.03, 1.05] | 1.65 [1.61, 1.69] | 2.62 [2.60, 2.62] | 1.04 |
| Wormhole | 1.55 [1.55, 1.55] | 2.25 [2.21, 2.26] | 2.92 [2.92, 2.93] | 0.85 |

Scan 以实际返回行数计算 Mrows/s，每行遍历全部 key/value 字节累积 checksum。
Get 拷贝 64 B value。计时还包括 key 编码、adapter 同步、记录管理和延迟抽样。

### Zipf 热点访问

| 实现 | Zipf Get Mops/s [Q1,Q3] | Scan Mrows/s | Get p99 µs | Get / uniform |
| --- | --- | --- | --- | --- |
| std::map | 1.91 [1.85, 1.93] | 4.81 [4.72, 4.83] | 2.14 | 2.88× |
| Abseil B-tree | 1.89 [1.89, 1.90] | 5.29 [5.24, 5.33] | 2.23 | 2.81× |
| TLX B+Tree | 2.03 [2.03, 2.04] | 6.72 [6.68, 6.72] | 1.89 | 2.65× |
| RocksDB InlineSkipList | 1.90 [1.89, 1.98] | 6.57 [6.51, 6.65] | 2.73 | 2.97× |
| BTreeOLC | 2.12 [2.11, 2.13] | 5.54 [5.53, 5.56] | 1.93 | 2.85× |
| UnoDB ART | 1.92 [1.90, 1.96] | 1.98 [1.98, 2.00] | 1.44 | 1.97× |
| Masstree | 3.81 [3.65, 3.88] | 5.15 [5.07, 5.17] | 0.93 | 2.50× |
| HOT | 3.06 [3.05, 3.10] | 5.03 [5.01, 5.04] | 0.87 | 1.86× |
| Wormhole | 4.01 [3.98, 4.02] | 5.37 [5.30, 5.38] | 0.72 | 1.78× |

### 内存与 adapter 差异

| 实现 | RSS 增量 MiB | RSS B/key | adapter mode | key encoding |
| --- | --- | --- | --- | --- |
| std::map | 228.9 | 240.1 | coarse_rwlock | binary |
| Abseil B-tree | 212.7 | 223.0 | coarse_rwlock | binary |
| TLX B+Tree | 257.8 | 270.3 | coarse_rwlock | binary |
| RocksDB InlineSkipList | 111.2 | 116.6 | native_concurrent_insert | binary |
| BTreeOLC | 235.7 | 247.1 | native_olc_key_stripes | binary |
| UnoDB ART | 531.2 | 557.0 | native_olc_qsbr | nibble_terminated |
| Masstree | 340.7 | 357.2 | native_masstree_deferred_reclaim | binary |
| HOT | 325.8 | 341.6 | coarse_rwlock_hot_singlethreaded | nibble_terminated |
| Wormhole | 145.5 | 152.5 | native_whsafe | binary |

RSS 为进程级、按页统计的插入前后差值；不是精确节点大小。共同逻辑 payload 为 97 B。
UnoDB 和 HOT 存储 nibble 编码 key：33 B 变成 67 B；HOT 另保留原始 key。
额外编码、解码和存储开销计入结果，不能把它们当作同样物理 key 长度的裸索引比较。
BTreeOLC 使用不可变记录、额外查找和 256 个 key 分片锁；Masstree 使用每索引分配上下文、
延迟到 Destroy 回收；HOT 的进程级节点池可以保留内存。上述选择都会影响 RSS 和生命周期。

## 2. 并发扩展性

| 实现 | 1 线程 Mops/s | 2 线程 Mops/s | 4 线程 Mops/s | 8 线程 Mops/s | 16 线程 Mops/s | 16/1 加速比 |
| --- | --- | --- | --- | --- | --- | --- |
| std::map | 0.62 [0.62, 0.62] | 0.37 [0.37, 0.37] | 0.35 [0.35, 0.35] | 0.35 [0.35, 0.35] | 0.34 [0.34, 0.35] | 0.55× |
| Abseil B-tree | 0.59 [0.59, 0.59] | 0.36 [0.36, 0.36] | 0.34 [0.34, 0.34] | 0.34 [0.34, 0.34] | 0.33 [0.33, 0.33] | 0.56× |
| TLX B+Tree | 0.64 [0.63, 0.64] | 0.38 [0.38, 0.38] | 0.35 [0.35, 0.35] | 0.35 [0.35, 0.35] | 0.34 [0.34, 0.35] | 0.54× |
| RocksDB InlineSkipList | 0.61 [0.60, 0.61] | 1.25 [1.21, 1.25] | 2.49 [2.49, 2.53] | 4.89 [4.85, 5.07] | 8.72 [8.71, 9.39] | 14.31× |
| BTreeOLC | 0.63 [0.62, 0.63] | 1.26 [1.25, 1.26] | 2.45 [2.40, 2.47] | 4.76 [4.66, 4.77] | 5.74 [5.69, 5.99] | 9.18× |
| UnoDB ART | 0.94 [0.94, 0.95] | 1.93 [1.89, 1.93] | 3.90 [3.88, 3.93] | 7.39 [7.35, 7.50] | 8.52 [8.50, 8.87] | 9.03× |
| Masstree | 1.03 [1.02, 1.03] | 1.89 [1.87, 1.90] | 3.48 [3.48, 3.52] | 5.71 [5.61, 5.73] | 2.94 [2.84, 3.14] | 2.86× |
| HOT | 1.31 [1.30, 1.31] | 0.52 [0.52, 0.52] | 0.48 [0.48, 0.48] | 0.48 [0.48, 0.48] | 0.48 [0.47, 0.48] | 0.36× |
| Wormhole | 1.59 [1.51, 1.60] | 3.05 [3.04, 3.13] | 5.87 [5.80, 6.03] | 10.41 [10.40, 10.62] | 11.99 [11.86, 12.20] | 7.54× |

| 实现 | 1 线程 p50/p95/p99 µs | 16 线程 p50/p95/p99 µs |
| --- | --- | --- |
| std::map | 1.56 / 2.17 / 3.96 | 2.34 / 266.65 / 745.51 |
| Abseil B-tree | 1.66 / 2.44 / 4.42 | 2.63 / 287.40 / 803.37 |
| TLX B+Tree | 1.44 / 2.56 / 5.47 | 2.17 / 272.17 / 849.46 |
| RocksDB InlineSkipList | 1.55 / 2.83 / 3.93 | 1.56 / 2.69 / 3.79 |
| BTreeOLC | 1.51 / 2.42 / 4.44 | 1.53 / 5.21 / 16.36 |
| UnoDB ART | 1.00 / 1.46 / 3.21 | 1.05 / 2.94 / 10.90 |
| Masstree | 0.73 / 3.17 / 3.82 | 0.84 / 17.42 / 55.31 |
| HOT | 0.67 / 1.16 / 3.09 | 1.12 / 180.00 / 852.65 |
| Wormhole | 0.52 / 0.86 / 2.70 | 0.57 / 1.41 / 10.44 |

std::map、Abseil、TLX 和 HOT 使用整体读写锁；HOT 是 HOTSingleThreaded，未接入 ROWEX。
RocksDB、BTreeOLC、UnoDB、Masstree、Wormhole 采用各自原生并发路径及已标明的 adapter 辅助机制。
这些曲线比较当前接入方式的扩展性。不同线程数会生成相应线程 trace；同一线程数下所有
adapter 的 trace 一致。核固定在同一个 socket，未使用 SMT，但共享服务器仍可能有干扰。

## 3. MemTable 生命周期

| 实现 | Insert ms | Freeze µs | Flush ms | Flush Mrows/s | Destroy ms | 阶段总和 ms |
| --- | --- | --- | --- | --- | --- | --- |
| std::map | 1475.71 | 26.94 | 402.79 | 2.48 [2.48, 2.49] | 280.31 | 2160.36 |
| Abseil B-tree | 1661.40 | 27.36 | 367.20 | 2.72 [2.72, 2.73] | 213.15 | 2240.92 |
| TLX B+Tree | 2034.35 | 27.27 | 209.58 | 4.77 [4.73, 4.77] | 195.67 | 2441.00 |
| RocksDB InlineSkipList | 1239.93 | 26.80 | 222.68 | 4.49 [4.48, 4.50] | 0.23 | 1462.36 |
| BTreeOLC | 1795.17 | 26.79 | 306.74 | 3.26 [3.25, 3.26] | 45.24 | 2146.99 |
| UnoDB ART | 986.55 | 26.44 | 831.85 | 1.20 [1.17, 1.21] | 601.73 | 2434.10 |
| Masstree | 850.39 | 26.06 | 346.49 | 2.89 [2.87, 2.91] | 108.75 | 1305.37 |
| HOT | 947.15 | 26.81 | 341.30 | 2.93 [2.91, 2.94] | 102.31 | 1389.21 |
| Wormhole | 642.76 | 26.46 | 261.38 | 3.83 [3.73, 3.83] | 388.79 | 1297.23 |

Flush 检查严格 key 顺序、精确行数，复制前一条 key 并计算所有字节的 checksum。
它没有写 SSTable、压缩或磁盘 I/O。阶段总和先在每轮求和、再取中位数；不包括索引构造、
trace 准备、CSV 输出和阶段间 RSS 采样。单次 Freeze 很短，perf 启停/read 系统调用和计时
开销可能占主要部分，不按这项作索引排名。释放后 RSS 不一定随 allocator/pool 立即下降。

## 4. 硬件计数器：uniform 精确 Get

| 实现 | cycles/op | instructions/op | IPC | L1D miss/op | LLC miss/op | branch miss/op | DTLB miss/op |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std::map | 4902.746 | 1690.662 | 0.345 | 74.677 | 19.942 | 11.355 | 13.800 |
| Abseil B-tree | 4843.603 | 1839.963 | 0.380 | 99.325 | 22.287 | 11.060 | 24.649 |
| TLX B+Tree | 4256.082 | 2077.522 | 0.488 | 74.977 | 19.729 | 12.286 | 9.463 |
| RocksDB InlineSkipList | 5088.603 | 2730.667 | 0.537 | 93.231 | 8.634 | 8.914 | 24.662 |
| BTreeOLC | 4375.383 | 2057.630 | 0.469 | 99.351 | 20.499 | 11.328 | 22.397 |
| UnoDB ART | 3339.460 | 2675.053 | 0.801 | 23.797 | 6.379 | 0.030 | 3.120 |
| Masstree | 2138.824 | 1195.360 | 0.558 | 29.677 | 5.666 | 11.499 | 3.859 |
| HOT | 1976.025 | 1755.848 | 0.889 | 21.175 | 5.749 | 0.711 | 2.882 |
| Wormhole | 1450.085 | 1542.129 | 1.063 | 18.884 | 2.734 | 1.908 | 3.165 |

这些是每次操作的事件数，不是 cache/branch miss 百分比；没有相应访问总数可用于分母。
IPC 来自 instructions/cycles。各 metric 分别对每轮结果取中位数，因此表中三个中位数
不保证满足精确的除法等式。完整 Insert/Scan/并发计数器均保存在原始和汇总 CSV 中。
缺失字段计数（全部 675 条 phase 记录）：`{"cycles_per_op": 0, "instructions_per_op": 0, "ipc": 0, "l1d_miss_per_op": 0, "llc_miss_per_op": 0, "branch_miss_per_op": 0, "dtlb_miss_per_op": 48}`。

## 可复现性

完成 360 个正式进程、675 条 phase 记录；另有 9 个预热进程。
40 个 scenario/repeat 组合中，全部 9 个 adapter 的操作数、
返回行数和 checksum 一致；所有全量 flush 返回 1,000,000 行且严格有序。
HOT 已在这台 native x86 机器上参与接口测试和全部 benchmark。

起始负载：`9.11 7.66 6.87 4/31032 3302795`；结束负载：`5.42 5.06 5.42 8/31027 3315569`。
没有独占 CPU、关闭后台程序或锁定频率。只测试一组规模、key/value 长度、命中读和 80/20 mix，
结果不代表所有 MemTable workload；也不与此前 M4 测量做直接排名。
Checksum 是辅助核对，不能代替完整的正确性测试。

### 依赖版本

| 依赖 | commit |
| --- | --- |
| abseil-cpp | `76bb24329e8bf5f39704eb10d21b9a80befa7c81` |
| tlx | `b6af589954fafd334f2f373b057a8886e1c6abc8` |
| rocksdb | `ae8fb3e5000e46d8d4c9dbf3a36019c0aaceebff` |
| btreeolc | `74cafa57d74798f209d8fcbce8c4f317ce066eae` |
| unodb | `89f52799743ec2093426bdcf7a7cbaaa95ca848c` |
| masstree | `11198427a1170654ca646dd20d96c8f349bca2bd` |
| hot | `96bf6fb7103b27e50e16a6026db8974c090ee84a` |
| wormhole | `31dfd2b1e67e5f709c78b018cf4abaecadad8b72` |

Boost headers 为 1.86.0。`source-manifest.json`、`build-config.txt`、`build-server.log`
包含源码、构建配置及编译/接口测试证据。上游修改见项目 `cmake/patches/`。

### 文件与重跑

- `raw.csv`：36 列 harness schema + scenario/repeat/seed/run_sequence/process_elapsed_s。
- `summary.csv`：各 metric 的 median/Q1/Q3/min/max 和有效样本数。
- `metadata.json`、`commands.jsonl`：机器、版本、执行顺序、完整命令、负载和退出码。
- `runs/`：每个进程的 CSV 和日志；预热有明确标记。
- `comparison.png` / `comparison.svg`：结果图，误差线/色带为 Q1–Q3。

在服务器项目目录重跑，输出必须指定新的目录：

```sh
python3 scripts/benchmark_matrix.py --binary build-linux/memtable_bench \
  --output results/new-run --cpus 2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17 --numa-node 0 \
  --keys 1000000 --ops 1000000 --repeats 5 --threads 1,2,4,8,16
python3 scripts/summarize_benchmark.py results/new-run
```

## 构建及计数器说明

构建时禁用了代理，未执行格式化目标；修复 NUMA syscall 后，绑定 node 0 的测试再次 10/10 通过。详见 [run-notes.md](run-notes.md) 和 `numa-rebuild-tests.log`。L1D/LLC/DTLB 使用通用 read-miss 事件，DTLB 空值仅出现在短阶段：{"freeze": 45, "destroy": 3}。TLX 的 tag 对象与实际 commit 的对应关系、测量源码快照说明也记录在 run-notes 中。
