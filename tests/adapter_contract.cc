#include "memtable_bench/index.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <cstdint>
#include <iostream>
#include <string>

namespace mb = memtable_bench;

int main() {
  const auto newer = mb::EncodeKey(7, 16, true, 9);
  const auto older = mb::EncodeKey(7, 16, true, 1);
  const auto other = mb::EncodeKey(8, 16, true, 1);
  assert(newer < older && older < other);

  for (const auto& info : mb::ListAdapters()) {
    if (!info.available) continue;
    auto index = mb::MakeIndex(info.name);
    const std::string binary_value("v\0x", 3);
    assert(index->Insert(other, "other"));
    assert(index->Insert(older, "old"));
    assert(index->Insert(newer, binary_value));
    assert(index->Size() == 3);
    std::string found;
    assert(index->Get(newer, &found) && found == binary_value);
    assert(index->Insert(newer, "updated"));
    assert(index->Size() == 3);
    assert(index->Get(newer, &found) && found == "updated");

    auto cursor = index->NewCursor();
    assert(cursor->Seek(newer) && cursor->Key() == newer);
    assert(cursor->Next() && cursor->Key() == older);
    assert(cursor->Next() && cursor->Key() == other);
    assert(!cursor->Next() && !cursor->Valid());
    std::uint64_t checksum = 0;
    assert(index->Scan(older, 1, &checksum) == 1);
    index->Freeze();
    assert(!index->Insert("late", "value"));
    assert(index->Get(other, &found) && found == "other");
    std::cout << info.name << " contract passed\n";
  }
}
