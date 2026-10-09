# Third-party sources and licenses

The repository's [MIT LICENSE](LICENSE) applies to its original harness and
adapter code. Optional upstream code keeps its own license and notices.
Pins below are part of the benchmark configuration; keep them fixed for a series.
Fetched sources stay in ignored build/vendor directories and are not committed
to this repository. Source pins, patches and standalone glue are tracked.

| Dependency | Pinned revision | Upstream license / source |
| --- | --- | --- |
| RocksDB | `ae8fb3e5000e46d8d4c9dbf3a36019c0aaceebff` (`v9.10.0`) | [Apache-2.0 or GPL-2.0, at the user's option](https://github.com/facebook/rocksdb/blob/v9.10.0/README.md#license); retain other source notices such as LICENSE.leveldb |
| BTreeOLC / index-microbench | `74cafa57d74798f209d8fcbce8c4f317ce066eae` | **License unresolved.** The pinned [BTreeOLC header](https://github.com/wangziqi2016/index-microbench/blob/74cafa57d74798f209d8fcbce8c4f317ce066eae/BTreeOLC/BTreeOLC.h) and repository root contain no identified license for this implementation. Licenses of unrelated vendored indexes do not resolve it. |
| UnoDB | `89f52799743ec2093426bdcf7a7cbaaa95ca848c` | [Apache-2.0](https://github.com/unodb-dev/unodb/blob/89f52799743ec2093426bdcf7a7cbaaa95ca848c/LICENSE) |
| Wormhole | `31dfd2b1e67e5f709c78b018cf4abaecadad8b72` | [GPL-3.0 license text in the repository root](https://github.com/wuxb45/wormhole/blob/31dfd2b1e67e5f709c78b018cf4abaecadad8b72/LICENSE) |
| Boost fallback headers | `1.86.0` | [Boost Software License 1.0](https://www.boost.org/LICENSE_1_0.txt); an installed Boost can be used instead |
| CSE MemTable core (optional local export) | `80b0309f23f387ff5835a8153263f0d00fbfdaa0` | Preserve the source notices and checkout's `COMMERCIAL-LICENSE` / `THIRD-PARTY-LICENSE`; no engine source is redistributed here. See [integration scope](docs/mvcc.md). |
| Crossbeam for CSE | `c4abd1b93149108dfa13c0cd42c878657c618bad` | MIT OR Apache-2.0; CSE's patched revision, locked by Cargo |

The standalone CSE bridge also uses byteorder 1.5.0, bytes 1.11.1, and rand
0.8.5 (MIT OR Apache-2.0). Their transitive versions and checksums are pinned
in `rust/cse_memtable/Cargo.lock`; preserve their package notices when distributing
a linked binary. The repository's MIT license does not relicense CSE or any
upstream dependency.

Boost fallback archive SHA-256:
`1bed88e40401b2cb7a1f76d4bab499e352fa4d0c5f31c0dbae64e24d34d7513b`.
Only its header tree and LICENSE_1_0.txt are extracted. The archive is from
[the official release](https://archives.boost.io/release/1.86.0/source/).

## Distribution choices

Keep the original code under MIT and keep all upstream licenses/attributions.
Do not describe an all-adapter binary as MIT-only. Wormhole is linked into the
same executable: distribution must account for GPL terms and corresponding
source, including the build configuration and patches. The GNU project explains
[the implications of linking GPL libraries](https://www.gnu.org/licenses/gpl-faq.en.html#GPLStaticVsDynamic).
Choose RocksDB's Apache-2.0 option when combining it with GPL-3.0 code.

Before redistributing BTreeOLC source or a binary containing it, resolve the
missing license with its author. This repository does not invent a license for
that header. The three optional adapters default to OFF; disabling BTreeOLC or Wormhole
can be an appropriate release configuration. Local benchmark availability is
recorded separately from license clearance.

## Upstream modifications

Upstream modifications are explicit, version-pinned patches. Some patch files
retain dormant upstream platform branches to preserve their original hashes;
current build support is Linux x86-64 only:

| Patch | Purpose |
| --- | --- |
| `btreeolc.patch` | Empty-node lookup, missing-key return initialization, standalone includes and ARM pause |
| `unodb-thread-registration.patch` | Register ordinary harness threads in upstream QSBR with upstream TLS cleanup |
| `unodb-iterator-restart.patch` | Retain owned next/prior restart probes and correct keyless-leaf seek comparison direction |
| `wormhole-asm.patch` | Portable inline-assembly instruction separators and alignment |
| `wormhole-unaligned.patch` | Use memcpy for CRC and common-prefix word loads from arbitrarily aligned byte views |

Only retained dependencies appear above. Retired dependency pins, licenses and
patches remain in the immutable measurement source snapshots; their removal
reasons are recorded in [index selection](docs/index-selection.md). Historical
archives still retain third-party provenance for the code actually measured.
