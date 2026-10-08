#include "memtable_bench/index.h"
#include "adapter_common.h"

#include "hot/singlethreaded/HOTSingleThreaded.hpp"

#include <mutex>
#include <shared_mutex>

namespace memtable_bench {
namespace {
struct HOTRecord {
  HOTRecord(std::string_view key, std::string_view value)
      : key(key), value(value), encoded(NibbleKey(key)) {}
  std::string key, value, encoded;
};
template <typename T> struct HOTKeyExtractor {
  const char* operator()(T record) const { return record->encoded.c_str(); }
};
using HOTTree = hot::singlethreaded::HOTSingleThreaded<HOTRecord*, HOTKeyExtractor>;

void CheckHOTKey(std::string_view key) {
  if (key.size() > 127) throw std::length_error("HOT supports at most 127 binary key bytes after nibble encoding");
}

class HOTIndex final : public Index {
 public:
  bool Insert(std::string_view key, std::string_view value) override {
    CheckHOTKey(key);
    std::unique_lock lock(mu_);
    if (frozen_) return false;
    auto record = std::make_unique<HOTRecord>(key, value);
    auto* ptr = record.get();
    records_.push_back(std::move(record));
    const auto old = tree_.upsert(ptr);
    if (!old.mIsValid) ++size_;
    return true;
  }
  bool Contains(std::string_view key) const override {
    CheckHOTKey(key);
    const auto encoded = NibbleKey(key);
    std::shared_lock lock(mu_);
    return tree_.lookup(encoded.c_str()).mIsValid;
  }

  bool Get(std::string_view key, std::string* value) const override {
    CheckHOTKey(key);
    const auto encoded = NibbleKey(key);
    std::shared_lock lock(mu_);
    const auto found = tree_.lookup(encoded.c_str());
    if (!found.mIsValid) return false;
    value->assign(found.mValue->value);
    return true;
  }

  class HOTCursor final : public Cursor {
   public:
    HOTCursor(const HOTIndex& owner, bool frozen)
        : owner_(owner), frozen_(frozen), it_(owner.tree_.end()) {}
    bool Seek(std::string_view key) override { return Position(key, false); }
    bool Next() override {
      if (!valid_) return false;
      if (!frozen_) return Position(key_, true);
      ++it_;
      return Set();
    }
    bool Valid() const override { return valid_; }
    std::string_view Key() const override {
      return frozen_ ? (valid_ ? (*it_)->key : std::string_view{}) : std::string_view(key_);
    }
    std::string_view Value() const override {
      return frozen_ ? (valid_ ? (*it_)->value : std::string_view{}) : std::string_view(value_);
    }
   private:
    bool Position(std::string_view key, bool strict) {
      CheckHOTKey(key);
      const auto encoded = NibbleKey(key);
      if (frozen_) { it_ = owner_.tree_.lower_bound(encoded.c_str()); return Set(); }
      std::shared_lock lock(owner_.mu_);
      it_ = strict ? owner_.tree_.upper_bound(encoded.c_str()) : owner_.tree_.lower_bound(encoded.c_str());
      return Set();
    }
    bool Set() {
      valid_ = it_ != owner_.tree_.end();
      if (!frozen_) {
        if (valid_) { key_ = (*it_)->key; value_ = (*it_)->value; }
        else { key_.clear(); value_.clear(); }
      }
      return valid_;
    }
    const HOTIndex& owner_;
    bool frozen_, valid_ = false;
    HOTTree::const_iterator it_;
    std::string key_, value_;
  };
  std::unique_ptr<Cursor> NewCursor() const override {
    std::shared_lock lock(mu_);
    return std::make_unique<HOTCursor>(*this, frozen_);
  }
  void Freeze() override { std::unique_lock lock(mu_); frozen_ = true; }
  std::size_t Size() const override { std::shared_lock lock(mu_); return size_; }
  std::string_view ConcurrencyMode() const override { return "coarse_rwlock_hot_singlethreaded"; }
  std::string_view KeyEncoding() const override { return "nibble_terminated"; }
 private:
  mutable std::shared_mutex mu_;
  std::vector<std::unique_ptr<HOTRecord>> records_;
  mutable HOTTree tree_;
  std::size_t size_ = 0;
  bool frozen_ = false;
};
}  // namespace

std::unique_ptr<Index> MakeHOT() { return std::make_unique<HOTIndex>(); }
}  // namespace memtable_bench
