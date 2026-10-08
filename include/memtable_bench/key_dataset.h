#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace memtable_bench {

struct KeyConfig {
  std::size_t count = 0;
  std::size_t user_bytes = 0;
  bool internal_key = false;
  std::string layout = "random";
  std::size_t prefix_bytes = 0;
  std::size_t prefix_groups = 1;
  std::uint64_t seed = 42;
};

struct KeyStats {
  std::size_t minimum = 0, p50 = 0, p95 = 0, p99 = 0, maximum = 0;
  double mean = 0;
  std::uint64_t hash = 1469598103934665603ULL;
  std::vector<std::size_t> lcp_histogram;
};

void ValidateKeyConfig(const KeyConfig& config);
void SetInternalTrailer(char* trailer, std::uint64_t sequence);

// A single contiguous input buffer survives all timed phases. Sorting and LCP
// computation happen before index construction and do not create a second copy.
class KeyDataset {
 public:
  explicit KeyDataset(KeyConfig config);
  std::string_view Key(std::size_t id) const;
  std::string Version(std::size_t id, std::uint64_t sequence) const;
  const std::vector<std::size_t>& SortedIds() const { return sorted_; }
  const std::vector<std::size_t>& SpreadIds() const { return spread_; }
  const KeyStats& Stats() const { return stats_; }
  void WriteMetadata(const std::string& path) const;
 private:
  KeyConfig config_;
  std::size_t stride_;
  std::vector<char> bytes_;
  std::vector<std::size_t> sorted_, spread_;
  KeyStats stats_;
};

}  // namespace memtable_bench
