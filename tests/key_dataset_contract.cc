#include "memtable_bench/key_dataset.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <algorithm>
#include <cassert>
#include <iostream>
#include <map>
#include <numeric>
#include <stdexcept>
#include <string>

namespace mb = memtable_bench;

int main() {
  for (const auto& layout : {"random", "global-prefix", "group-prefix"}) {
    const std::size_t prefix = std::string(layout) == "random" ? 0 : 24;
    const std::size_t groups = std::string(layout) == "group-prefix" ? 16 : 1;
    const mb::KeyConfig config{4096, 64, true, layout, prefix, groups, 42};
    mb::KeyDataset dataset(config), repeat(config);
    assert(dataset.Stats().hash == repeat.Stats().hash);
    assert(dataset.SortedIds() == repeat.SortedIds());
    assert(dataset.SpreadIds() == repeat.SpreadIds());
    assert(std::accumulate(dataset.Stats().lcp_histogram.begin(),
                           dataset.Stats().lcp_histogram.end(), std::size_t{0}) == 4095);
    std::map<std::string, unsigned> prefix_counts;
    std::vector<std::size_t> histogram(65);
    for (std::size_t i = 0; i < config.count; ++i) {
      const auto id = dataset.SortedIds()[i];
      const auto key = dataset.Key(id);
      assert(key.size() == 73);
      const auto newest = dataset.Version(id, 100);
      assert(newest.substr(0, 64) == key.substr(0, 64));
      assert(newest < key && newest.back() == 1);
      if (prefix) ++prefix_counts[std::string(key.substr(0, prefix))];
      if (i) {
        const auto previous = dataset.Key(dataset.SortedIds()[i - 1]);
        assert(previous < key);
        std::size_t lcp = 0;
        while (lcp < 64 && previous[lcp] == key[lcp]) ++lcp;
        ++histogram[lcp];
      }
    }
    assert(histogram == dataset.Stats().lcp_histogram);
    if (prefix) {
      assert(prefix_counts.size() == groups);
      for (const auto& [key, count] : prefix_counts) assert(count == config.count / groups);
    }
    assert(dataset.Stats().p50 >= prefix && dataset.Stats().maximum < 64);
    auto ids = dataset.SpreadIds();
    std::sort(ids.begin(), ids.end());
    for (std::size_t i = 0; i < ids.size(); ++i) assert(ids[i] == i);
  }
  mb::KeyDataset narrow({4096, 8, false, "random", 0, 1, 42});
  mb::KeyDataset wide({4096, 112, true, "random", 0, 1, 42});
  assert(narrow.SortedIds() == wide.SortedIds());
  assert(narrow.SpreadIds() == wide.SpreadIds());
  for (std::size_t id = 0; id < 4096; ++id)
    assert(narrow.Key(id) == wide.Key(id).substr(0, 8));
  mb::KeyDataset singleton({1, 8, false, "random", 0, 1, 42});
  assert(singleton.Stats().mean == 0 && singleton.Stats().maximum == 0);
  for (auto config : {mb::KeyConfig{10, 8, true, "global-prefix", 1, 1, 42},
                      mb::KeyConfig{10, 64, true, "group-prefix", 24, 11, 42},
                      mb::KeyConfig{10, 64, true, "random", 1, 1, 42}}) {
    bool rejected = false;
    try { mb::ValidateKeyConfig(config); } catch (const std::invalid_argument&) { rejected = true; }
    assert(rejected);
  }
  std::cout << "Key uniqueness, balanced prefixes, LCP histogram, MVCC and stable traces verified\n";
}
