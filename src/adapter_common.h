#pragma once

#include <atomic>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>

namespace memtable_bench {

// Closing admission waits for all accepted writes. Readers and cursors must
// finish before the index is destroyed, as required by Index's lifetime contract.
class WriteAdmission {
 public:
  class Guard {
   public:
    explicit Guard(WriteAdmission& owner) : owner_(owner), admitted_(owner.Enter()) {}
    ~Guard() {
      if (admitted_) owner_.Leave();
    }
    Guard(const Guard&) = delete;
    Guard& operator=(const Guard&) = delete;
    explicit operator bool() const { return admitted_; }
   private:
    WriteAdmission& owner_;
    bool admitted_;
  };

  void Freeze() {
    state_.fetch_or(kFrozen, std::memory_order_acq_rel);
    auto state = state_.load(std::memory_order_acquire);
    while ((state & ~kFrozen) != 0) {
      state_.wait(state, std::memory_order_acquire);
      state = state_.load(std::memory_order_acquire);
    }
    drained_.store(true, std::memory_order_release);
  }
  bool Frozen() const { return drained_.load(std::memory_order_acquire); }

 private:
  bool Enter() {
    auto state = state_.load(std::memory_order_acquire);
    while (!(state & kFrozen)) {
      if (state_.compare_exchange_weak(state, state + 1, std::memory_order_acquire,
                                      std::memory_order_relaxed)) return true;
    }
    return false;
  }
  void Leave() {
    if (state_.fetch_sub(1, std::memory_order_acq_rel) == (kFrozen | 1))
      state_.notify_all();
  }
  static constexpr std::uint64_t kFrozen = std::uint64_t{1} << 63;
  std::atomic<std::uint64_t> state_{0};
  std::atomic<bool> drained_{false};
};

// No zero bytes except the terminator. The transformation preserves unsigned
// binary lexicographic order, including empty keys and prefix relationships.
// UnoDB receives the terminator as part of its key, making keys prefix-free.
inline std::string NibbleKey(std::string_view key) {
  if (key.size() > (std::numeric_limits<std::size_t>::max() - 1) / 2)
    throw std::length_error("key too large to encode");
  std::string out(key.size() * 2 + 1, '\0');
  for (std::size_t i = 0; i < key.size(); ++i) {
    const auto byte = static_cast<unsigned char>(key[i]);
    out[2 * i] = static_cast<char>('A' + (byte >> 4));
    out[2 * i + 1] = static_cast<char>('A' + (byte & 15));
  }
  return out;
}

inline std::string DecodeNibbleKey(std::string_view encoded) {
  if (encoded.empty() || encoded.back() != '\0' || encoded.size() % 2 != 1)
    throw std::runtime_error("invalid terminated key from adapter");
  std::string out((encoded.size() - 1) / 2, '\0');
  for (std::size_t i = 0; i < out.size(); ++i) {
    const unsigned high = static_cast<unsigned char>(encoded[2 * i]) - 'A';
    const unsigned low = static_cast<unsigned char>(encoded[2 * i + 1]) - 'A';
    if (high > 15 || low > 15) throw std::runtime_error("invalid nibble key");
    out[i] = static_cast<char>((high << 4) | low);
  }
  return out;
}

// Immutable records remain alive through upserts and active cursor movements.
// An intrusive ownership list avoids a global vector lock on insertion.
struct OwnedRecord {
  OwnedRecord(std::string_view k, std::string_view v) : key(k), value(v) {}
  std::string key;
  std::string value;
  OwnedRecord* next = nullptr;
};

template <typename Record = OwnedRecord>
class RecordOwner {
 public:
  ~RecordOwner() {
    auto* record = head_.load(std::memory_order_relaxed);
    while (record) {
      auto* next = record->next;
      delete static_cast<Record*>(record);
      record = next;
    }
  }
  void Keep(std::unique_ptr<Record> record) {
    auto* head = head_.load(std::memory_order_relaxed);
    do { record->next = head; }
    while (!head_.compare_exchange_weak(head, record.get(), std::memory_order_release,
                                        std::memory_order_relaxed));
    record.release();
  }
 private:
  std::atomic<OwnedRecord*> head_{nullptr};
};

}  // namespace memtable_bench
