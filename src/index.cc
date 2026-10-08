#include "memtable_bench/index.h"

#include <map>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <utility>

#ifdef MEMTABLE_BENCH_HAVE_HOT
#include <cpuid.h>
#endif

#ifdef MEMTABLE_BENCH_HAVE_ABSEIL
#include "absl/container/btree_map.h"
#endif
#ifdef MEMTABLE_BENCH_HAVE_TLX
#include "tlx/container/btree_map.hpp"
#endif

namespace memtable_bench {
#ifdef MEMTABLE_BENCH_HAVE_ROCKSDB
std::unique_ptr<Index> MakeRocksDBInlineSkipList();
#endif
#ifdef MEMTABLE_BENCH_HAVE_BTREEOLC
std::unique_ptr<Index> MakeBTreeOLC();
#endif
#ifdef MEMTABLE_BENCH_HAVE_UNODB
std::unique_ptr<Index> MakeUnoDBART();
#endif
#ifdef MEMTABLE_BENCH_HAVE_MASSTREE
std::unique_ptr<Index> MakeMasstree();
#endif
#ifdef MEMTABLE_BENCH_HAVE_HOT
std::unique_ptr<Index> MakeHOT();
// Keep the feature check in a TU compiled without AVX2, before entering HOT.
bool HOTSupported() {
  unsigned eax, ebx, ecx, edx;
  const bool lzcnt = __get_cpuid(0x80000001, &eax, &ebx, &ecx, &edx) && (ecx & (1U << 5));
  return __builtin_cpu_supports("avx2") && __builtin_cpu_supports("bmi2") &&
         __builtin_cpu_supports("bmi") && __builtin_cpu_supports("popcnt") && lzcnt;
}
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

namespace {

template <class Map>
class LockedMapIndex final : public Index {
 public:
  bool Insert(std::string_view key, std::string_view value) override {
    std::unique_lock lock(mu_);
    if (frozen_) return false;
    std::string k(key);
    auto it = map_.lower_bound(k);
    if (it != map_.end() && it->first == k) {
      it->second.assign(value);
    } else {
      map_.insert(it, {std::move(k), std::string(value)});
    }
    return true;
  }

  bool Contains(std::string_view key) const override {
    std::shared_lock lock(mu_);
    return map_.find(std::string(key)) != map_.end();
  }

  bool Get(std::string_view key, std::string* value) const override {
    std::shared_lock lock(mu_);
    auto it = map_.find(std::string(key));
    if (it == map_.end()) return false;
    *value = it->second;
    return true;
  }

  class MapCursor final : public Cursor {
   public:
    explicit MapCursor(const LockedMapIndex& owner) : owner_(owner) {}

    bool Seek(std::string_view key) override {
      std::shared_lock lock(owner_.mu_);
      return Set(owner_.map_.lower_bound(std::string(key)));
    }

    bool Next() override {
      if (!valid_) return false;
      std::shared_lock lock(owner_.mu_);
      return Set(owner_.map_.upper_bound(key_));
    }

    bool Valid() const override { return valid_; }
    std::string_view Key() const override { return key_; }
    std::string_view Value() const override { return value_; }

   private:
    bool Set(typename Map::const_iterator it) {
      valid_ = it != owner_.map_.end();
      if (valid_) {
        key_ = it->first;
        value_ = it->second;
      } else {
        key_.clear();
        value_.clear();
      }
      return valid_;
    }

    const LockedMapIndex& owner_;
    std::string key_;
    std::string value_;
    bool valid_ = false;
  };

  // Freeze prevents all future writes, so iterators and their referenced bytes
  // stay valid. One seek followed by increments gives a linear full traversal.
  class FrozenMapCursor final : public Cursor {
   public:
    explicit FrozenMapCursor(const Map& map) : map_(map), it_(map.end()) {}

    bool Seek(std::string_view key) override {
      it_ = map_.lower_bound(std::string(key));
      return Valid();
    }

    bool Next() override {
      if (Valid()) ++it_;
      return Valid();
    }

    bool Valid() const override { return it_ != map_.end(); }
    std::string_view Key() const override {
      return Valid() ? std::string_view(it_->first) : std::string_view{};
    }
    std::string_view Value() const override {
      return Valid() ? std::string_view(it_->second) : std::string_view{};
    }

   private:
    const Map& map_;
    typename Map::const_iterator it_;
  };

  std::unique_ptr<Cursor> NewCursor() const override {
    std::shared_lock lock(mu_);
    if (frozen_) return std::make_unique<FrozenMapCursor>(map_);
    return std::make_unique<MapCursor>(*this);
  }

  void Freeze() override {
    std::unique_lock lock(mu_);
    frozen_ = true;
  }

  std::size_t Size() const override {
    std::shared_lock lock(mu_);
    return map_.size();
  }

  std::string_view ConcurrencyMode() const override { return "coarse_rwlock"; }

 private:
  mutable std::shared_mutex mu_;
  Map map_;
  bool frozen_ = false;
};

using StandardMap = std::map<std::string, std::string>;

}  // namespace

std::vector<AdapterInfo> ListAdapters() {
  return {
      {"std_map", true, "reference baseline; coarse reader/writer lock"},
#ifdef MEMTABLE_BENCH_HAVE_ABSEIL
      {"abseil_btree", true, "Abseil btree_map; coarse reader/writer lock"},
#else
      {"abseil_btree", false, "configure -DMEMTABLE_BENCH_FETCH_ABSEIL=ON"},
#endif
#ifdef MEMTABLE_BENCH_HAVE_TLX
      {"tlx_btree", true, "TLX btree_map; coarse reader/writer lock"},
#else
      {"tlx_btree", false, "configure -DMEMTABLE_BENCH_FETCH_TLX=ON"},
#endif
#ifdef MEMTABLE_BENCH_HAVE_ROCKSDB
      {"rocksdb_inlineskiplist", true, "RocksDB InlineSkipList + ConcurrentArena; append-only", true, false},
#else
      {"rocksdb_inlineskiplist", false, "configure -DMEMTABLE_BENCH_FETCH_ROCKSDB=ON", true, false},
#endif
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
#ifdef MEMTABLE_BENCH_HAVE_MASSTREE
      {"masstree", true, "Masstree; native concurrency; deferred node/value reclamation", true, true, 1024},
#else
      {"masstree", false, "configure -DMEMTABLE_BENCH_FETCH_MASSTREE=ON", true, true, 1024},
#endif
#ifdef MEMTABLE_BENCH_HAVE_HOT
      {"hot", HOTSupported(), HOTSupported() ? "HOTSingleThreaded; coarse reader/writer lock; terminated nibble keys" :
        "CPU lacks AVX2/BMI/BMI2/POPCNT/LZCNT required by HOT", false, true, 127, "nibble_terminated"},
#elif defined(MEMTABLE_BENCH_HOT_UNSUPPORTED)
      {"hot", false, "HOT requires x86_64 AVX2/BMI2; this target architecture is unsupported", false, true, 127, "nibble_terminated"},
#else
      {"hot", false, "configure -DMEMTABLE_BENCH_FETCH_HOT=ON; requires x86_64 AVX2/BMI2", false, true, 127, "nibble_terminated"},
#endif
#ifdef MEMTABLE_BENCH_HAVE_WORMHOLE
      {"wormhole", true, "Wormhole; native whsafe API with parked per-thread references", true, true, 65535},
#else
      {"wormhole", false, "configure -DMEMTABLE_BENCH_FETCH_WORMHOLE=ON", true, true, 65535},
#endif
  };
}

std::unique_ptr<Index> MakeIndex(std::string_view name) {
  if (name == "std_map") return std::make_unique<LockedMapIndex<StandardMap>>();
#ifdef MEMTABLE_BENCH_HAVE_ROCKSDB
  if (name == "rocksdb_inlineskiplist") return MakeRocksDBInlineSkipList();
#endif
#ifdef MEMTABLE_BENCH_HAVE_BTREEOLC
  if (name == "btreeolc") return MakeBTreeOLC();
#endif
#ifdef MEMTABLE_BENCH_HAVE_UNODB
  if (name == "unodb_art") return MakeUnoDBART();
#endif
#ifdef MEMTABLE_BENCH_HAVE_MASSTREE
  if (name == "masstree") return MakeMasstree();
#endif
#ifdef MEMTABLE_BENCH_HAVE_HOT
  if (name == "hot" && HOTSupported()) return MakeHOT();
#endif
#ifdef MEMTABLE_BENCH_HAVE_WORMHOLE
  if (name == "wormhole") return MakeWormhole();
#endif
#ifdef MEMTABLE_BENCH_HAVE_ABSEIL
  if (name == "abseil_btree") {
    return std::make_unique<LockedMapIndex<absl::btree_map<std::string, std::string>>>();
  }
#endif
#ifdef MEMTABLE_BENCH_HAVE_TLX
  if (name == "tlx_btree") {
    return std::make_unique<LockedMapIndex<tlx::btree_map<std::string, std::string>>>();
  }
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
