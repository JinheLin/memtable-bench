#include "memtable_bench/index.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <algorithm>
#include <array>
#include <atomic>
#include <barrier>
#include <cstdint>
#include <iostream>
#include <latch>
#include <map>
#include <numeric>
#include <random>
#include <string>
#include <thread>
#include <vector>

namespace mb = memtable_bench;

namespace {
void VerifyContents(const mb::Index& index,
                    const std::map<std::string, std::string>& expected) {
  assert(index.Size() == expected.size());
  auto cursor = index.NewCursor();
  bool valid = cursor->Seek("");
  for (const auto& [key, value] : expected) {
    assert(valid && cursor->Key() == key && cursor->Value() == value);
    std::string found;
    assert(index.Get(key, &found) && found == value);
    assert(index.Contains(key));
    valid = cursor->Next();
  }
  assert(!valid && !cursor->Valid());
  assert(cursor->Key().empty() && cursor->Value().empty());
  assert(!cursor->Next());
}

void VerifyBinaryRecords(const mb::AdapterInfo& info) {
  auto index = mb::MakeIndex(info.name);
  const std::map<std::string, std::string> expected = {
      {"", ""}, {std::string("\0", 1), std::string("\0\xff", 2)},
      {std::string("\0\xff", 2), "prefix"}, {std::string("\xff", 1), "high"},
      {std::string(info.max_key_size ? std::min<std::size_t>(300, info.max_key_size) : 300, 'z'),
       std::string(513, '\xff')}};
  auto empty_cursor = index->NewCursor();
  assert(!empty_cursor->Seek("") && !empty_cursor->Next());
  empty_cursor.reset();
  for (const auto& [key, value] : expected) assert(index->Insert(key, value));
  VerifyContents(*index, expected);
  std::string missing;
  assert(!index->Get("absent", &missing));
  assert(!index->Contains("absent"));
  if (info.max_key_size) {
    bool rejected = false;
    try { index->Insert(std::string(info.max_key_size + 1, 'x'), "too long"); }
    catch (const std::length_error&) { rejected = true; }
    assert(rejected && index->Size() == expected.size());
  }
  index->Freeze();
  VerifyContents(*index, expected);
}

void VerifyLeafLowerBounds(const mb::AdapterInfo& info) {
  auto index = mb::MakeIndex(info.name);
  const std::string stored("a\0", 2);
  assert(index->Insert(stored, "leaf"));
  const std::vector<std::string> probes = {"", "a", stored, stored + '\0', "b"};
  for (int frozen = 0; frozen < 2; ++frozen) {
    auto cursor = index->NewCursor();
    for (const auto& probe : probes) {
      const bool expected = probe <= stored;
      assert(cursor->Seek(probe) == expected);
      if (expected) {
        assert(cursor->Key() == stored && cursor->Value() == "leaf");
        assert(!cursor->Next());
      }
    }
    index->Freeze();
  }
}

void VerifyManyVersions(const mb::AdapterInfo& info) {
  auto index = mb::MakeIndex(info.name);
  std::vector<std::size_t> order(info.name == "btreeolc" ? 65536 : 4096);
  std::iota(order.begin(), order.end(), 0);
  std::mt19937 rng(42);
  std::shuffle(order.begin(), order.end(), rng);
  std::map<std::string, std::string> expected;
  for (auto i : order) {
    auto key = mb::EncodeKey(i % 256, 24, true, i / 256 + 1);
    std::string value(37 + i % 100, static_cast<char>(i % 256));
    assert(index->Insert(key, value));
    expected.emplace(std::move(key), std::move(value));
  }
  VerifyContents(*index, expected);
  std::uint64_t before = 0;
  assert(index->Scan("", expected.size() + 1, &before) == expected.size());
  index->Freeze();
  VerifyContents(*index, expected);
  std::uint64_t after = 0;
  assert(index->Scan("", expected.size() + 1, &after) == expected.size());
  assert(before == after);
  auto cursor = index->NewCursor();
  for (std::size_t i = 0; i < 100; ++i) {
    const auto target = mb::EncodeKey(i, 24, true, 8);
    const auto reference = expected.lower_bound(target);
    assert(cursor->Seek(target) && cursor->Key() == reference->first);
  }
}

void VerifyUnalignedInputs(const mb::AdapterInfo& info) {
  // Byte views may start anywhere, including a 73-byte dataset stride.
  // Cover every alignment and the CRC's 2/4/8-byte tail boundaries.
  alignas(std::uint64_t) std::array<char, 128> bytes{};
  for (std::size_t i = 0; i < bytes.size(); ++i) bytes[i] = static_cast<char>(i * 37);
  for (std::size_t offset = 0; offset < 8; ++offset) {
    auto index = mb::MakeIndex(info.name);
    std::map<std::string, std::string> expected;
    for (const std::size_t length : {0, 1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 33, 64, 73, 118}) {
      const std::string_view key(bytes.data() + offset, length);
      const std::string_view value(bytes.data() + 7 - offset, 31);
      assert(index->Insert(key, value));
      expected.emplace(std::string(key), std::string(value));
      assert(index->Contains(key));
      std::string found;
      assert(index->Get(key, &found) && found == value);
      auto cursor = index->NewCursor();
      assert(cursor->Seek(key) && cursor->Key() == key && cursor->Value() == value);
    }
    index->Freeze();
    VerifyContents(*index, expected);
  }
}

void VerifyConcurrentInsertAndFreeze(const mb::AdapterInfo& info) {
  constexpr unsigned workers = 4;
  auto index = mb::MakeIndex(info.name);
  std::barrier start(workers + 1);
  std::latch first_insert(workers);
  std::atomic<std::size_t> accepted{0};
  std::vector<std::thread> threads;
  for (unsigned t = 0; t < workers; ++t) {
    threads.emplace_back([&, t] {
      start.arrive_and_wait();
      assert(index->Insert(mb::EncodeKey(t, 16, true), "seed"));
      accepted.fetch_add(1, std::memory_order_relaxed);
      first_insert.count_down();
      for (std::size_t i = 1; i <= 10000; ++i) {
        const auto key = mb::EncodeKey(t + i * workers, 16, true);
        if (!index->Insert(key, "value")) break;
        accepted.fetch_add(1, std::memory_order_relaxed);
        std::string found;
        assert(index->Get(key, &found) && found == "value");
      }
    });
  }
  start.arrive_and_wait();
  first_insert.wait();
  index->Freeze();
  for (auto& thread : threads) thread.join();
  assert(index->Size() == accepted.load());
  assert(!index->Insert("late", "value"));
  auto cursor = index->NewCursor();
  std::size_t count = 0;
  std::string previous;
  for (bool valid = cursor->Seek(""); valid; valid = cursor->Next()) {
    assert(count == 0 || previous < cursor->Key());
    previous.assign(cursor->Key());
    ++count;
  }
  assert(count == accepted.load());
}

void VerifyConcurrentDuplicates(const mb::AdapterInfo& info) {
  if (info.supports_upsert) return;
  auto index = mb::MakeIndex(info.name);
  std::barrier start(5);
  std::atomic<unsigned> accepted{0};
  std::vector<std::thread> threads;
  for (unsigned t = 0; t < 4; ++t) {
    threads.emplace_back([&] {
      start.arrive_and_wait();
      if (index->Insert("same", "value")) accepted.fetch_add(1);
    });
  }
  start.arrive_and_wait();
  for (auto& thread : threads) thread.join();
  index->Freeze();
  assert(accepted.load() == 1 && index->Size() == 1);
}

void VerifyConcurrentUpserts(const mb::AdapterInfo& info) {
  if (!info.supports_upsert) return;
  auto index = mb::MakeIndex(info.name);
  assert(index->Insert("shared", std::string(64, 'a')));
  std::barrier start(5);
  std::vector<std::thread> threads;
  for (unsigned t = 0; t < 4; ++t) {
    threads.emplace_back([&, t] {
      start.arrive_and_wait();
      for (unsigned i = 0; i < 2000; ++i) {
        if (t < 2) assert(index->Insert("shared", std::string(64, static_cast<char>('a' + t))));
        std::string found;
        assert(index->Get("shared", &found));
        assert(found == std::string(64, 'a') || found == std::string(64, 'b'));
      }
    });
  }
  start.arrive_and_wait();
  for (auto& thread : threads) thread.join();
  index->Freeze();
  assert(index->Size() == 1);
}

void VerifyConcurrentOrderedCursor(const mb::AdapterInfo& info) {
  auto index = mb::MakeIndex(info.name);
  for (unsigned i = 0; i < 512; ++i)
    assert(index->Insert(mb::EncodeKey(i, 16 + i % 32, true), "stable"));
  std::barrier start(4);
  std::vector<std::thread> threads;
  for (unsigned t = 0; t < 2; ++t) {
    threads.emplace_back([&, t] {
      start.arrive_and_wait();
      for (unsigned i = 0; i < 1500; ++i) {
        const auto id = 512 + 2 * i + t;
        const auto key = mb::EncodeKey(id, 16 + id % 32, true);
        assert(index->Insert(key, "stable"));
        std::string found;
        assert(index->Get(key, &found) && found == "stable");
      }
    });
  }
  threads.emplace_back([&] {
    start.arrive_and_wait();
    auto cursor = index->NewCursor();
    for (unsigned scan = 0; scan < 100; ++scan) {
      const auto target = mb::EncodeKey(scan * 29, 16, true);
      auto valid = cursor->Seek(target);
      std::string previous;
      for (unsigned n = 0; valid && n < 100; ++n) {
        assert(cursor->Key() >= target);
        assert(n == 0 || previous < cursor->Key());
        assert(cursor->Value() == "stable");
        previous.assign(cursor->Key());
        valid = cursor->Next();
      }
    }
  });
  start.arrive_and_wait();
  for (auto& thread : threads) thread.join();
  index->Freeze();
  assert(index->Size() == 3512);
}

void VerifyActiveCursorWithWrites(const mb::AdapterInfo& info) {
  auto index = mb::MakeIndex(info.name);
  assert(index->Insert("a", "first") && index->Insert("c", "last"));
  auto cursor = index->NewCursor();
  assert(cursor->Seek("a") && cursor->Key() == "a");
  // Holding an active cursor must not hold a native read latch that deadlocks
  // this caller's Insert or Freeze. Native frozen cursors are tested separately.
  assert(index->Insert("b", "middle"));
  // Native batch iterators may have already cached "c" before "b" arrived.
  // The cursor contract allows this; a new Seek must see the completed insert.
  assert(cursor->Next());
  if (cursor->Key() == "b") assert(cursor->Next());
  assert(cursor->Key() == "c");
  assert(!cursor->Next());
  assert(cursor->Seek("b") && cursor->Key() == "b" && cursor->Value() == "middle");
  index->Freeze();
}
}  // namespace

int main() {
  std::cout << std::unitbuf;
  const auto newer = mb::EncodeKey(7, 16, true, 9);
  const auto older = mb::EncodeKey(7, 16, true, 1);
  const auto other = mb::EncodeKey(8, 16, true, 1);
  assert(newer < older && older < other);

  for (const auto& info : mb::ListAdapters()) {
    if (!info.available) continue;
    auto index = mb::MakeIndex(info.name);
    assert(info.supports_upsert == index->SupportsUpsert());
    assert(info.key_encoding == index->KeyEncoding());
    std::string absent;
    assert(!index->Get("missing", &absent));
    assert(!index->Contains("missing"));
    const std::string binary_value("v\0x", 3);
    assert(index->Insert(other, "other"));
    assert(index->Insert(older, "old"));
    assert(index->Insert(newer, binary_value));
    assert(index->Size() == 3);
    std::string found;
    assert(index->Get(newer, &found) && found == binary_value);
    assert(index->Insert(newer, "updated") == info.supports_upsert);
    assert(index->Size() == 3);
    assert(index->Get(newer, &found));
    assert(found == (info.supports_upsert ? "updated" : binary_value));

    auto cursor = index->NewCursor();
    assert(cursor->Seek(newer) && cursor->Key() == newer);
    assert(cursor->Next() && cursor->Key() == older);
    assert(cursor->Next() && cursor->Key() == other);
    assert(!cursor->Next() && !cursor->Valid());
    std::uint64_t checksum = 0;
    assert(index->Scan(older, 1, &checksum) == 1);
    index->Freeze();
    index->Freeze();  // Idempotent and does not invalidate pre-existing cursors.
    assert(!index->Insert("late", "value"));
    assert(index->Get(other, &found) && found == "other");
    assert(cursor->Seek(older) && cursor->Key() == older);
    auto frozen = index->NewCursor();
    assert(frozen->Seek(newer) && frozen->Key() == newer);
    assert(frozen->Next() && frozen->Key() == older);
    assert(frozen->Next() && frozen->Key() == other);
    assert(!frozen->Next() && !frozen->Next());
    assert(frozen->Seek("") && frozen->Key() == newer);
    const auto gap = mb::EncodeKey(7, 16, true, 5);
    assert(frozen->Seek(gap) && frozen->Key() == older);
    assert(!frozen->Seek(mb::EncodeKey(9, 16, true)));
    VerifyBinaryRecords(info);
    VerifyLeafLowerBounds(info);
    VerifyManyVersions(info);
    VerifyUnalignedInputs(info);
    if (info.native_concurrent) {
      VerifyConcurrentInsertAndFreeze(info);
      VerifyConcurrentDuplicates(info);
      VerifyConcurrentUpserts(info);
      VerifyActiveCursorWithWrites(info);
      VerifyConcurrentOrderedCursor(info);
    }
    std::cout << info.name << " contract passed\n";
  }
}
