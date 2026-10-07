#include "memtable_bench/index.h"

#include <map>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <utility>

#ifdef MEMTABLE_BENCH_HAVE_ABSEIL
#include "absl/container/btree_map.h"
#endif
#ifdef MEMTABLE_BENCH_HAVE_TLX
#include "tlx/container/btree_map.hpp"
#endif

namespace memtable_bench {
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

  std::unique_ptr<Cursor> NewCursor() const override {
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
      {"rocksdb_inlineskiplist", false, "TODO: arena allocation, comparator, and iterator adapter"},
      {"btreeolc", false, "TODO: binary keys and ordered iterator semantics"},
      {"unodb_art", false, "TODO: binary-key encoding, cursor, and concurrency contract"},
      {"masstree", false, "TODO: thread context, value ownership, and iterator adapter"},
      {"hot", false, "TODO: key extraction, value lifetime, and iterator adapter"},
      {"wormhole", false, "TODO: thread registration, memory ownership, and iterator adapter"},
  };
}

std::unique_ptr<Index> MakeIndex(std::string_view name) {
  if (name == "std_map") return std::make_unique<LockedMapIndex<StandardMap>>();
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
