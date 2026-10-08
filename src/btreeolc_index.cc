#include "memtable_bench/index.h"
#include "adapter_common.h"

#include "BTreeOLC/BTreeOLC.h"

#include <array>
#include <mutex>
#include <thread>
#include <type_traits>

namespace memtable_bench {
namespace {
// Upstream nodes memcpy keys, so store a trivially copyable view over immutable
// index-owned bytes, rather than putting std::string inside a page.
struct BinaryKey {
  // One aligned pointer rather than a two-word string_view: native OLC page
  // copies must not tear a view's pointer and length during comparison.
  const std::string_view* bytes = nullptr;
  std::string_view View() const { return bytes ? *bytes : std::string_view{}; }
  bool operator<(BinaryKey other) const { return View() < other.View(); }
  bool operator>(BinaryKey other) const { return View() > other.View(); }
  bool operator==(BinaryKey other) const { return View() == other.View(); }
};
struct BTreeRecord : OwnedRecord {
  BTreeRecord(std::string_view key, std::string_view value)
      : OwnedRecord(key, value), key_view(this->key) {}
  const std::string_view key_view;
};
static_assert(std::is_trivially_copyable_v<BinaryKey>);
static_assert(sizeof(BinaryKey) == sizeof(void*));
using Tree = btreeolc::BTree<BinaryKey, OwnedRecord*>;
using Node = btreeolc::NodeBase;
using Inner = btreeolc::BTreeInner<BinaryKey>;
using Leaf = btreeolc::BTreeLeaf<BinaryKey, OwnedRecord*>;

void FreeNodes(Node* node) {
  if (node->type == btreeolc::PageType::BTreeInner) {
    auto* inner = static_cast<Inner*>(node);
    for (unsigned i = 0; i <= inner->count; ++i) FreeNodes(inner->children[i]);
    delete inner;
  } else { delete static_cast<Leaf*>(node); }
}

class BTreeOLCIndex final : public Index {
 public:
  ~BTreeOLCIndex() override { FreeNodes(tree_.root.load()); }

  bool Insert(std::string_view key, std::string_view value) override {
    WriteAdmission::Guard admitted(admission_);
    if (!admitted) return false;
    // Upstream insert upserts and returns void. A stripe serializes equal keys
    // for accurate size tracking; unrelated keys use native OLC page locking.
    const auto stripe = std::hash<std::string_view>{}(key) % stripes_.size();
    std::lock_guard lock(stripes_[stripe]);
    auto record = std::make_unique<BTreeRecord>(key, value);
    OwnedRecord* previous = nullptr;
    const bool exists = tree_.lookup({&key}, previous);
    tree_.insert({&record->key_view}, record.get());
    records_.Keep(std::move(record));
    if (!exists) size_.fetch_add(1, std::memory_order_relaxed);
    return true;
  }

  bool Contains(std::string_view key) const override {
    OwnedRecord* found = nullptr;
    return tree_.lookup({&key}, found);
  }

  bool Get(std::string_view key, std::string* value) const override {
    OwnedRecord* found = nullptr;
    if (!tree_.lookup({&key}, found)) return false;
    value->assign(found->value);
    return true;
  }

  // Upstream scan stops at a single leaf. This optimistic lower_bound walks
  // parent frames across leaf boundaries and validates every visited page.
  OwnedRecord* LowerBound(std::string_view key, bool strict) const {
    struct Path { Node* node; std::uint64_t version; unsigned child; };
    for (;;) {
      bool restart = false;
      std::vector<Path> checked;
      std::vector<std::size_t> parents;
      auto* root = tree_.root.load();
      auto* node = root;
      const auto enter = [&](Node* next) {
        checked.push_back({next, next->readLockOrRestart(restart), 0});
      };
      enter(node);
      while (!restart && node->type == btreeolc::PageType::BTreeInner) {
        auto* inner = static_cast<Inner*>(node);
        const unsigned child = inner->lowerBound({&key});
        checked.back().child = child;
        parents.push_back(checked.size() - 1);
        node = inner->children[child];
        inner->checkOrRestart(checked.back().version, restart);
        if (!restart) enter(node);
      }
      if (restart) { std::this_thread::yield(); continue; }
      auto* leaf = static_cast<Leaf*>(node);
      unsigned position = leaf->lowerBound({&key});
      if (strict && position < leaf->count && leaf->keys[position].View() == key) ++position;
      while (position >= leaf->count && !parents.empty() && !restart) {
        auto& parent = checked[parents.back()];
        auto* inner = static_cast<Inner*>(parent.node);
        const auto count = inner->count;
        inner->checkOrRestart(parent.version, restart);
        if (restart) break;
        if (parent.child >= count) { parents.pop_back(); continue; }
        node = inner->children[++parent.child];
        inner->checkOrRestart(parent.version, restart);
        if (restart) break;
        enter(node);
        while (!restart && node->type == btreeolc::PageType::BTreeInner) {
          inner = static_cast<Inner*>(node);
          parents.push_back(checked.size() - 1);
          node = inner->children[0];
          inner->checkOrRestart(checked.back().version, restart);
          if (!restart) enter(node);
        }
        if (restart) break;
        leaf = static_cast<Leaf*>(node);
        position = 0;
      }
      OwnedRecord* found = !restart && position < leaf->count ? leaf->payloads[position] : nullptr;
      for (const auto& entry : checked) {
        bool changed = false;
        entry.node->checkOrRestart(entry.version, changed);
        restart |= changed;
      }
      if (!restart && root == tree_.root.load()) return found;
    }
  }

  class ActiveCursor final : public Cursor {
   public:
    explicit ActiveCursor(const BTreeOLCIndex& owner) : owner_(owner) {}
    bool Seek(std::string_view key) override { record_ = owner_.LowerBound(key, false); return Valid(); }
    bool Next() override {
      if (record_) record_ = owner_.LowerBound(record_->key, true);
      return Valid();
    }
    bool Valid() const override { return record_ != nullptr; }
    std::string_view Key() const override { return record_ ? record_->key : std::string_view{}; }
    std::string_view Value() const override { return record_ ? record_->value : std::string_view{}; }
   private:
    const BTreeOLCIndex& owner_;
    OwnedRecord* record_ = nullptr;
  };

  class FrozenCursor final : public Cursor {
   public:
    explicit FrozenCursor(Node* root) : root_(root) {}
    bool Seek(std::string_view key) override {
      path_.clear();
      auto* node = root_;
      while (node->type == btreeolc::PageType::BTreeInner) {
        auto* inner = static_cast<Inner*>(node);
        const auto child = inner->lowerBound({&key});
        path_.push_back({inner, child});
        node = inner->children[child];
      }
      leaf_ = static_cast<Leaf*>(node);
      position_ = leaf_->lowerBound({&key});
      if (position_ >= leaf_->count) AdvanceLeaf();
      return Valid();
    }
    bool Next() override {
      if (Valid() && ++position_ >= leaf_->count) AdvanceLeaf();
      return Valid();
    }
    bool Valid() const override { return leaf_ && position_ < leaf_->count; }
    std::string_view Key() const override { return Valid() ? Record()->key : std::string_view{}; }
    std::string_view Value() const override { return Valid() ? Record()->value : std::string_view{}; }
   private:
    OwnedRecord* Record() const { return leaf_->payloads[position_]; }
    void AdvanceLeaf() {
      while (!path_.empty()) {
        auto& [inner, child] = path_.back();
        if (child == inner->count) { path_.pop_back(); continue; }
        auto* node = inner->children[++child];
        while (node->type == btreeolc::PageType::BTreeInner) {
          auto* next = static_cast<Inner*>(node);
          path_.push_back({next, 0});
          node = next->children[0];
        }
        leaf_ = static_cast<Leaf*>(node);
        position_ = 0;
        if (leaf_->count) return;
      }
      leaf_ = nullptr;
    }
    Node* root_;
    Leaf* leaf_ = nullptr;
    unsigned position_ = 0;
    std::vector<std::pair<Inner*, unsigned>> path_;
  };

  std::unique_ptr<Cursor> NewCursor() const override {
    if (admission_.Frozen()) return std::make_unique<FrozenCursor>(tree_.root.load());
    return std::make_unique<ActiveCursor>(*this);
  }
  void Freeze() override { admission_.Freeze(); }
  std::size_t Size() const override { return size_.load(std::memory_order_relaxed); }
  std::string_view ConcurrencyMode() const override { return "native_olc_key_stripes"; }
 private:
  RecordOwner<BTreeRecord> records_;
  mutable Tree tree_;
  std::array<std::mutex, 256> stripes_;
  WriteAdmission admission_;
  std::atomic<std::size_t> size_{0};
};
}  // namespace

std::unique_ptr<Index> MakeBTreeOLC() { return std::make_unique<BTreeOLCIndex>(); }
}  // namespace memtable_bench
