#pragma once

#include "memtable_bench/index.h"
#include <span>

namespace memtable_bench {

struct MvccWrite {
  std::string_view key, value;
  std::uint64_t version;
  bool deleted = false;
};
struct MvccValue {
  std::string value;
  std::uint64_t version = 0;
  bool deleted = false;
};

// One cursor position is one physical version. NextUser skips the remaining
// versions of this key. Index/table must outlive cursors and borrowed views.
class VersionCursor {
 public:
  virtual ~VersionCursor() = default;
  virtual bool Seek(std::string_view user_key) = 0;
  virtual bool NextUser() = 0;
  virtual bool NextVersion() = 0;  // false leaves the current position unchanged
  virtual bool Next() { return Valid() && (NextVersion() || NextUser()); }
  virtual bool Valid() const = 0;
  virtual std::string_view Key() const = 0;
  virtual std::string_view Value() const = 0;
  virtual std::uint64_t Version() const = 0;
  virtual bool Deleted() const = 0;
};

class MvccTable {
 public:
  virtual ~MvccTable() = default;
  // Contract: unique (key,version), versions strictly increase per key. Batch
  // submission is not transaction atomic; callers publish snapshots separately.
  virtual bool Write(std::span<const MvccWrite> batch) = 0;
  // true includes a visible tombstone; false means no version <= snapshot.
  virtual bool GetAt(std::string_view key, std::uint64_t snapshot,
                     MvccValue* result) const = 0;
  virtual std::unique_ptr<VersionCursor> NewCursor(bool flush = false) const = 0;
  virtual void Freeze() = 0;
  virtual std::size_t VersionCount() const = 0;
  virtual std::string_view Representation() const = 0;
  virtual std::string_view ConcurrencyMode() const = 0;
  virtual bool NativeBatch() const { return false; }
  // Backend accounting, not interchangeable with RSS. Zero means unavailable.
  virtual std::uint64_t RetainedBytes() const { return 0; }
};

std::vector<AdapterInfo> ListMvccAdapters();
std::unique_ptr<MvccTable> MakeMvccTable(std::string_view name, std::size_t key_size);
std::string MvccInternalKey(std::string_view user_key, std::uint64_t version, bool deleted);
void HashRecord(std::string_view key, std::string_view value, std::uint64_t version,
                bool deleted, std::uint64_t* checksum);
std::size_t VisibleScan(const MvccTable& table, std::string_view start,
                        std::uint64_t snapshot, std::size_t limit,
                        std::uint64_t* checksum, std::size_t* versions_examined);
std::size_t FlushVersions(const MvccTable& table, std::uint64_t* checksum);

}  // namespace memtable_bench
