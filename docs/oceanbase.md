# OceanBase integration

## Availability and boundary

| Candidate | Status | What it measures |
| --- | --- | --- |
| `oceanbase_keybtree` | Runnable on Linux x86-64 | Port of the actual MemTable KeyBtree index core, with binary keys and benchmark-owned records |
| `oceanbase_memtable_btree` | Unavailable; TODO | Full native ObMemtable MVCC with its B-tree lookup path |
| `oceanbase_memtable_hash_btree` | Unavailable; TODO | Full native ObMemtable MVCC with hash point lookups and ordered B-tree scans |

The runnable candidate is **an index core port**. It does not execute
`ObMemtable::set/get/scan`, native transaction version chains, row locks,
transaction cleanout, row compaction, tenant services or SST generation.
It must not be reported as full OceanBase MemTable performance. The two reserved
full-MemTable candidates are always listed as unavailable and reject execution.

The fixed source revision is
[`0fa1778765483295e844f0465938b831ee56fe4b`](https://github.com/oceanbase/oceanbase/tree/0fa1778765483295e844f0465938b831ee56fe4b/src/storage/memtable).
The original implementation calls this structure a B-tree; do not label it a B+tree.
It uses 15 entries per node, concurrent node modification, copy-on-write splits,
epoch retirement, CPU/thread-partitioned node caches and a 225-entry scan queue.

## Source reuse

`scripts/vendor_oceanbase.py` fetches only 13 pinned files, including upstream
LICENSE and NOTICE. Each original is checked against a tracked SHA-256 digest.
It supports an offline pinned Git checkout with `--source`. Configuration
generates isolated includes; every build verifies originals, generated files
and the manifest. Unexpected source changes fail the build.

These implementations retain their upstream method bodies:

- KeyBtree, its node allocator and buffered iterator;
- QClock, HazardList, RetireStation and ObQSync;
- atomic operations, counters, linked nodes and thread ID allocation/release.

The generated port changes quoted includes, qualifies template typedefs for
GCC, and replaces the database-specific iterator-size assertion with the same
4016-byte assertion on the adapter instantiation. It does not alter tree,
scan, split, locking, retirement or thread ID algorithms. Original files and
generated hashes remain available in `vendor/oceanbase-keybtree/`.

The tracked `vendor/oceanbase-port/` glue replaces unavailable server runtime
dependencies: build macros, logger/profiling hooks and allocator interface.
There are no coroutines in the harness; RLOCAL storage is OS-thread-local.
Logging/time guards are disabled; assertions still abort, and the adapter
checks native operation return codes. Unused callback and range-estimation
APIs are only forward-declared. DynamicQSync is not used by this adapter.

Keys use an eight-byte pointer wrapper with unsigned binary lexicographic
comparison, rather than OceanBase's typed `ObStoreRowkey` comparator. Values are
immutable, aligned record pointers. The backing allocator retains aligned node
blocks until native `destroy(false)` purges retirement; the adapter then frees
blocks and records. Record ownership, allocation, key comparison and the write
admission gate are included in timing. There is no coarse lock around the tree.
Only the backing allocation list has a mutex; upstream node caches reduce its use.

## Workload semantics

Both `memtable_bench` and `mvcc_bench` can use `oceanbase_keybtree` in all three
stages. It supports native concurrent insertion/read/scan, so it is eligible for
multiple workers. Duplicate exact keys return false; it is append-only.

For `mvcc_bench`, the common adapter stores one InternalKey **per version** and
implements snapshot/tombstone selection. This differs from native OceanBase's
one user key pointing to an `ObMvccRow` chain. `GetAt` uses an ordered cursor,
including the native iterator's first batch fill; it does not use OceanBase's
native hash/B-tree point-get plus row-chain visibility path. These costs matter
when interpreting point-read results. `Freeze` closes the adapter write gate
and drains accepted writes; it is not `ObMemtable::finish_freeze`.

Active native cursors can cache rows before concurrent inserts. Such inserts
may be omitted by an existing cursor, consistent with the Index contract.
A new Seek observes completed inserts. Fixed published snapshots used by the
MVCC benchmark are unaffected: later writes have greater versions, and all
visible history existed before readers started. Frozen flush walks every stored
InternalKey in order and validates its count and content against the oracle.

The CSV schemas remain v3 and mvcc-v1. `adapter_mode` identifies the core port as
`native_keybtree_port_cow_epoch`; MVCC representation is `internal_key`.
MVCC runner metadata includes all port glue hashes and upstream/generated
source hashes. RSS includes allocations and native shared retirement/clock state;
no OceanBase tenant allocator accounting is claimed.

## Build and run

No OceanBase server, special compiler toolchain or RPM dependency bundle is
needed for this index core. Python 3 is required for vendoring/verification.
Downloads bypass proxies; compilation must also use the direct environment:

```sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cmake -S . -B build-oceanbase -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DMEMTABLE_BENCH_FETCH_OCEANBASE=ON
cmake --build build-oceanbase -j 4
ctest --test-dir build-oceanbase --output-on-failure
build-oceanbase/mvcc_bench --list-indexes

build-oceanbase/memtable_bench --index oceanbase_keybtree --internal-key \
  --stage all --keys 100000 --ops 100000 --threads 4 \
  --key-size 24 --value-size 64 --output results/oceanbase-index.csv

build-oceanbase/mvcc_bench --index oceanbase_keybtree --stage all \
  --keys 100000 --versions 8 --snapshot-lag 4 --ops 100000 --threads 4 \
  --key-size 32 --key-layout global-prefix --prefix-bytes 24 \
  --value-size 64 --scan-length 100 --scan-ops 1024 \
  --cpu-list 2,3,4,5 --numa-node 0 --output results/oceanbase-mvcc.csv
```

`scripts/build_all.sh` enables the core along with the other optional indexes.
`mvcc_matrix.py` discovers it automatically. The historical exact-key matrix's
default nine-index cohort remains stable; explicitly select it with
`sensitivity_matrix.py --indexes std_map,rocksdb_inlineskiplist,oceanbase_keybtree`.

For offline vendoring:

```sh
python3 scripts/vendor_oceanbase.py --source /path/to/pinned/oceanbase \
  --output vendor/oceanbase-keybtree
python3 scripts/vendor_oceanbase.py --output vendor/oceanbase-keybtree --verify
```

## Full native MemTable TODO

The pinned [`ObMemtable`](https://github.com/oceanbase/oceanbase/blob/0fa1778765483295e844f0465938b831ee56fe4b/src/storage/memtable/ob_memtable.h)
initialization needs a TableKey, LS handle, freezer, Tablet MemTable manager,
schema version and freeze clock, plus the hash-index switch. Its write/read
paths also require storage access contexts, schema/read-info and transaction
services. Linking the header or inventing replacement visibility logic would
not provide this implementation.

Remaining work for the two unavailable candidates:

1. Build/link the pinned upstream oblib/storage code with its official dependency
   toolchain; initialize a real test tenant, LS/Tablet, freezer and transaction context.
2. Submit writes through the native transaction path and commit at controlled
   SCNs; retain snapshot history and tombstones required by the benchmark.
3. Adapt native snapshot reads and visible range scans. Expose complete retained
   versions for the existing flush oracle, without silently enabling compaction
   that drops benchmark-required history.
4. Use native freezing and release paths; validate tombstones, resurrection,
   snapshot boundaries, concurrent readers, retained versions and both hash modes.
5. Advertise availability and benchmark participation only after those paths
   compile and pass the MVCC contract on Linux x86-64.

Upstream `test_memtable_basic` is commented out in the pinned unit-test build;
it should not be treated as a ready standalone integration target. The current
query-engine and multiversion scan tests are useful references, but do not alone
provide a full transaction fixture.

The subset preserves OceanBase Apache-2.0 LICENSE and NOTICE. The harness's MIT
license does not relicense upstream files. See [THIRD_PARTY.md](../THIRD_PARTY.md).
