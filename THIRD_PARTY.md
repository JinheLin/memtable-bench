# Third-party sources and licenses

The repository's [MIT LICENSE](LICENSE) applies to its original harness and
adapter code. Optional upstream code keeps its own license and notices.
Pins below are part of the benchmark configuration; keep them fixed for a series.
Fetched checkouts stay in build directories and are not copied into this repository.

| Dependency | Pinned revision | Upstream license / source |
| --- | --- | --- |
| Abseil | `76bb24329e8bf5f39704eb10d21b9a80befa7c81` (`20250512.1`) | [Apache-2.0](https://github.com/abseil/abseil-cpp/blob/76bb24329e8bf5f39704eb10d21b9a80befa7c81/LICENSE) |
| TLX | `502601e2328129263eeb31a61342e4a48f519a2b` (`v0.6.1`) | [Boost Software License 1.0](https://github.com/tlx/tlx/blob/502601e2328129263eeb31a61342e4a48f519a2b/LICENSE) |
| RocksDB | `ae8fb3e5000e46d8d4c9dbf3a36019c0aaceebff` (`v9.10.0`) | [Apache-2.0 or GPL-2.0, at the user's option](https://github.com/facebook/rocksdb/blob/v9.10.0/README.md#license); retain other source notices such as LICENSE.leveldb |
| BTreeOLC / index-microbench | `74cafa57d74798f209d8fcbce8c4f317ce066eae` | **License unresolved.** The pinned [BTreeOLC header](https://github.com/wangziqi2016/index-microbench/blob/74cafa57d74798f209d8fcbce8c4f317ce066eae/BTreeOLC/BTreeOLC.h) and repository root contain no identified license for this implementation. Licenses of unrelated vendored indexes do not resolve it. |
| UnoDB | `89f52799743ec2093426bdcf7a7cbaaa95ca848c` | [Apache-2.0](https://github.com/unodb-dev/unodb/blob/89f52799743ec2093426bdcf7a7cbaaa95ca848c/LICENSE) |
| Masstree | `11198427a1170654ca646dd20d96c8f349bca2bd` | [MIT terms plus a publicity/name-use restriction](https://github.com/kohler/masstree-beta/blob/11198427a1170654ca646dd20d96c8f349bca2bd/LICENSE) |
| HOT | `96bf6fb7103b27e50e16a6026db8974c090ee84a` | [ISC](https://github.com/speedskater/hot/blob/96bf6fb7103b27e50e16a6026db8974c090ee84a/LICENSE) |
| Wormhole | `31dfd2b1e67e5f709c78b018cf4abaecadad8b72` | [GPL-3.0 license text in the repository root](https://github.com/wuxb45/wormhole/blob/31dfd2b1e67e5f709c78b018cf4abaecadad8b72/LICENSE) |
| Boost fallback headers | `1.86.0` | [Boost Software License 1.0](https://www.boost.org/LICENSE_1_0.txt); an installed Boost can be used instead |
| CSE MemTable core (optional local export) | `80b0309f23f387ff5835a8153263f0d00fbfdaa0` | Preserve the source notices and checkout's `COMMERCIAL-LICENSE` / `THIRD-PARTY-LICENSE`; no engine source is redistributed here. See [integration scope](docs/mvcc.md). |
| Crossbeam for CSE | `c4abd1b93149108dfa13c0cd42c878657c618bad` | MIT OR Apache-2.0; CSE's patched revision, locked by Cargo |

The standalone CSE bridge also uses byteorder 1.5.0, bytes 1.11.1, and rand
0.8.5 (MIT OR Apache-2.0). Their transitive versions and checksums are pinned
in `rust/cse_memtable/Cargo.lock`; preserve their package notices when distributing
a linked binary. The repository's MIT license does not relicense CSE or any
upstream dependency.

TLX's `502601e2328129263eeb31a61342e4a48f519a2b` pin is the annotated
`v0.6.1` tag object. It resolves to commit
`b6af589954fafd334f2f373b057a8886e1c6abc8`, which is what benchmark metadata
records as the checked-out HEAD. These refer to the same source revision.

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
that header. All optional adapters default to OFF; disabling BTreeOLC or Wormhole
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
| `masstree-arm64.patch` | Historical patch, retained for old source snapshots; not applied by the current Linux x86-64 build |
| `masstree-permutation.patch` | Avoid a 64-bit shift for an empty permutation remainder |
| `hot-clang.patch` | Clang declaration/template ordering fixes and equivalent SSE2 byte-mask operation |
| `hot-leaf-bound.patch` | Correct lower/upper-bound ordering and strictness for a single-record tree |
| `wormhole-asm.patch` | Portable inline-assembly instruction separators and alignment |
| `wormhole-unaligned.patch` | Use memcpy for CRC and common-prefix word loads from arbitrarily aligned byte views |

Masstree uses a harness allocation context with whole-index retirement; HOT uses
its single-threaded implementation with a harness lock. Neither is presented as
an unmodified upstream server/ROWEX benchmark. Consult the README for key encoding,
CPU requirements, operation semantics and actual local validation status.
