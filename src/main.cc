#include "memtable_bench/index.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <barrier>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#ifdef __linux__
#include <cerrno>
#include <cstring>
#include <pthread.h>
#include <sched.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <linux/mempolicy.h>
#include <linux/perf_event.h>
#endif
#ifdef __APPLE__
#include <mach/mach.h>
#endif

namespace mb = memtable_bench;
using Clock = std::chrono::steady_clock;

namespace {

struct Options {
  std::string index = "std_map";
  std::string stage = "all";
  std::string output = "results.csv";
  std::string distribution = "uniform";
  std::string cpu_list;
  std::vector<int> cpus;
  int numa_node = -1;
  std::size_t keys = 100000;
  std::size_t ops = 100000;
  std::size_t key_size = 16;
  std::size_t value_size = 32;
  std::size_t scan_length = 100;
  unsigned threads = 1;
  unsigned read_percent = 80;
  std::uint64_t seed = 42;
  bool internal_key = false;
};

std::uint64_t ParseUnsigned(const std::string& s) {
  std::size_t pos = 0;
  const auto result = std::stoull(s, &pos);
  if (pos != s.size()) throw std::invalid_argument("invalid number: " + s);
  return result;
}

void PrintHelp() {
  std::cout << "memtable_bench [options]\n"
            << "  --index NAME            Adapter (see --list-indexes)\n"
            << "  --stage 1|2|3|all        Benchmark stage\n"
            << "  --keys N                 Distinct user keys (default 100000)\n"
            << "  --ops N                  Read/mixed operations (default 100000)\n"
            << "  --key-size N             User key bytes, at least 8 (default 16)\n"
            << "  --value-size N           Value bytes (default 32)\n"
            << "  --distribution uniform|sequential|zipf\n"
            << "  --threads N              Stage 2 workers (default 1)\n"
            << "  --read-percent N         Stage 2 read share, 0..100 (default 80)\n"
            << "  --scan-length N          Stage 1 scan limit (default 100)\n"
            << "  --internal-key           Append descending MVCC sequence/type\n"
            << "  --cpu-list 0,2,4         Pin workers in list order (Linux)\n"
            << "  --numa-node N            Bind thread allocations to node N (Linux)\n"
            << "  --seed N                 Reproducible workload seed (default 42)\n"
            << "  --output FILE            CSV path (default results.csv)\n";
}

Options ParseOptions(int argc, char** argv) {
  Options o;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--help") { PrintHelp(); std::exit(0); }
    if (arg == "--list-indexes") {
      for (const auto& info : mb::ListAdapters()) {
        std::cout << info.name << "\t" << (info.available ? "available" : "unavailable")
                  << "\t" << info.reason << '\n';
      }
      std::exit(0);
    }
    if (arg == "--internal-key") { o.internal_key = true; continue; }
    if (i + 1 == argc) throw std::invalid_argument("missing value for " + arg);
    const std::string value = argv[++i];
    if (arg == "--index") o.index = value;
    else if (arg == "--stage") o.stage = value;
    else if (arg == "--output") o.output = value;
    else if (arg == "--distribution") o.distribution = value;
    else if (arg == "--keys") o.keys = ParseUnsigned(value);
    else if (arg == "--ops") o.ops = ParseUnsigned(value);
    else if (arg == "--key-size") o.key_size = ParseUnsigned(value);
    else if (arg == "--value-size") o.value_size = ParseUnsigned(value);
    else if (arg == "--scan-length") o.scan_length = ParseUnsigned(value);
    else if (arg == "--threads") o.threads = ParseUnsigned(value);
    else if (arg == "--read-percent") o.read_percent = ParseUnsigned(value);
    else if (arg == "--seed") o.seed = ParseUnsigned(value);
    else if (arg == "--cpu-list") o.cpu_list = value;
    else if (arg == "--numa-node") o.numa_node = static_cast<int>(ParseUnsigned(value));
    else throw std::invalid_argument("unknown option: " + arg);
  }
  if (o.stage != "1" && o.stage != "2" && o.stage != "3" && o.stage != "all")
    throw std::invalid_argument("stage must be 1, 2, 3, or all");
  if (o.distribution != "uniform" && o.distribution != "sequential" &&
      o.distribution != "zipf") throw std::invalid_argument("unknown distribution");
  if (o.keys == 0 || o.ops == 0 || o.threads == 0 || o.scan_length == 0 ||
      o.key_size < 8 || o.read_percent > 100)
    throw std::invalid_argument("keys, ops, threads, scan-length must be positive; "
                                "key-size >= 8; read-percent <= 100");
  if (!o.cpu_list.empty()) {
    std::stringstream stream(o.cpu_list);
    std::string token;
    while (std::getline(stream, token, ',')) {
      if (token.empty()) throw std::invalid_argument("empty CPU id");
      o.cpus.push_back(static_cast<int>(ParseUnsigned(token)));
    }
  }
#ifndef __linux__
  if (!o.cpus.empty() || o.numa_node >= 0)
    throw std::invalid_argument("CPU pinning and NUMA binding require Linux");
#endif
  return o;
}

void ConfigureThread(const Options& o, unsigned worker) {
#ifdef __linux__
  if (!o.cpus.empty()) {
    const int cpu = o.cpus[worker % o.cpus.size()];
    if (cpu < 0 || cpu >= CPU_SETSIZE) throw std::invalid_argument("CPU id out of range");
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    const int rc = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
    if (rc != 0) throw std::runtime_error("CPU affinity: " + std::string(std::strerror(rc)));
  }
  if (o.numa_node >= 0) {
    if (o.numa_node >= static_cast<int>(sizeof(unsigned long) * 8))
      throw std::invalid_argument("NUMA node exceeds one-word nodemask");
    const unsigned long mask = 1UL << o.numa_node;
    if (syscall(SYS_set_mempolicy, MPOL_BIND, &mask, o.numa_node + 1) != 0)
      throw std::runtime_error("NUMA binding: " + std::string(std::strerror(errno)));
  }
#else
  (void)o; (void)worker;
#endif
}

std::uint64_t ResidentBytes() {
#ifdef __linux__
  std::ifstream statm("/proc/self/statm");
  std::uint64_t total = 0, resident = 0;
  statm >> total >> resident;
  return resident * static_cast<std::uint64_t>(sysconf(_SC_PAGESIZE));
#elif defined(__APPLE__)
  mach_task_basic_info_data_t info{};
  mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
  if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO,
                reinterpret_cast<task_info_t>(&info), &count) == KERN_SUCCESS)
    return info.resident_size;
  return 0;
#else
  return 0;
#endif
}

enum Counter { kCycles, kInstructions, kL1Miss, kLLCMiss, kBranchMiss, kDTLBMiss, kCount };
using Counters = std::array<std::optional<double>, kCount>;

class Perf {
 public:
  Perf() {
#ifdef __linux__
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
#endif
  }
  ~Perf() {
#ifdef __linux__
    for (int fd : fds_) if (fd >= 0) close(fd);
#endif
  }
  void Start() {
#ifdef __linux__
    for (int fd : fds_) if (fd >= 0) {
      ioctl(fd, PERF_EVENT_IOC_RESET, 0);
      ioctl(fd, PERF_EVENT_IOC_ENABLE, 0);
    }
#endif
  }
  Counters Stop() {
    Counters result{};
#ifdef __linux__
    struct Reading { std::uint64_t value, enabled, running; };
    for (std::size_t i = 0; i < kCount; ++i) if (fds_[i] >= 0) {
      ioctl(fds_[i], PERF_EVENT_IOC_DISABLE, 0);
      Reading reading{};
      if (read(fds_[i], &reading, sizeof(reading)) == sizeof(reading) && reading.running)
        result[i] = static_cast<double>(reading.value) * reading.enabled / reading.running;
    }
#endif
    return result;
  }
 private:
#ifdef __linux__
  std::array<int, kCount> fds_ = {-1, -1, -1, -1, -1, -1};
#endif
};

struct Sample {
  std::size_t operations = 0;
  std::size_t items = 0;
  std::uint64_t elapsed_ns = 0;
  std::uint64_t checksum = 1469598103934665603ULL;
  std::vector<std::uint64_t> latency_ns;
  Counters counters{};
};

std::uint64_t Nanoseconds(Clock::duration d) {
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

class KeyPicker {
 public:
  KeyPicker(const Options& o) : options_(o) {
    if (o.distribution == "zipf") {
      cdf_.reserve(o.keys);
      double sum = 0;
      for (std::size_t i = 0; i < o.keys; ++i) {
        sum += 1.0 / std::pow(static_cast<double>(i + 1), 1.1);
        cdf_.push_back(sum);
      }
      for (double& x : cdf_) x /= sum;
    }
  }
  std::size_t Pick(std::mt19937_64& rng, std::size_t ordinal) const {
    if (options_.distribution == "sequential") return ordinal % options_.keys;
    if (options_.distribution == "uniform") return rng() % options_.keys;
    const double u = std::generate_canonical<double, 53>(rng);
    return std::lower_bound(cdf_.begin(), cdf_.end(), u) - cdf_.begin();
  }
 private:
  const Options& options_;
  std::vector<double> cdf_;
};

std::vector<std::size_t> InsertOrder(const Options& o) {
  std::vector<std::size_t> ids(o.keys);
  std::iota(ids.begin(), ids.end(), 0);
  if (o.distribution != "sequential") {
    std::mt19937_64 rng(o.seed);
    std::shuffle(ids.begin(), ids.end(), rng);
  }
  return ids;
}

std::vector<std::size_t> ReadTrace(const Options& o, std::size_t count, std::uint64_t salt) {
  KeyPicker picker(o);
  std::mt19937_64 rng(o.seed + salt);
  std::vector<std::size_t> ids(count);
  for (std::size_t i = 0; i < count; ++i) ids[i] = picker.Pick(rng, i);
  return ids;
}

std::string Value(const Options& o) {
  std::string value(o.value_size, '\0');
  for (std::size_t i = 0; i < value.size(); ++i)
    value[i] = static_cast<char>((i * 131 + 17) & 0xff);
  return value;
}

double Percentile(std::vector<std::uint64_t> values, double pct) {
  if (values.empty()) return 0;
  const auto pos = static_cast<std::size_t>(std::ceil(pct * values.size())) - 1;
  std::nth_element(values.begin(), values.begin() + pos, values.end());
  return values[pos];
}

std::string Number(double x) {
  if (!std::isfinite(x)) return "";
  std::ostringstream out;
  out << std::fixed << std::setprecision(3) << x;
  return out.str();
}

class Csv {
 public:
  explicit Csv(const std::string& path) {
    std::ifstream existing(path);
    const bool has_content = existing && existing.peek() != std::ifstream::traits_type::eof();
    out_.open(path, std::ios::app);
    if (!out_) throw std::runtime_error("cannot open CSV: " + path);
    if (!has_content) out_ << "run_id,index,adapter_mode,stage,phase,threads,keys,ops,items_scanned,"
      "key_size,value_size,internal_key,distribution,read_percent,scan_length,cpu_list,numa_node,"
      "elapsed_ns,throughput_ops_s,items_per_s,latency_p50_ns,latency_p95_ns,latency_p99_ns,"
      "cycles_per_op,instructions_per_op,ipc,l1d_miss_per_op,llc_miss_per_op,"
      "branch_miss_per_op,dtlb_miss_per_op,rss_before_bytes,rss_after_bytes,"
      "rss_delta_bytes,bytes_per_key,checksum\n";
  }

  void Write(const Options& o, std::string_view adapter_mode, std::size_t index_size, int stage,
             std::string_view phase, const Sample& s,
             std::uint64_t before, std::uint64_t after, unsigned threads) {
    const double secs = static_cast<double>(s.elapsed_ns) / 1e9;
    const auto per_op = [&](Counter c) -> std::string {
      return s.counters[c] && s.operations ? Number(*s.counters[c] / s.operations) : "";
    };
    const std::string ipc = s.counters[kCycles] && s.counters[kInstructions] &&
      *s.counters[kCycles] > 0 ? Number(*s.counters[kInstructions] / *s.counters[kCycles]) : "";
    const std::int64_t delta = static_cast<std::int64_t>(after) - before;
    const double bytes_per_key = index_size ? static_cast<double>(delta) / index_size : 0;
    out_ << run_id_ << ',' << o.index << ',' << adapter_mode << ',' << stage
         << ',' << phase << ',' << threads << ',' << o.keys << ',' << s.operations << ','
         << s.items << ',' << o.key_size << ',' << o.value_size << ',' << o.internal_key
         << ',' << o.distribution << ',' << o.read_percent << ',' << o.scan_length << ','
         << '"' << o.cpu_list << '"' << ',';
    if (o.numa_node >= 0) out_ << o.numa_node;
    out_ << ',' << s.elapsed_ns << ',' << Number(s.operations / secs) << ','
         << Number(s.items / secs) << ',' << Number(Percentile(s.latency_ns, .50)) << ','
         << Number(Percentile(s.latency_ns, .95)) << ','
         << Number(Percentile(s.latency_ns, .99)) << ',' << per_op(kCycles) << ','
         << per_op(kInstructions) << ',' << ipc << ',' << per_op(kL1Miss) << ','
         << per_op(kLLCMiss) << ',' << per_op(kBranchMiss) << ',' << per_op(kDTLBMiss)
         << ',' << before << ',' << after << ',' << delta << ','
         << Number(bytes_per_key) << ',' << s.checksum << '\n';
    out_.flush();
    std::cout << "stage " << stage << " " << phase << ": " << s.operations << " ops, "
              << Number(s.operations / secs) << " ops/s, RSS delta " << delta << " B\n";
  }

 private:
  std::ofstream out_;
  std::uint64_t run_id_ = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
};

void Prefill(mb::Index& index, const Options& o, const std::vector<std::size_t>& order,
             std::string_view value) {
  for (std::size_t id : order) {
    if (!index.Insert(mb::EncodeKey(id, o.key_size, o.internal_key), value))
      throw std::runtime_error("prefill insert rejected");
  }
  if (index.Size() != o.keys) throw std::runtime_error("prefill size mismatch");
}

void Stage1(const Options& o, Csv& csv) {
  auto order = InsertOrder(o);
  const auto reads = ReadTrace(o, o.ops, 1);
  const auto scan_starts = ReadTrace(o, std::max<std::size_t>(1, o.ops / o.scan_length), 2);
  const std::string value = Value(o);
  const auto before = ResidentBytes();
  auto index = mb::MakeIndex(o.index);
  const auto inserted = Measure(order.size(), [&](std::size_t i, std::uint64_t*) {
    if (!index->Insert(mb::EncodeKey(order[i], o.key_size, o.internal_key), value))
      throw std::runtime_error("insert rejected");
    return 0U;
  });
  const auto after_insert = ResidentBytes();
  if (index->Size() != o.keys) throw std::runtime_error("stage 1 size mismatch");
  csv.Write(o, index->ConcurrencyMode(), index->Size(), 1, "insert", inserted, before, after_insert, 1);

  const auto get = Measure(reads.size(), [&](std::size_t i, std::uint64_t* hash) {
    std::string found;
    if (!index->Get(mb::EncodeKey(reads[i], o.key_size, o.internal_key), &found))
      throw std::runtime_error("expected key absent");
    *hash = (*hash * 1099511628211ULL) ^ static_cast<unsigned char>(found.empty() ? 0 : found[0]);
    return 0U;
  });
  csv.Write(o, index->ConcurrencyMode(), index->Size(), 1, "get", get, before, ResidentBytes(), 1);

  // Freeze outside the timed scan so every adapter can use a stable native
  // iterator. The lifecycle stage measures Freeze separately.
  index->Freeze();
  const auto scan = Measure(scan_starts.size(), [&](std::size_t i, std::uint64_t* hash) {
    return index->Scan(mb::EncodeKey(scan_starts[i], o.key_size, o.internal_key),
                       o.scan_length, hash);
  });
  csv.Write(o, index->ConcurrencyMode(), index->Size(), 1, "scan", scan, before, ResidentBytes(), 1);
}

struct MixedOp { std::size_t id; bool write; };

void Stage2(const Options& o, Csv& csv) {
  auto order = InsertOrder(o);
  const std::string value = Value(o);
  auto index = mb::MakeIndex(o.index);
  Prefill(*index, o, order, value);
  KeyPicker picker(o);
  std::vector<std::vector<MixedOp>> traces(o.threads);
  for (unsigned t = 0; t < o.threads; ++t) {
    std::mt19937_64 rng(o.seed + 1000 + t);
    const std::size_t count = o.ops / o.threads + (t < o.ops % o.threads);
    auto& trace = traces[t];
    trace.reserve(count);
    for (std::size_t i = 0; i < count; ++i)
      trace.push_back({picker.Pick(rng, i), rng() % 100 >= o.read_percent});
  }
  const auto before = ResidentBytes();

  std::vector<Sample> samples(o.threads);
  std::vector<std::exception_ptr> errors(o.threads);
  Clock::time_point wall_start;
  std::barrier start_line(static_cast<std::ptrdiff_t>(o.threads + 1),
                          [&] { wall_start = Clock::now(); });
  std::vector<std::thread> workers;
  workers.reserve(o.threads);
  for (unsigned t = 0; t < o.threads; ++t) {
    workers.emplace_back([&, t] {
      try {
        ConfigureThread(o, t);
      } catch (...) { errors[t] = std::current_exception(); }
      Perf perf;
      start_line.arrive_and_wait();
      if (errors[t]) return;
      try {
        samples[t] = Measure(traces[t].size(), [&](std::size_t i, std::uint64_t* hash) {
          const auto& op = traces[t][i];
          if (op.write) {
            // Unique sequence makes each MVCC write an insertion.
            const std::uint64_t sequence = o.internal_key ? 2 + t * o.ops + i : 1;
            if (!index->Insert(mb::EncodeKey(op.id, o.key_size, o.internal_key, sequence), value))
              throw std::runtime_error("mixed insert rejected");
          } else {
            std::string found;
            if (!index->Get(mb::EncodeKey(op.id, o.key_size, o.internal_key), &found))
              throw std::runtime_error("mixed get missed prefill key");
            *hash = (*hash * 1099511628211ULL) ^
                    static_cast<unsigned char>(found.empty() ? 0 : found[0]);
          }
          return 0U;
        }, &perf);
      } catch (...) { errors[t] = std::current_exception(); }
    });
  }
  start_line.arrive_and_wait();
  for (auto& worker : workers) worker.join();
  const auto wall_ns = Nanoseconds(Clock::now() - wall_start);
  for (const auto& error : errors) if (error) std::rethrow_exception(error);

  Sample aggregate;
  aggregate.operations = o.ops;
  aggregate.elapsed_ns = wall_ns;
  for (const auto& s : samples) {
    aggregate.latency_ns.insert(aggregate.latency_ns.end(),
                                s.latency_ns.begin(), s.latency_ns.end());
    aggregate.checksum ^= s.checksum;
  }
  for (std::size_t c = 0; c < kCount; ++c) {
    double total = 0;
    bool all_available = true;
    for (const auto& s : samples) {
      if (!s.counters[c]) { all_available = false; break; }
      total += *s.counters[c];
    }
    if (all_available) aggregate.counters[c] = total;
  }
  csv.Write(o, index->ConcurrencyMode(), index->Size(), 2, "mixed", aggregate,
            before, ResidentBytes(), o.threads);
}

void Stage3(const Options& o, Csv& csv) {
  auto order = InsertOrder(o);
  const std::string value = Value(o);
  const auto before = ResidentBytes();
  auto index = mb::MakeIndex(o.index);
  const auto inserted = Measure(order.size(), [&](std::size_t i, std::uint64_t*) {
    if (!index->Insert(mb::EncodeKey(order[i], o.key_size, o.internal_key), value))
      throw std::runtime_error("lifecycle insert rejected");
    return 0U;
  });
  const auto after_insert = ResidentBytes();
  if (index->Size() != o.keys) throw std::runtime_error("lifecycle size mismatch");
  csv.Write(o, index->ConcurrencyMode(), index->Size(), 3, "insert", inserted,
            before, after_insert, 1);

  const auto frozen = Measure(1, [&](std::size_t, std::uint64_t*) {
    index->Freeze();
    return 0U;
  });
  csv.Write(o, index->ConcurrencyMode(), index->Size(), 3, "freeze", frozen,
            before, ResidentBytes(), 1);

  std::string previous;
  const auto flush = Measure(1, [&](std::size_t, std::uint64_t* hash) {
    auto cursor = index->NewCursor();
    std::size_t count = 0;
    for (bool valid = cursor->Seek(""); valid; valid = cursor->Next()) {
      if (count && !(previous < cursor->Key()))
        throw std::runtime_error("scan is not strictly ordered");
      previous.assign(cursor->Key());
      for (unsigned char byte : cursor->Key()) *hash = (*hash * 1099511628211ULL) ^ byte;
      for (unsigned char byte : cursor->Value()) *hash = (*hash * 1099511628211ULL) ^ byte;
      ++count;
    }
    return count;
  });
  if (flush.items != o.keys) throw std::runtime_error("flush count mismatch");
  csv.Write(o, index->ConcurrencyMode(), index->Size(), 3, "ordered_flush", flush,
            before, ResidentBytes(), 1);

  const std::string adapter_mode(index->ConcurrencyMode());
  const auto index_size = index->Size();
  const auto destroyed = Measure(1, [&](std::size_t, std::uint64_t*) {
    index.reset();
    return 0U;
  });
  csv.Write(o, adapter_mode, index_size, 3, "destroy", destroyed,
            after_insert, ResidentBytes(), 1);
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Options o = ParseOptions(argc, argv);
    // Fail before creating output for a requested but unavailable adapter.
    const auto adapters = mb::ListAdapters();
    const auto selected = std::find_if(adapters.begin(), adapters.end(),
                                       [&](const mb::AdapterInfo& info) {
                                         return info.name == o.index;
                                       });
    if (selected == adapters.end() || !selected->available)
      throw std::invalid_argument("adapter unavailable: " + o.index +
                                  "; run --list-indexes for details");
    if (!selected->supports_upsert && !o.internal_key && o.read_percent < 100 &&
        (o.stage == "2" || o.stage == "all"))
      throw std::invalid_argument(o.index + " is append-only; stage 2 writes require "
                                  "--internal-key (or use --read-percent 100)");
    ConfigureThread(o, 0);
    Csv csv(o.output);
    if (o.stage == "1" || o.stage == "all") Stage1(o, csv);
    if (o.stage == "2" || o.stage == "all") Stage2(o, csv);
    if (o.stage == "3" || o.stage == "all") Stage3(o, csv);
  } catch (const std::exception& e) {
    std::cerr << "error: " << e.what() << '\n';
    return 1;
  }
}
