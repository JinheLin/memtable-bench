# 索引精简决策（2026-10-09）

当前保留 **5 项**，以 **RocksDB InlineSkipList** 作为默认性能基准。
筛选依据是数据结构代表性、原生并发能力、MVCC 适配范围和维护成本。
数据来自[精简前的正式 MVCC 实验](../benchmarks/mvcc-formal-1m-2026-10-08/README.md)，
下面的性能数字均为基础组的三次重复中位数。

## 保留哪些，以及理由

| 索引 | 保留理由 |
| --- | --- |
| RocksDB InlineSkipList | 成熟的生产级 LSM MemTable 参照；支持原生并发插入，适配 append-only InternalKey；历史扫描和完整版本 flush 表现较好，基础组 RSS 约 78.7 B/version。作为默认索引和比较基准。 |
| BTreeOLC | 保留原生并发 B-tree，覆盖树索引的页组织、OLC 和 cache 行为。其 adapter 的记录所有权和分片锁成本继续纳入测量。 |
| UnoDB ART | 保留原生并发 ART，覆盖 radix 结构；基础组加载约 1.053 Mversions/s、历史点查约 0.630 Mrequests/s。继续记录 nibble 编码与 QSBR 成本。 |
| Wormhole | 保留另一种有序索引方案；基础组加载约 1.032 Mversions/s、RSS 约 111.5 B/version，提供不同于树和 SkipList 的权衡。 |
| CSE Crossbeam | 保留实际 CSE 默认 MemTable 的原生用户 key 版本链、历史可见性、seal 和 flush 迭代器；可完成所有四种百万用户 key 配置。原生 batch writer 内部串行，当前测量为 SWMR。 |

## 删除哪些，以及理由和取舍

| 删除项 | 理由 | 放弃的对照 |
| --- | --- | --- |
| std::map | InlineSkipList 已能承担性能基准和默认运行入口。移除整棵通用树的 adapter 和非原生并发包装，缩小测试矩阵。 | 默认构建将获取/编译固定版本 RocksDB，失去零外部依赖的可运行 adapter。测试中的独立预期值、MVCC oracle，以及用作校验容器的 std::map 仍有自己的用途。 |
| Abseil B-tree | 当前优先保留原生并发 BTreeOLC，收缩单线程树变体及其依赖。 | packed B-tree 的单线程 cache locality 和内存参照。 |
| TLX B+Tree | 原生单线程；收缩树变体，优先保留同一候选可参与并发实验的方案。 | packed B+Tree 参照；TLX 在 1 KiB value 的完整版本 flush 中领先，删除这项有明确的信息损失。 |
| Masstree | 配置、线程状态、遍历和延迟回收的 adapter 维护范围较大；基础组 RSS 约 432.7 B/version。先保留 BTreeOLC、UnoDB、Wormhole 的结构对照。 | Masstree 的分层结构，以及较强的历史点查（约 0.738 Mrequests/s）。 |
| HOT | 当前只集成 HOTSingleThreaded，未集成 ROWEX，无法参与原生并发比较；同时有独立 ISA、key 限制、内存池和补丁。 | 很强的单线程历史点查（约 0.762 Mrequests/s）。并发 ART 参照由 UnoDB 提供。 |
| OceanBase KeyBtree | 当前是索引核心移植，共同 InternalKey wrapper 未使用 OceanBase 原生 MVCC 版本链。GetAt 包含 225 条迭代器缓冲填充，点查解释范围较复杂；移除独立 port/runtime/vendor 维护路径。 | OceanBase KeyBtree 核心的 COW、epoch 回收和遍历参照。历史范围见[原集成说明](oceanbase.md)。 |
| CSE Arena | 固定版本 CSE 默认使用 Crossbeam；为聚焦实际默认实现，删除另一个可创建 backend。Arena 在百万 key 的深历史和 1 KiB value 配置触及容量限制，还需要两组较小规模补充实验。 | Arena 的紧凑分配、较低 RSS（基础组约 72.3 B/version）和整体释放参照。容量失败及较小规模结果继续保存在原始归档中。 |

这是对当前 benchmark 范围的收缩。取舍列记录了每项删除造成的信息损失，
历史测量不能据此改写为这些实现不可用或性能较差。

## CSE 默认实现的确认依据

在 CSE 固定版本 `80b0309f23f387ff5835a8153263f0d00fbfdaa0` 中确认了三处：

- `components/kvengine/src/config.rs:325`：配置默认值
  `enable_crossbeam_memtable: true`。
- `components/kvengine/src/options.rs:173`：运行 Options 默认值同样为 `true`。
- `components/kvengine/src/table/memtable/selectable_skl.rs:22`：
  `MemTableImplementation::Crossbeam` 标有 `#[default]`。
  `shard.rs` 通过 `from_crossbeam_enabled` 将运行选项传入 MemTable。

因此 **Crossbeam 是该固定版本的默认实现**。CSE 本身仍允许显式关闭此选项
来选择 Arena；本次修改的范围是 benchmark 的候选集合。

Crossbeam 的原生 `WriteBatch` / `WriteBatchEntry` 定义在 `skl.rs`，
而 `skl.rs` 引用 `arena.rs`。为保持固定版本源码原样，导出和编译仍需要这些
共享依赖模块。benchmark 的 Rust C ABI 已去掉 backend 枚举和选择参数，
只创建 Crossbeam；`cse_arena` 已从注册表、workload 检查和测试路径中移除。

## 代码、构建和实验的影响

- 两个可执行程序的默认索引都改为 `rocksdb_inlineskiplist`。
  RocksDB 成为必要的构建依赖，三个其他 C++ adapter 和 CSE 仍可选。
- 删除七项 adapter 的入口及其专用构建、补丁、port 和依赖。
  对已删除名称的运行请求在创建 CSV 前失败；旧 CMake 选项明确报错。
- 保留统一的 Insert/Get/Seek/Next/Scan、MVCC、Freeze/flush/Destroy、
  perf、RSS 和 CPU/NUMA 测量能力。
- 五项均可参与原生并发实验；CSE 的 batch writer 串行约束继续如实记录。
- 四种百万用户 key profile，1/4/8 workers、三次重复：
  当前计划 **300 个进程 / 960 行结果**。精简前同样四组为
  **594 / 1,920**；含 Arena 配套小规模组的原实验总计 **906 / 2,928**。
  当前计划无需 Arena 专用的小规模补充组。
- 历史 CSV、图表、源码快照和失败证据继续归档。报告工具对旧候选名称的兼容
  只用于读取历史结果；新实验的可用列表包含当前实现。

运行规模减少不代表已测得同等比例的耗时下降。新结果与历史结果分别记录
其源码、二进制、候选集合和 workload 参数。
