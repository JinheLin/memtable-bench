#include "memtable_bench/index.h"
#include "adapter_common.h"

#include "masstree.hh"
#include "masstree_struct.hh"
#include "masstree_get.hh"
#include "masstree_insert.hh"
#include "masstree_remove.hh"
#include "masstree_scan.hh"

#include <atomic>
#include <new>

namespace memtable_bench {
namespace {
// An insert/upsert-only MemTable never removes nodes. Retain all node/suffix
// allocations until whole-index destruction, including those retired by a
// suffix resize. This implements the threadinfo allocation contract without
// process-global server thread lists, RCU epochs, or retained thread pools.
class MasstreeAllocator {
 public:
  ~MasstreeAllocator() {
    auto* block = head_.load(std::memory_order_relaxed);
    while (block) {
      auto* next = block->next;
      ::operator delete(block, std::align_val_t{64});
      block = next;
    }
  }
  void* Allocate(std::size_t size) {
    auto* block = new (::operator new(sizeof(Block) + size, std::align_val_t{64})) Block;
    auto* head = head_.load(std::memory_order_relaxed);
    do { block->next = head; }
    while (!head_.compare_exchange_weak(head, block, std::memory_order_release,
                                        std::memory_order_relaxed));
    return block + 1;
  }
 private:
  struct alignas(64) Block { Block* next; };
  std::atomic<Block*> head_{nullptr};
};

struct MasstreeThreadInfo {
  struct mrcu_callback { virtual void operator()(MasstreeThreadInfo&) = 0; };
  struct StableFence {
    template <typename Version> void operator()(const Version&) const { relax_fence(); }
  };
  explicit MasstreeThreadInfo(MasstreeAllocator& allocator) : allocator(allocator) {}
  void* allocate(std::size_t size, memtag) { return allocator.Allocate(size); }
  void* pool_allocate(std::size_t size, memtag tag) { return allocate(size, tag); }
  void deallocate(void*, std::size_t, memtag) {}
  void deallocate_rcu(void*, std::size_t, memtag) {}
  void pool_deallocate(void*, std::size_t, memtag) {}
  void pool_deallocate_rcu(void*, std::size_t, memtag) {}
  void rcu_register(mrcu_callback*) {
    throw std::logic_error("Masstree adapter has no delete/RCU callback operations");
  }
  void mark(threadcounter) const {}
  std::uint64_t operation_timestamp() const { return 0; }
  StableFence stable_fence() const { return {}; }
  relax_fence_function lock_fence(threadcounter) const { return {}; }
  MasstreeAllocator& allocator;
};

struct Parameters : Masstree::nodeparams<15, 15> {
  using value_type = OwnedRecord*;
  using threadinfo_type = MasstreeThreadInfo;
};
using Table = Masstree::basic_table<Parameters>;
using Leaf = Masstree::leaf<Parameters>;
using Node = Masstree::node_base<Parameters>;
using MTKey = Masstree::key<Parameters::ikey_type>;

Masstree::Str Probe(std::string_view key) {
  if (key.size() > MASSTREE_MAXKEYLEN) throw std::length_error("Masstree key exceeds 1024 bytes");
  return {key.data(), static_cast<int>(key.size())};
}

class MasstreeIndex final : public Index {
 public:
  MasstreeIndex() {
    MasstreeThreadInfo ti(allocator_);
    table_.initialize(ti);
  }
  bool Insert(std::string_view key, std::string_view value) override {
    WriteAdmission::Guard admitted(admission_);
    if (!admitted) return false;
    const auto probe = Probe(key);
    auto record = std::make_unique<OwnedRecord>(key, value);
    MasstreeThreadInfo ti(allocator_);
    Table::cursor_type cursor(table_, probe);
    const bool exists = cursor.find_insert(ti);
    cursor.value() = record.get();
    cursor.finish(exists ? 0 : 1, ti);
    records_.Keep(std::move(record));
    if (!exists) size_.fetch_add(1, std::memory_order_relaxed);
    return true;
  }
  bool Contains(std::string_view key) const override {
    MasstreeThreadInfo ti(allocator_);
    OwnedRecord* record = nullptr;
    return table_.get(Probe(key), record, ti);
  }

  bool Get(std::string_view key, std::string* value) const override {
    MasstreeThreadInfo ti(allocator_);
    OwnedRecord* record = nullptr;
    if (!table_.get(Probe(key), record, ti)) return false;
    value->assign(record->value);
    return true;
  }

  OwnedRecord* LowerBound(std::string_view key, bool inclusive) const {
    struct Scanner {
      OwnedRecord* found = nullptr;
      void visit_leaf(const Masstree::scanstackelt<Parameters>&, const MTKey&,
                      MasstreeThreadInfo&) {}
      bool visit_value(const MTKey&, OwnedRecord* record, MasstreeThreadInfo&) {
        found = record;
        return false;
      }
    } scanner;
    MasstreeThreadInfo ti(allocator_);
    table_.scan(Probe(key), inclusive, scanner, ti);
    return scanner.found;
  }

  class ActiveCursor final : public Cursor {
   public:
    explicit ActiveCursor(const MasstreeIndex& owner) : owner_(owner) {}
    bool Seek(std::string_view key) override { record_ = owner_.LowerBound(key, true); return Valid(); }
    bool Next() override {
      if (record_) record_ = owner_.LowerBound(record_->key, false);
      return Valid();
    }
    bool Valid() const override { return record_ != nullptr; }
    std::string_view Key() const override { return record_ ? record_->key : std::string_view{}; }
    std::string_view Value() const override { return record_ ? record_->value : std::string_view{}; }
   private:
    const MasstreeIndex& owner_;
    OwnedRecord* record_ = nullptr;
  };

  // Stable leaf permutations and sibling links are enough for a native DFS
  // across Masstree's 8-byte trie layers. No sorted auxiliary index is built.
  class FrozenCursor final : public Cursor {
   public:
    explicit FrozenCursor(const MasstreeIndex& owner) : owner_(owner) {}
    bool Seek(std::string_view key) override {
      path_.clear();
      record_ = owner_.LowerBound(key, true);
      if (!record_) return false;
      MasstreeThreadInfo ti(owner_.allocator_);
      MTKey remaining(Probe(record_->key));
      Node* root = owner_.table_.root();
      while (true) {
        Leaf::nodeversion_type version;
        auto* leaf = root->reach_leaf(remaining, version, ti);
        const auto slot = key_lower_bound(remaining, *leaf);
        path_.push_back({leaf, slot.i});
        if (!leaf->keylenx_is_layer(leaf->keylenx_[slot.p])) break;
        root = leaf->lv_[slot.p].layer();
        remaining.shift();
      }
      return true;
    }
    bool Next() override {
      if (!record_) return false;
      ++path_.back().position;
      return Advance();
    }
    bool Valid() const override { return record_ != nullptr; }
    std::string_view Key() const override { return record_ ? record_->key : std::string_view{}; }
    std::string_view Value() const override { return record_ ? record_->value : std::string_view{}; }
   private:
    bool Advance() {
      MasstreeThreadInfo ti(owner_.allocator_);
      while (!path_.empty()) {
        auto& frame = path_.back();
        const auto permutation = frame.leaf->permutation();
        if (frame.position >= permutation.size()) {
          auto* next = frame.leaf->safe_next();
          if (next) { frame = {next, 0}; continue; }
          path_.pop_back();
          if (!path_.empty()) ++path_.back().position;
          continue;
        }
        const auto slot = permutation[frame.position];
        if (frame.leaf->keylenx_is_layer(frame.leaf->keylenx_[slot])) {
          auto* root = frame.leaf->lv_[slot].layer();
          Leaf::nodeversion_type version;
          const MTKey first(Masstree::Str("", 0));
          path_.push_back({root->reach_leaf(first, version, ti), 0});
          continue;
        }
        record_ = frame.leaf->lv_[slot].value();
        return true;
      }
      record_ = nullptr;
      return false;
    }
    struct Frame { Leaf* leaf; int position; };
    const MasstreeIndex& owner_;
    std::vector<Frame> path_;
    OwnedRecord* record_ = nullptr;
  };

  std::unique_ptr<Cursor> NewCursor() const override {
    if (admission_.Frozen()) return std::make_unique<FrozenCursor>(*this);
    return std::make_unique<ActiveCursor>(*this);
  }
  void Freeze() override { admission_.Freeze(); }
  std::size_t Size() const override { return size_.load(std::memory_order_relaxed); }
  std::string_view ConcurrencyMode() const override { return "native_masstree_deferred_reclaim"; }
 private:
  RecordOwner<> records_;
  mutable MasstreeAllocator allocator_;
  Table table_;
  WriteAdmission admission_;
  std::atomic<std::size_t> size_{0};
};
}  // namespace

std::unique_ptr<Index> MakeMasstree() { return std::make_unique<MasstreeIndex>(); }
}  // namespace memtable_bench
