#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace memtable_bench {

// Keys and values are owned by the index. All operations use exact binary keys.
// A cursor owns its position; concurrent inserts may change subsequent results.
class Cursor {
 public:
  virtual ~Cursor() = default;
  virtual bool Seek(std::string_view key) = 0;
  virtual bool Next() = 0;
  virtual bool Valid() const = 0;
  virtual std::string_view Key() const = 0;
  virtual std::string_view Value() const = 0;
};

class Index {
 public:
  virtual ~Index() = default;
  virtual bool Insert(std::string_view key, std::string_view value) = 0;
  virtual bool Get(std::string_view key, std::string* value) const = 0;
  virtual std::unique_ptr<Cursor> NewCursor() const = 0;
  virtual std::size_t Scan(std::string_view start, std::size_t limit,
                           std::uint64_t* checksum) const;
  virtual void Freeze() = 0;
  virtual std::size_t Size() const = 0;
  virtual std::string_view ConcurrencyMode() const = 0;
};

struct AdapterInfo {
  std::string name;
  bool available;
  std::string reason;
};

std::vector<AdapterInfo> ListAdapters();
std::unique_ptr<Index> MakeIndex(std::string_view name);

// Fixed-width big-endian user id, followed by a deterministic binary suffix.
// Internal-key mode appends one's-complement big-endian sequence and a type byte.
// Therefore lexicographic order is (user id ascending, sequence descending).
std::string EncodeKey(std::uint64_t user_id, std::size_t user_key_size,
                      bool internal_key, std::uint64_t sequence = 1);

}  // namespace memtable_bench
