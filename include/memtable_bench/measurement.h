#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <vector>
#include <cerrno>
#include <cstring>
#include <pthread.h>
#include <sched.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <linux/mempolicy.h>
#include <linux/perf_event.h>
namespace memtable_bench {
using Clock = std::chrono::steady_clock;
inline void ConfigureThread(const std::vector<int>& cpus, int numa_node, unsigned worker) {
  if (!cpus.empty()) {
    const int cpu = cpus[worker % cpus.size()];
    if (cpu < 0 || cpu >= CPU_SETSIZE) throw std::invalid_argument("CPU id out of range");
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    const int rc = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
    if (rc != 0) throw std::runtime_error("CPU affinity: " + std::string(std::strerror(rc)));
  }
  if (numa_node >= 0) {
    if (numa_node >= static_cast<int>(sizeof(unsigned long) * 8))
      throw std::invalid_argument("NUMA node exceeds one-word nodemask");
    const unsigned long mask = 1UL << numa_node;
    // Linux's nodemask ABI subtracts one from maxnode before reading bits.
    // Match libnuma: pass the mask's bit capacity plus one, including node 0.
    const unsigned long maxnode = sizeof(mask) * 8 + 1;
    if (syscall(SYS_set_mempolicy, MPOL_BIND, &mask, maxnode) != 0)
      throw std::runtime_error("NUMA binding: " + std::string(std::strerror(errno)));
  }
}

inline std::uint64_t ResidentBytes() {
  std::ifstream statm("/proc/self/statm");
  std::uint64_t total = 0, resident = 0;
  statm >> total >> resident;
  return resident * static_cast<std::uint64_t>(sysconf(_SC_PAGESIZE));
}

enum Counter { kCycles, kInstructions, kL1Miss, kLLCMiss, kBranchMiss, kDTLBMiss, kCount };
using Counters = std::array<std::optional<double>, kCount>;

class Perf {
 public:
  Perf() {
    static constexpr std::array<std::pair<std::uint32_t, std::uint64_t>, kCount> specs = {{
        {PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES},
        {PERF_TYPE_HARDWARE, PERF_COUNT_HW_INSTRUCTIONS},
        {PERF_TYPE_HW_CACHE, PERF_COUNT_HW_CACHE_L1D |
            (PERF_COUNT_HW_CACHE_OP_READ << 8) | (PERF_COUNT_HW_CACHE_RESULT_MISS << 16)},
        {PERF_TYPE_HW_CACHE, PERF_COUNT_HW_CACHE_LL |
            (PERF_COUNT_HW_CACHE_OP_READ << 8) | (PERF_COUNT_HW_CACHE_RESULT_MISS << 16)},
        {PERF_TYPE_HARDWARE, PERF_COUNT_HW_BRANCH_MISSES},
        {PERF_TYPE_HW_CACHE, PERF_COUNT_HW_CACHE_DTLB |
            (PERF_COUNT_HW_CACHE_OP_READ << 8) | (PERF_COUNT_HW_CACHE_RESULT_MISS << 16)}
    }};
    for (std::size_t i = 0; i < kCount; ++i) {
      perf_event_attr attr{};
      attr.size = sizeof(attr);
      attr.type = specs[i].first;
      attr.config = specs[i].second;
      attr.disabled = 1;
      attr.exclude_kernel = 1;
      attr.exclude_hv = 1;
      attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
      fds_[i] = static_cast<int>(syscall(SYS_perf_event_open, &attr, 0, -1, -1, 0));
    }
  }
  ~Perf() {
    for (int fd : fds_) if (fd >= 0) close(fd);
  }
  void Start() {
    for (int fd : fds_) if (fd >= 0) {
      ioctl(fd, PERF_EVENT_IOC_RESET, 0);
      ioctl(fd, PERF_EVENT_IOC_ENABLE, 0);
    }
  }
  Counters Stop() {
    Counters result{};
    struct Reading { std::uint64_t value, enabled, running; };
    for (std::size_t i = 0; i < kCount; ++i) if (fds_[i] >= 0) {
      ioctl(fds_[i], PERF_EVENT_IOC_DISABLE, 0);
      Reading reading{};
      if (read(fds_[i], &reading, sizeof(reading)) == sizeof(reading) && reading.running)
        result[i] = static_cast<double>(reading.value) * reading.enabled / reading.running;
    }
    return result;
  }
 private:
  std::array<int, kCount> fds_ = {-1, -1, -1, -1, -1, -1};
};

struct Sample {
  std::size_t operations = 0;
  std::size_t items = 0;
  std::uint64_t elapsed_ns = 0;
  std::uint64_t checksum = 1469598103934665603ULL;
  std::vector<std::uint64_t> latency_ns;
  Counters counters{};
};

inline std::uint64_t Nanoseconds(Clock::duration d) {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(d).count();
}

template <class Fn>
Sample Measure(std::size_t operations, Fn&& fn, Perf* external_perf = nullptr) {
  Sample sample;
  sample.operations = operations;
  sample.latency_ns.reserve(operations / 64 + 1);
  std::optional<Perf> local_perf;
  if (!external_perf) local_perf.emplace();
  Perf& perf = external_perf ? *external_perf : *local_perf;
  const auto start = Clock::now();
  perf.Start();
  for (std::size_t i = 0; i < operations; ++i) {
    if (i % 64 == 0) {
      const auto t0 = Clock::now();
      sample.items += fn(i, &sample.checksum);
      sample.latency_ns.push_back(Nanoseconds(Clock::now() - t0));
    } else {
      sample.items += fn(i, &sample.checksum);
    }
  }
  sample.counters = perf.Stop();
  sample.elapsed_ns = Nanoseconds(Clock::now() - start);
  return sample;
}

inline double Percentile(std::vector<std::uint64_t> values, double pct) {
  if (values.empty()) return 0;
  const auto pos = static_cast<std::size_t>(std::ceil(pct * values.size())) - 1;
  std::nth_element(values.begin(), values.begin() + pos, values.end());
  return values[pos];
}

inline std::string Number(double x) {
  if (!std::isfinite(x)) return "";
  std::ostringstream out;
  out << std::fixed << std::setprecision(3) << x;
  return out.str();
}

}  // namespace memtable_bench
