#include "memtable_bench/index.h"

#include <atomic>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>

#include "memory/concurrent_arena.h"
#include "memtable/inlineskiplist.h"
#include "util/coding.h"

namespace memtable_bench {
namespace {
namespace rdb = ROCKSDB_NAMESPACE;

// Records use RocksDB's memtable envelope:
// varint32(key length) | binary key | varint32(value length) | value.
// The key itself uses the harness's encoding, including its descending sequence.
struct BinaryComparator {
  using DecodedType = rdb::Slice;

  DecodedType decode_key(const char* record) const {
    return rdb::GetLengthPrefixedSlice(record);
  }
  int operator()(const char* a, const char* b) const {
    return decode_key(a).compare(decode_key(b));
  }
  int operator()(const char* a, const DecodedType& b) const {
    return decode_key(a).compare(b);
  }
};

std::string EncodeProbe(std::string_view key) {
  if (key.size() > std::numeric_limits<std::uint32_t>::max())
    throw std::length_error("RocksDB adapter keys must fit varint32");
  std::string probe;
  probe.reserve(key.size() + 5);
  rdb::PutLengthPrefixedSlice(&probe, rdb::Slice(key.data(), key.size()));
  return probe;
}

std::string_view RecordKey(const char* record) {
  const auto key = rdb::GetLengthPrefixedSlice(record);
  return {key.data(), key.size()};
}

std::string_view RecordValue(const char* record) {
  const auto key = rdb::GetLengthPrefixedSlice(record);
  const auto value = rdb::GetLengthPrefixedSlice(key.data() + key.size());
  return {value.data(), value.size()};
}

using SkipList = rdb::InlineSkipList<BinaryComparator>;

class RocksDBInlineSkipList final : public Index {
 public:
  RocksDBInlineSkipList() : arena_(64 * 1024), list_(BinaryComparator{}, &arena_) {}

  bool Insert(std::string_view key, std::string_view value) override {
    if (!BeginInsert()) return false;
    InsertGuard guard(*this);
    if (key.size() > std::numeric_limits<std::uint32_t>::max() ||
        value.size() > std::numeric_limits<std::uint32_t>::max())
      throw std::length_error("RocksDB adapter keys/values must fit varint32");
    const auto key_length = static_cast<std::uint32_t>(key.size());
    const auto value_length = static_cast<std::uint32_t>(value.size());
    const std::size_t record_size = rdb::VarintLength(key_length) + key.size() +
                                    rdb::VarintLength(value_length) + value.size();
    char* record = list_.AllocateKey(record_size);
    char* dst = rdb::EncodeVarint32(record, key_length);
    if (!key.empty()) std::memcpy(dst, key.data(), key.size());
    dst += key.size();
    dst = rdb::EncodeVarint32(dst, value_length);
    if (!value.empty()) std::memcpy(dst, value.data(), value.size());

    // The upstream CAS insert detects duplicates. Published bytes are immutable;
    // a failed allocation/duplicate stays in the arena until whole-index destroy.
    if (!list_.InsertConcurrently(record)) return false;
    size_.fetch_add(1, std::memory_order_relaxed);
    return true;
  }

  bool Get(std::string_view key, std::string* value) const override {
    const std::string probe = EncodeProbe(key);
    SkipList::Iterator it(&list_);
    it.Seek(probe.data());
    if (!it.Valid() || RecordKey(it.key()) != key) return false;
    value->assign(RecordValue(it.key()));
    return true;
  }

  class SkipListCursor final : public Cursor {
   public:
    explicit SkipListCursor(const SkipList& list) : it_(&list) {}

    bool Seek(std::string_view key) override {
      const std::string probe = EncodeProbe(key);
      it_.Seek(probe.data());
      return Valid();
    }
    bool Next() override {
      if (Valid()) it_.Next();
      return Valid();
    }
    bool Valid() const override { return it_.Valid(); }
    std::string_view Key() const override {
      return Valid() ? RecordKey(it_.key()) : std::string_view{};
    }
    std::string_view Value() const override {
      return Valid() ? RecordValue(it_.key()) : std::string_view{};
    }

   private:
    SkipList::Iterator it_;
  };

  std::unique_ptr<Cursor> NewCursor() const override {
    return std::make_unique<SkipListCursor>(list_);
  }

  void Freeze() override {
    state_.fetch_or(kFrozen, std::memory_order_acq_rel);
    auto state = state_.load(std::memory_order_acquire);
    while ((state & ~kFrozen) != 0) {
      state_.wait(state, std::memory_order_acquire);
      state = state_.load(std::memory_order_acquire);
    }
  }

  std::size_t Size() const override { return size_.load(std::memory_order_relaxed); }
  std::string_view ConcurrencyMode() const override { return "native_concurrent_insert"; }
  bool SupportsUpsert() const override { return false; }

 private:
  bool BeginInsert() {
    auto state = state_.load(std::memory_order_acquire);
    while ((state & kFrozen) == 0) {
      if (state_.compare_exchange_weak(state, state + 1,
                                      std::memory_order_acquire,
                                      std::memory_order_relaxed)) return true;
    }
    return false;
  }

  class InsertGuard {
   public:
    explicit InsertGuard(RocksDBInlineSkipList& owner) : owner_(owner) {}
    ~InsertGuard() {
      const auto previous = owner_.state_.fetch_sub(1, std::memory_order_acq_rel);
      if (previous == (kFrozen | 1)) owner_.state_.notify_all();
    }
   private:
    RocksDBInlineSkipList& owner_;
  };

  static constexpr std::uint64_t kFrozen = std::uint64_t{1} << 63;
  // Arena precedes the list so its memory survives until the list is destroyed.
  rdb::ConcurrentArena arena_;
  SkipList list_;
  std::atomic<std::size_t> size_{0};
  // High bit closes admission; low bits count inserts already in flight.
  std::atomic<std::uint64_t> state_{0};
};

}  // namespace

std::unique_ptr<Index> MakeRocksDBInlineSkipList() {
  return std::make_unique<RocksDBInlineSkipList>();
}

}  // namespace memtable_bench
