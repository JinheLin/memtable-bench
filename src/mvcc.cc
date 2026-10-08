#include "memtable_bench/mvcc.h"
#include <limits>
#include <stdexcept>

namespace memtable_bench {
#ifdef MEMTABLE_BENCH_HAVE_CSE
std::unique_ptr<MvccTable> MakeCseTable(bool crossbeam, std::size_t key_size);
#endif
namespace {
std::uint64_t DecodeVersion(std::string_view key) {
  std::uint64_t encoded = 0;
  for (unsigned char byte : key.substr(key.size() - 9, 8)) encoded = (encoded << 8) | byte;
  return ~encoded;
}
class InternalCursor final : public VersionCursor {
 public:
  explicit InternalCursor(std::unique_ptr<Cursor> cursor) : cursor_(std::move(cursor)) {}
  bool Seek(std::string_view key) override {
    return cursor_->Seek(MvccInternalKey(key, UINT64_MAX, true));
  }
  bool NextUser() override {
    if (!Valid()) return false;
    const std::string key(Key());
    while (cursor_->Next()) if (Key() != key) return true;
    return false;
  }
  bool NextVersion() override {
    if (!Valid()) return false;
    const std::string current(cursor_->Key()), user(Key());
    if (cursor_->Next() && Key() == user) return true;
    cursor_->Seek(current);  // preserve position as required by native API
    return false;
  }
  bool Valid() const override { return cursor_->Valid(); }
  bool Next() override { return cursor_->Next(); }
  std::string_view Key() const override {
    return Valid() ? cursor_->Key().substr(0, cursor_->Key().size() - 9) : std::string_view{};
  }
  std::string_view Value() const override { return cursor_->Value(); }
  std::uint64_t Version() const override { return DecodeVersion(cursor_->Key()); }
  bool Deleted() const override { return cursor_->Key().back() == 0; }
 private:
  std::unique_ptr<Cursor> cursor_;
};
class InternalTable final : public MvccTable {
 public:
  InternalTable(std::unique_ptr<Index> index, std::size_t key_size)
      : index_(std::move(index)), key_size_(key_size) {}
  bool Write(std::span<const MvccWrite> batch) override {
    for (const auto& row : batch) {
      if (row.key.size() != key_size_) throw std::invalid_argument("MVCC user key width differs");
      if (!index_->Insert(MvccInternalKey(row.key, row.version, row.deleted), row.value)) return false;
    }
    return true;
  }
  bool GetAt(std::string_view key, std::uint64_t snapshot, MvccValue* result) const override {
    auto cursor = index_->NewCursor();
    if (!cursor->Seek(MvccInternalKey(key, snapshot, true)) ||
        cursor->Key().substr(0, cursor->Key().size() - 9) != key) return false;
    result->version = DecodeVersion(cursor->Key());
    result->deleted = cursor->Key().back() == 0;
    result->value.assign(cursor->Value());
    return true;
  }
  std::unique_ptr<VersionCursor> NewCursor(bool) const override {
    return std::make_unique<InternalCursor>(index_->NewCursor());
  }
  void Freeze() override { index_->Freeze(); }
  std::size_t VersionCount() const override { return index_->Size(); }
  std::string_view Representation() const override { return "internal_key"; }
  std::string_view ConcurrencyMode() const override { return index_->ConcurrencyMode(); }
 private:
  std::unique_ptr<Index> index_;
  std::size_t key_size_;
};
}  // namespace

std::string MvccInternalKey(std::string_view user_key, std::uint64_t version, bool deleted) {
  std::string key(user_key);
  const auto descending = ~version;
  for (int shift = 56; shift >= 0; shift -= 8) key.push_back(static_cast<char>(descending >> shift));
  key.push_back(deleted ? 0 : 1);
  return key;
}
std::vector<AdapterInfo> ListMvccAdapters() {
  auto adapters = ListAdapters();
#ifdef MEMTABLE_BENCH_HAVE_CSE
  constexpr bool available = true;
  const std::string reason = "CSE native version chains; serialized batch writer; Rust FFI";
#else
  constexpr bool available = false;
  const std::string reason = "configure MEMTABLE_BENCH_CSE_SOURCE_DIR with pinned export";
#endif
  adapters.push_back({"cse_arena", available, reason, true, false, 65535, "user_key_chain"});
  adapters.push_back({"cse_crossbeam", available, reason, true, false, 65535, "user_key_chain"});
  adapters.push_back({"oceanbase_memtable_btree", false,
      "TODO: full ObMemtable requires native tenant/transaction/tablet/freezer runtime; use oceanbase_keybtree for index core",
      false, false, 0, "user_key_chain"});
  adapters.push_back({"oceanbase_memtable_hash_btree", false,
      "TODO: native ObMemtable MVCC runtime and hash index are not integrated",
      false, false, 0, "user_key_chain"});
  return adapters;
}
std::unique_ptr<MvccTable> MakeMvccTable(std::string_view name, std::size_t key_size) {
  for (const auto& info : ListMvccAdapters()) if (info.name == name) {
    if (!info.available) throw std::invalid_argument(info.reason);
    const auto width = key_size + (info.key_encoding == "user_key_chain" ? 0 : 9);
    if (info.max_key_size && width > info.max_key_size)
      throw std::invalid_argument("MVCC key exceeds adapter limit");
#ifdef MEMTABLE_BENCH_HAVE_CSE
    if (name == "cse_arena" || name == "cse_crossbeam")
      return MakeCseTable(name == "cse_crossbeam", key_size);
#endif
    return std::make_unique<InternalTable>(MakeIndex(name), key_size);
  }
  throw std::invalid_argument("unknown MVCC adapter");
}
void HashRecord(std::string_view key, std::string_view value, std::uint64_t version,
                bool deleted, std::uint64_t* checksum) {
  auto hash = [&](unsigned char c) { *checksum = (*checksum * 1099511628211ULL) ^ c; };
  for (unsigned char c : key) hash(c);
  for (int shift = 56; shift >= 0; shift -= 8) hash(version >> shift);
  hash(deleted);
  for (unsigned char c : value) hash(c);
}
std::size_t VisibleScan(const MvccTable& table, std::string_view start,
                        std::uint64_t snapshot, std::size_t limit,
                        std::uint64_t* checksum, std::size_t* examined) {
  auto cursor = table.NewCursor();
  std::size_t rows = 0;
  for (bool valid = cursor->Seek(start); valid && rows < limit; valid = cursor->NextUser()) {
    bool visible = false;
    do {
      ++*examined;
      if (cursor->Version() <= snapshot) { visible = true; break; }
    } while (cursor->NextVersion());
    if (visible && !cursor->Deleted()) {
      HashRecord(cursor->Key(), cursor->Value(), cursor->Version(), false, checksum);
      ++rows;
    }
  }
  return rows;
}
std::size_t FlushVersions(const MvccTable& table, std::uint64_t* checksum) {
  auto cursor = table.NewCursor(true);
  std::size_t rows = 0;
  for (bool valid = cursor->Seek({}); valid; valid = cursor->Next()) {
    HashRecord(cursor->Key(), cursor->Value(), cursor->Version(), cursor->Deleted(), checksum);
    ++rows;
  }
  return rows;
}
}  // namespace memtable_bench
