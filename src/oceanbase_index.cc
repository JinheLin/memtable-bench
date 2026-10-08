#include "memtable_bench/index.h"
#include "adapter_common.h"
#include "ob_keybtree.h"

#include <cstdlib>
#include <mutex>

namespace memtable_bench {
namespace {
namespace ob = oceanbase::common;
namespace kb = oceanbase::keybtree;

void Check(int status, const char* operation) {
  if (status != ob::OB_SUCCESS)
    throw std::runtime_error(std::string("OceanBase KeyBtree ") + operation +
                             " failed: " + std::to_string(status));
}
struct KeyBytes {
  std::string_view bytes;
  bool maximum = false;
};
// The upstream generic tree requires an eight-byte key and aligned value
// pointers. Database ObStoreRowkey comparisons are replaced with binary keys.
struct ByteKey {
  ByteKey(const KeyBytes* key = nullptr) : pointer(key) {}
  const KeyBytes* get_ptr() const { return pointer; }
  std::string DebugString() const {
    if (!pointer) return "MIN";
    if (pointer->maximum) return "MAX";
    constexpr char hex[] = "0123456789abcdef";
    std::string out;
    for (unsigned char byte : pointer->bytes) {
      out.push_back(hex[byte >> 4]);
      out.push_back(hex[byte & 15]);
    }
    return out;
  }
  int compare(const ByteKey& other, int& result) const {
    if (!pointer || !other.pointer) result = (pointer != nullptr) - (other.pointer != nullptr);
    else if (pointer->maximum || other.pointer->maximum)
      result = pointer->maximum - other.pointer->maximum;
    else result = pointer->bytes.compare(other.pointer->bytes);
    return ob::OB_SUCCESS;
  }
  const KeyBytes* pointer;
};
struct Record final : OwnedRecord {
  Record(std::string_view key, std::string_view value)
      : OwnedRecord(key, value), key_bytes{this->key} {}
  KeyBytes key_bytes;
};
using Tree = kb::ObKeyBtree<ByteKey, Record*>;
using NativeIterator = kb::BtreeIterator<ByteKey, Record*>;
static_assert(sizeof(ByteKey) == 8 && alignof(Record) >= 8);
static_assert(sizeof(NativeIterator) == 4016);

// Native node caches recycle COW nodes. The backing allocations must remain
// live until destroy(false) purges the native global RetireStation.
class BackingAllocator final : public ob::ObIAllocator {
 public:
  ~BackingAllocator() override { for (auto* block : blocks_) std::free(block); }
  void* alloc(std::int64_t size) override {
    void* block = nullptr;
    if (size <= 0 || posix_memalign(&block, 64, static_cast<std::size_t>(size)) != 0) return nullptr;
    try {
      std::lock_guard lock(mutex_);
      blocks_.push_back(block);
    } catch (...) { std::free(block); return nullptr; }
    return block;
  }
 private:
  std::mutex mutex_;
  std::vector<void*> blocks_;
};

class OceanBaseIndex final : public Index {
 public:
  OceanBaseIndex() : node_allocator_(allocator_), tree_(node_allocator_) { Check(tree_.init(), "init"); }
  ~OceanBaseIndex() override {
    admission_.Freeze();
    // Readers/cursors are already gone by the Index lifetime contract.
    if (tree_.destroy(false) != ob::OB_SUCCESS) std::abort();
  }
  bool Insert(std::string_view key, std::string_view value) override {
    WriteAdmission::Guard guard(admission_);
    if (!guard) return false;
    auto record = std::make_unique<Record>(key, value);
    auto* native_value = record.get();
    const int status = tree_.insert(ByteKey(&record->key_bytes), native_value);
    if (status == ob::OB_ENTRY_EXIST) return false;
    Check(status, "insert");
    records_.Keep(std::move(record));
    return true;
  }
  bool Contains(std::string_view key) const override { return Find(key) != nullptr; }
  bool Get(std::string_view key, std::string* value) const override {
    auto* record = Find(key);
    if (!record) return false;
    value->assign(record->value);
    return true;
  }
  class OceanBaseCursor final : public Cursor {
   public:
    explicit OceanBaseCursor(const Tree& tree) : tree_(tree) {}
    bool Seek(std::string_view key) override {
      iterator_.reset();
      start_storage_.assign(key);
      start_.bytes = start_storage_;
      Check(tree_.set_key_range(iterator_, ByteKey(&start_), false, ByteKey(&end_), false), "seek");
      return Advance();
    }
    bool Next() override { return Valid() && Advance(); }
    bool Valid() const override { return record_ != nullptr; }
    std::string_view Key() const override { return Valid() ? std::string_view(record_->key) : std::string_view{}; }
    std::string_view Value() const override { return Valid() ? std::string_view(record_->value) : std::string_view{}; }
   private:
    bool Advance() {
      ByteKey key;
      Record* value = nullptr;
      const auto status = iterator_.get_next(key, value);
      if (status == ob::OB_ITER_END) { record_ = nullptr; return false; }
      Check(status, "next");
      record_ = value;
      return true;
    }
    const Tree& tree_;
    std::string start_storage_;
    KeyBytes start_, end_{{}, true};
    NativeIterator iterator_;
    Record* record_ = nullptr;
  };
  std::unique_ptr<Cursor> NewCursor() const override { return std::make_unique<OceanBaseCursor>(tree_); }
  void Freeze() override { admission_.Freeze(); }
  std::size_t Size() const override { return static_cast<std::size_t>(tree_.size()); }
  std::string_view ConcurrencyMode() const override { return "native_keybtree_port_cow_epoch"; }
  bool SupportsUpsert() const override { return false; }
 private:
  Record* Find(std::string_view key) const {
    const KeyBytes probe{key};
    Record* value = nullptr;
    const int status = tree_.get(ByteKey(&probe), value);
    if (status == ob::OB_ENTRY_NOT_EXIST) return nullptr;
    Check(status, "get");
    return value;
  }
  BackingAllocator allocator_;
  kb::BtreeNodeAllocator<ByteKey, Record*> node_allocator_;
  mutable Tree tree_;
  RecordOwner<Record> records_;
  WriteAdmission admission_;
};
}  // namespace
std::unique_ptr<Index> MakeOceanBaseKeyBtree() { return std::make_unique<OceanBaseIndex>(); }
}  // namespace memtable_bench
