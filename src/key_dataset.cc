#include "memtable_bench/key_dataset.h"
#include "memtable_bench/index.h"

#include <algorithm>
#include <fstream>
#include <iomanip>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <utility>

namespace memtable_bench {
namespace {
// Each step is a bijection on uint64. Distinct IDs therefore have distinct
// 8-byte suffixes, without collision retries or a hidden increasing-ID prefix.
std::uint64_t Permute(std::uint64_t x) {
  x ^= x >> 30;
  x *= 0xbf58476d1ce4e5b9ULL;
  x ^= x >> 27;
  x *= 0x94d049bb133111ebULL;
  return x ^ (x >> 31);
}
void RandomBytes(char* out, std::size_t length, std::uint64_t id, std::uint64_t seed) {
  for (std::size_t offset = 0; offset < length; offset += 8) {
    const auto word = Permute(id ^ (seed + offset * 0x9e3779b97f4a7c15ULL));
    for (std::size_t j = 0; j < std::min<std::size_t>(8, length - offset); ++j)
      out[offset + j] = static_cast<char>(word >> (56 - 8 * j));
  }
}
std::size_t Quantile(const std::vector<std::size_t>& histogram, std::size_t pairs,
                     double fraction) {
  const auto rank = static_cast<std::size_t>(fraction * (pairs - 1));
  std::size_t cumulative = 0;
  for (std::size_t i = 0; i < histogram.size(); ++i) {
    cumulative += histogram[i];
    if (cumulative > rank) return i;
  }
  return 0;
}
}  // namespace

void ValidateKeyConfig(const KeyConfig& c) {
  if (!c.count || c.user_bytes < 8 || c.user_bytes > std::numeric_limits<std::size_t>::max() - 9)
    throw std::invalid_argument("positive key count and user key size >= 8 required");
  if (c.layout != "legacy" && c.layout != "random" && c.layout != "global-prefix" &&
      c.layout != "group-prefix") throw std::invalid_argument("unknown key layout");
  if (c.prefix_bytes > c.user_bytes - 8)
    throw std::invalid_argument("prefix must leave at least 8 unique suffix bytes");
  if (c.layout == "legacy" || c.layout == "random") {
    if (c.prefix_bytes || c.prefix_groups != 1)
      throw std::invalid_argument("random/legacy keys require prefix-bytes=0 and prefix-groups=1");
  } else if (c.layout == "global-prefix") {
    if (!c.prefix_bytes || c.prefix_groups != 1)
      throw std::invalid_argument("global-prefix requires positive prefix-bytes and one group");
  } else if (c.prefix_bytes < 8 || c.prefix_groups < 2 || c.prefix_groups > c.count) {
    throw std::invalid_argument("group-prefix requires >=8 prefix bytes and 2..keys groups");
  }
}

void SetInternalTrailer(char* trailer, std::uint64_t sequence) {
  const auto inverse = ~sequence;
  for (unsigned i = 0; i < 8; ++i) trailer[i] = static_cast<char>(inverse >> (56 - 8 * i));
  trailer[8] = 1;
}

KeyDataset::KeyDataset(KeyConfig config)
    : config_(std::move(config)), stride_(config_.user_bytes + (config_.internal_key ? 9 : 0)) {
  ValidateKeyConfig(config_);
  if (config_.count > bytes_.max_size() / stride_) throw std::length_error("dataset size overflow");
  bytes_.resize(config_.count * stride_);
  sorted_.resize(config_.count);
  std::iota(sorted_.begin(), sorted_.end(), 0);
  for (std::size_t id = 0; id < config_.count; ++id) {
    char* destination = bytes_.data() + id * stride_;
    if (config_.layout == "legacy") {
      const auto key = EncodeKey(id, config_.user_bytes, config_.internal_key);
      std::copy(key.begin(), key.end(), destination);
    } else {
      if (config_.prefix_bytes) {
        const auto group = config_.layout == "group-prefix" ? id % config_.prefix_groups : 0;
        RandomBytes(destination, config_.prefix_bytes, group, config_.seed ^ 0xa5a5a5a5a5a5a5a5ULL);
      }
      RandomBytes(destination + config_.prefix_bytes, config_.user_bytes - config_.prefix_bytes,
                  id, config_.seed);
      if (config_.internal_key) SetInternalTrailer(destination + config_.user_bytes, 1);
    }
    for (unsigned char byte : Key(id)) stats_.hash = (stats_.hash ^ byte) * 1099511628211ULL;
  }
  std::sort(sorted_.begin(), sorted_.end(), [&](auto a, auto b) { return Key(a) < Key(b); });
  stats_.lcp_histogram.resize(config_.user_bytes + 1);
  std::size_t sum = 0;
  for (std::size_t i = 1; i < sorted_.size(); ++i) {
    const auto a = Key(sorted_[i - 1]).substr(0, config_.user_bytes);
    const auto b = Key(sorted_[i]).substr(0, config_.user_bytes);
    if (a == b) throw std::runtime_error("duplicate generated user key");
    std::size_t length = 0;
    while (length < a.size() && a[length] == b[length]) ++length;
    ++stats_.lcp_histogram[length];
    sum += length;
  }
  if (config_.count > 1) {
    const auto pairs = config_.count - 1;
    stats_.minimum = Quantile(stats_.lcp_histogram, pairs, 0);
    stats_.p50 = Quantile(stats_.lcp_histogram, pairs, .50);
    stats_.p95 = Quantile(stats_.lcp_histogram, pairs, .95);
    stats_.p99 = Quantile(stats_.lcp_histogram, pairs, .99);
    stats_.maximum = Quantile(stats_.lcp_histogram, pairs, 1);
    stats_.mean = static_cast<double>(sum) / pairs;
  }
  spread_.resize(config_.count);
  std::iota(spread_.begin(), spread_.end(), 0);
  std::mt19937_64 random(config_.seed ^ 0xd1b54a32d192ed03ULL);
  std::shuffle(spread_.begin(), spread_.end(), random);
}

std::string_view KeyDataset::Key(std::size_t id) const {
  return {bytes_.data() + id * stride_, stride_};
}
std::string KeyDataset::Version(std::size_t id, std::uint64_t sequence) const {
  if (!config_.internal_key) throw std::logic_error("versions require InternalKey");
  std::string key(Key(id));
  SetInternalTrailer(key.data() + config_.user_bytes, sequence);
  return key;
}
void KeyDataset::WriteMetadata(const std::string& path) const {
  std::ofstream out(path);
  if (!out) throw std::runtime_error("cannot open dataset metadata: " + path);
  out << "{\n  \"layout\": \"" << config_.layout << "\",\n  \"seed\": " << config_.seed
      << ",\n  \"keys\": " << config_.count << ",\n  \"user_key_bytes\": " << config_.user_bytes
      << ",\n  \"logical_key_bytes\": " << stride_ << ",\n  \"prefix_bytes\": " << config_.prefix_bytes
      << ",\n  \"prefix_groups\": " << config_.prefix_groups
      << ",\n  \"dataset_hash_fnv1a64\": \"" << stats_.hash << "\",\n"
      << "  \"lcp_scope\": \"sorted adjacent distinct user keys; MVCC trailer excluded\",\n"
      << "  \"lcp_pairs\": " << config_.count - 1 << ",\n  \"lcp_min\": " << stats_.minimum
      << ",\n  \"lcp_p50\": " << stats_.p50 << ",\n  \"lcp_p95\": " << stats_.p95
      << ",\n  \"lcp_p99\": " << stats_.p99 << ",\n  \"lcp_max\": " << stats_.maximum
      << ",\n  \"lcp_mean\": " << std::setprecision(12) << stats_.mean
      << ",\n  \"lcp_histogram\": [";
  for (std::size_t i = 0; i < stats_.lcp_histogram.size(); ++i) {
    if (i) out << ',';
    out << stats_.lcp_histogram[i];
  }
  out << "]\n}\n";
  if (!out) throw std::runtime_error("writing dataset metadata failed");
}
}  // namespace memtable_bench
