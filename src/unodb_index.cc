#include "memtable_bench/index.h"
#include "adapter_common.h"

#include "global.hpp"
#include "olc_art.hpp"
#include "qsbr.hpp"

#include <atomic>
#include <limits>
#include <span>

namespace memtable_bench {
namespace {
using ART = unodb::olc_db<unodb::key_view, unodb::value_view>;
using ARTIterator = decltype(std::declval<ART&>().test_only_iterator());

unodb::key_view Bytes(std::string_view s) {
  if (s.size() > std::numeric_limits<std::uint32_t>::max())
    throw std::length_error("UnoDB key/value exceeds uint32 length");
  return {reinterpret_cast<const std::byte*>(s.data()), s.size()};
}
std::string EncodeARTKey(std::string_view key) {
  if (key.size() > std::numeric_limits<std::uint32_t>::max() / 2)
    throw std::length_error("UnoDB encoded key exceeds uint32 length");
  return NibbleKey(key);
}
std::string_view View(std::span<const std::byte> s) {
  return {reinterpret_cast<const char*>(s.data()), s.size()};
}

class UnoDBART final : public Index {
 public:
  bool Insert(std::string_view key, std::string_view value) override {
    WriteAdmission::Guard admitted(admission_);
    if (!admitted) return false;
    const auto encoded = EncodeARTKey(key);
    unodb::qsbr_per_thread::ensure_registered();
    unodb::quiescent_state_on_scope_exit quiescent;
    if (!tree_.insert(Bytes(encoded), Bytes(value))) return false;
    size_.fetch_add(1, std::memory_order_relaxed);
    return true;
  }

  bool Contains(std::string_view key) const override {
    const auto encoded = EncodeARTKey(key);
    unodb::qsbr_per_thread::ensure_registered();
    unodb::quiescent_state_on_scope_exit quiescent;
    return tree_.get(Bytes(encoded)).has_value();
  }

  bool Get(std::string_view key, std::string* value) const override {
    const auto encoded = EncodeARTKey(key);
    unodb::qsbr_per_thread::ensure_registered();
    unodb::quiescent_state_on_scope_exit quiescent;
    const auto found = tree_.get(Bytes(encoded));
    if (!found) return false;
    value->assign(View(*found));
    return true;
  }

  // Public scans hold QSBR protection only for one movement and copy the
  // result. No internal stack or leaf view survives a quiescent state.
  class ActiveCursor final : public Cursor {
   public:
    explicit ActiveCursor(UnoDBART const& owner) : owner_(owner) {}
    bool Seek(std::string_view key) override { return Position(key, false); }
    bool Next() override { return valid_ && Position(key_, true); }
    bool Valid() const override { return valid_; }
    std::string_view Key() const override { return key_; }
    std::string_view Value() const override { return value_; }
   private:
    bool Position(std::string_view key, bool strict) {
      const auto encoded = EncodeARTKey(key);
      valid_ = false;
      unodb::qsbr_per_thread::ensure_registered();
      unodb::quiescent_state_on_scope_exit quiescent;
      owner_.tree_.scan_from(Bytes(encoded), [&](const auto& visit) {
        const auto candidate = View(visit.get_key());
        if (strict && candidate == encoded) return false;
        key_ = DecodeNibbleKey(candidate);
        value_.assign(View(visit.get_value()));
        valid_ = true;
        return true;
      });
      if (!valid_) { key_.clear(); value_.clear(); }
      return valid_;
    }
    const UnoDBART& owner_;
    bool valid_ = false;
    std::string key_, value_;
  };

  // The pinned upstream exposes its native iterator via test_only_iterator().
  // Use this internal API only after writes have drained: no iterator stack
  // can then reference an inode replaced by this tree's writer.
  class FrozenCursor final : public Cursor {
   public:
    explicit FrozenCursor(ART& tree) : it_(tree.test_only_iterator()) {}
    bool Seek(std::string_view key) override {
      const auto encoded = EncodeARTKey(key);
      unodb::qsbr_per_thread::ensure_registered();
      unodb::quiescent_state_on_scope_exit quiescent;
      bool exact = false;
      it_.seek(ART::art_key_type{Bytes(encoded)}, exact);
      return Refresh();
    }
    bool Next() override {
      if (!valid_) return false;
      unodb::qsbr_per_thread::ensure_registered();
      unodb::quiescent_state_on_scope_exit quiescent;
      it_.next();
      return Refresh();
    }
    bool Valid() const override { return valid_; }
    std::string_view Key() const override { return key_; }
    std::string_view Value() const override { return value_; }
   private:
    bool Refresh() {
      valid_ = it_.valid();
      if (valid_) {
        key_ = DecodeNibbleKey(View(it_.get_key()));
        value_ = View(it_.get_val());
      } else { key_.clear(); value_ = {}; }
      return valid_;
    }
    ARTIterator it_;
    std::string key_;
    std::string_view value_;
    bool valid_ = false;
  };

  std::unique_ptr<Cursor> NewCursor() const override {
    if (admission_.Frozen()) return std::make_unique<FrozenCursor>(tree_);
    return std::make_unique<ActiveCursor>(*this);
  }
  void Freeze() override { admission_.Freeze(); }
  std::size_t Size() const override { return size_.load(std::memory_order_relaxed); }
  bool SupportsUpsert() const override { return false; }
  std::string_view ConcurrencyMode() const override { return "native_olc_qsbr"; }
  std::string_view KeyEncoding() const override { return "nibble_terminated"; }
 private:
  mutable ART tree_;
  WriteAdmission admission_;
  std::atomic<std::size_t> size_{0};
};
}  // namespace

std::unique_ptr<Index> MakeUnoDBART() { return std::make_unique<UnoDBART>(); }
}  // namespace memtable_bench
