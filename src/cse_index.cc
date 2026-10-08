#include "memtable_bench/mvcc.h"
#include <atomic>
#include <exception>
#include <stdexcept>

namespace memtable_bench {
namespace {
struct NativeWrite {
  const char* key; std::size_t key_len;
  const char* value; std::size_t value_len;
  std::uint64_t version; std::uint8_t deleted;
};
struct NativeRecord {
  const char* key = nullptr; std::size_t key_len = 0;
  const char* value = nullptr; std::size_t value_len = 0;
  std::uint64_t version = 0; std::uint8_t deleted = 0;
};
extern "C" {
void* cse_new(std::uint8_t);
void cse_drop(void*);
int cse_write(const void*, const NativeWrite*, std::size_t);
int cse_get(const void*, const char*, std::size_t, std::uint64_t, void*,
            void (*)(void*, const NativeRecord*));
int cse_freeze(const void*);
std::uint64_t cse_retained(const void*);
void* cse_cursor_new(const void*, std::uint8_t);
void cse_cursor_drop(void*);
int cse_cursor_seek(void*, const char*, std::size_t);
int cse_cursor_next(void*, std::uint8_t);
int cse_cursor_record(const void*, NativeRecord*);
}
bool Check(int result) {
  if (result < 0) throw std::runtime_error("CSE bridge rejected input or caught a Rust panic");
  return result != 0;
}
class CseCursor final : public VersionCursor {
 public:
  CseCursor(const void* table, bool flush) : handle_(cse_cursor_new(table, flush)) {
    if (!handle_) throw std::runtime_error("CSE cursor creation failed (flush requires Freeze)");
  }
  ~CseCursor() override { cse_cursor_drop(handle_); }
  bool Seek(std::string_view key) override {
    Check(cse_cursor_seek(handle_, key.data(), key.size())); return Refresh();
  }
  bool NextUser() override { Check(cse_cursor_next(handle_, 0)); return Refresh(); }
  bool NextVersion() override {
    const bool advanced = Check(cse_cursor_next(handle_, 1)); Refresh(); return advanced;
  }
  bool Valid() const override { return valid_; }
  std::string_view Key() const override { return valid_ ? std::string_view(record_.key, record_.key_len) : std::string_view{}; }
  std::string_view Value() const override { return valid_ ? std::string_view(record_.value, record_.value_len) : std::string_view{}; }
  std::uint64_t Version() const override { return record_.version; }
  bool Deleted() const override { return record_.deleted; }
 private:
  bool Refresh() { valid_ = Check(cse_cursor_record(handle_, &record_)); return valid_; }
  void* handle_;
  NativeRecord record_;
  bool valid_ = false;
};
class CseTable final : public MvccTable {
 public:
  CseTable(bool crossbeam, std::size_t key_size) : handle_(cse_new(crossbeam)), key_size_(key_size) {
    if (!handle_) throw std::runtime_error("CSE initialization failed");
  }
  ~CseTable() override { cse_drop(handle_); }
  bool Write(std::span<const MvccWrite> batch) override {
    std::vector<NativeWrite> rows;
    rows.reserve(batch.size());
    for (const auto& row : batch) {
      if (row.key.size() != key_size_) throw std::invalid_argument("MVCC user key width differs");
      rows.push_back({row.key.data(), row.key.size(), row.value.data(), row.value.size(), row.version,
                      static_cast<std::uint8_t>(row.deleted)});
    }
    if (!Check(cse_write(handle_, rows.data(), rows.size()))) return false;
    versions_.fetch_add(batch.size(), std::memory_order_relaxed);
    return true;
  }
  bool GetAt(std::string_view key, std::uint64_t snapshot, MvccValue* result) const override {
    struct Output { MvccValue* value; std::exception_ptr error; } output{result, {}};
    const bool found = Check(cse_get(handle_, key.data(), key.size(), snapshot, &output,
      [](void* opaque, const NativeRecord* row) noexcept {
        auto& out = *static_cast<Output*>(opaque);
        try {
          out.value->version = row->version;
          out.value->deleted = row->deleted;
          out.value->value.assign(row->value, row->value_len);
        } catch (...) { out.error = std::current_exception(); }
      }));
    if (output.error) std::rethrow_exception(output.error);
    return found;
  }
  std::unique_ptr<VersionCursor> NewCursor(bool flush) const override {
    return std::make_unique<CseCursor>(handle_, flush);
  }
  void Freeze() override { Check(cse_freeze(handle_)); }
  std::size_t VersionCount() const override { return versions_.load(std::memory_order_relaxed); }
  std::string_view Representation() const override { return "user_key_chain"; }
  std::string_view ConcurrencyMode() const override { return "native_swmr_serialized_batch_writer_ffi"; }
  bool NativeBatch() const override { return true; }
  std::uint64_t RetainedBytes() const override { return cse_retained(handle_); }
 private:
  void* handle_;
  std::size_t key_size_;
  std::atomic<std::size_t> versions_{0};
};
}  // namespace
std::unique_ptr<MvccTable> MakeCseTable(bool crossbeam, std::size_t key_size) {
  return std::make_unique<CseTable>(crossbeam, key_size);
}
}  // namespace memtable_bench
