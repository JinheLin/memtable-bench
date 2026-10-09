#include "memtable_bench/index.h"

#include <stdexcept>

namespace memtable_bench {
std::unique_ptr<Index> MakeRocksDBInlineSkipList();
#ifdef MEMTABLE_BENCH_HAVE_BTREEOLC
std::unique_ptr<Index> MakeBTreeOLC();
#endif
#ifdef MEMTABLE_BENCH_HAVE_UNODB
std::unique_ptr<Index> MakeUnoDBART();
#endif
#ifdef MEMTABLE_BENCH_HAVE_WORMHOLE
std::unique_ptr<Index> MakeWormhole();
#endif

std::size_t Index::Scan(std::string_view start, std::size_t limit,
                        std::uint64_t* checksum) const {
  auto cursor = NewCursor();
  std::size_t count = 0;
  bool valid = cursor->Seek(start);
  while (valid && count < limit) {
    for (unsigned char byte : cursor->Key()) *checksum = (*checksum * 1099511628211ULL) ^ byte;
    for (unsigned char byte : cursor->Value()) *checksum = (*checksum * 1099511628211ULL) ^ byte;
    ++count;
    if (count < limit) valid = cursor->Next();
  }
  return count;
}

std::vector<AdapterInfo> ListAdapters() {
  return {
      {"rocksdb_inlineskiplist", true, "RocksDB InlineSkipList baseline + ConcurrentArena; append-only", true, false},
#ifdef MEMTABLE_BENCH_HAVE_BTREEOLC
      {"btreeolc", true, "BTreeOLC; native OLC with per-key stripes for exact size/upsert", true},
#else
      {"btreeolc", false, "configure -DMEMTABLE_BENCH_FETCH_BTREEOLC=ON", true},
#endif
#ifdef MEMTABLE_BENCH_HAVE_UNODB
      {"unodb_art", true, "UnoDB olc_db + QSBR; append-only; terminated nibble keys", true, false, 0, "nibble_terminated"},
#else
      {"unodb_art", false, "configure -DMEMTABLE_BENCH_FETCH_UNODB=ON", true, false, 0, "nibble_terminated"},
#endif
#ifdef MEMTABLE_BENCH_HAVE_WORMHOLE
      {"wormhole", true, "Wormhole; native whsafe API with parked per-thread references", true, true, 65535},
#else
      {"wormhole", false, "configure -DMEMTABLE_BENCH_FETCH_WORMHOLE=ON", true, true, 65535},
#endif
  };
}

std::unique_ptr<Index> MakeIndex(std::string_view name) {
  if (name == "rocksdb_inlineskiplist") return MakeRocksDBInlineSkipList();
#ifdef MEMTABLE_BENCH_HAVE_BTREEOLC
  if (name == "btreeolc") return MakeBTreeOLC();
#endif
#ifdef MEMTABLE_BENCH_HAVE_UNODB
  if (name == "unodb_art") return MakeUnoDBART();
#endif
#ifdef MEMTABLE_BENCH_HAVE_WORMHOLE
  if (name == "wormhole") return MakeWormhole();
#endif
  throw std::invalid_argument("adapter unavailable: " + std::string(name) +
                              "; run --list-indexes for details");
}

std::string EncodeKey(std::uint64_t user_id, std::size_t user_key_size,
                      bool internal_key, std::uint64_t sequence) {
  if (user_key_size < 8) throw std::invalid_argument("key size must be at least 8");
  std::string key(user_key_size + (internal_key ? 9 : 0), '\0');
  for (int i = 7; i >= 0; --i) {
    key[static_cast<std::size_t>(i)] = static_cast<char>(user_id & 0xff);
    user_id >>= 8;
  }
  // A deterministic suffix keeps the configured key width meaningful.
  for (std::size_t i = 8; i < user_key_size; ++i) {
    key[i] = static_cast<char>((key[i - 8] + 131 * i) & 0xff);
  }
  if (internal_key) {
    const std::uint64_t inverse = ~sequence;
    for (std::size_t i = 0; i < 8; ++i) {
      key[user_key_size + i] = static_cast<char>(inverse >> (56 - 8 * i));
    }
    key[user_key_size + 8] = 1;  // Value type, not a tombstone.
  }
  return key;
}

}  // namespace memtable_bench
