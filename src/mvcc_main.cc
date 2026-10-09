#include "memtable_bench/mvcc.h"
#include "memtable_bench/key_dataset.h"
#include "memtable_bench/measurement.h"

#include <atomic>
#include <barrier>
#include <climits>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <thread>

namespace mb = memtable_bench;
namespace {
struct Options {
  std::string index = "rocksdb_inlineskiplist", stage = "all", output = "mvcc-results.csv";
  std::string layout = "random", distribution = "uniform", cpu_list;
  std::size_t keys = 10000, versions = 4, ops = 20000, key_size = 16, value_size = 32;
  std::size_t batch_size = 32, snapshot_lag = 2, scan_length = 100;
  std::size_t scan_ops = 1024;
  std::size_t prefix_bytes = 0, prefix_groups = 1;
  unsigned threads = 1, read_percent = 80, scan_percent = 10;
  unsigned delete_percent = 10, miss_percent = 10;
  std::uint64_t seed = 42;
  int numa_node = -1;
  std::vector<int> cpus;
};
std::size_t Unsigned(std::string_view value) {
  if (value.empty() || value.find_first_not_of("0123456789") != value.npos)
    throw std::invalid_argument("invalid unsigned integer");
  const auto result = std::stoull(std::string(value));
  if (result > SIZE_MAX) throw std::invalid_argument("integer too large");
  return result;
}
void Help() {
  std::cout << "mvcc_bench: snapshot semantics over InternalKeys or native version chains\n"
    "  --index NAME --list-indexes --stage 1|2|3|all --output FILE\n"
    "  --keys N --versions N --ops N --key-size N --value-size N\n"
    "  --batch-size N           Entries per Write submission (not atomic transactions)\n"
    "  --snapshot-lag N         Completed version rounds behind latest, 0..versions\n"
    "  --delete-percent N --miss-percent N --scan-percent N (0..100)\n"
    "  --read-percent N         Stage 2 read requests / (reads + written versions)\n"
    "  --threads N              Stage 2: 1 mixed worker or 1 writer + N-1 readers\n"
    "  --distribution uniform|zipf|sequential (Zipf theta 1.1, spread key ranks)\n"
    "  --key-layout random|global-prefix|group-prefix|legacy\n"
    "  --prefix-bytes N --prefix-groups N --seed N\n"
    "  --scan-length N          Visible live rows, not physical version entries\n"
    "  --scan-ops N             Stage 1 scan calls (default min(ops,1024))\n"
    "  --cpu-list 2,3,4 --numa-node N (Linux)\n";
}
Options Parse(int argc, char** argv) {
  Options o;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--help") { Help(); std::exit(0); }
    if (arg == "--list-indexes") {
      for (const auto& info : mb::ListMvccAdapters())
        std::cout << info.name << '\t' << (info.available ? "available" : "unavailable")
                  << '\t' << info.reason << "\tnative_concurrent=" << info.native_concurrent
                  << "\tkey_encoding=" << info.key_encoding << '\n';
      std::exit(0);
    }
    if (++i == argc) throw std::invalid_argument("missing value: " + arg);
    const std::string value = argv[i];
    if (arg == "--index") o.index = value;
    else if (arg == "--stage") o.stage = value;
    else if (arg == "--output") o.output = value;
    else if (arg == "--key-layout") o.layout = value;
    else if (arg == "--distribution") o.distribution = value;
    else if (arg == "--cpu-list") o.cpu_list = value;
    else {
      const auto n = Unsigned(value);
      if (arg == "--keys") o.keys = n;
      else if (arg == "--versions") o.versions = n;
      else if (arg == "--ops") o.ops = n;
      else if (arg == "--key-size") o.key_size = n;
      else if (arg == "--value-size") o.value_size = n;
      else if (arg == "--batch-size") o.batch_size = n;
      else if (arg == "--snapshot-lag") o.snapshot_lag = n;
      else if (arg == "--scan-length") o.scan_length = n;
      else if (arg == "--scan-ops") o.scan_ops = n;
      else if (arg == "--prefix-bytes") o.prefix_bytes = n;
      else if (arg == "--prefix-groups") o.prefix_groups = n;
      else if (arg == "--seed") o.seed = n;
      else if (arg == "--numa-node") {
        if (n > INT_MAX) throw std::invalid_argument("NUMA id out of range");
        o.numa_node = static_cast<int>(n);
      } else if (arg == "--threads") {
        if (n > 256) throw std::invalid_argument("threads must be <= 256");
        o.threads = n;
      } else {
        if (n > 100) throw std::invalid_argument("percentage out of range or unknown option: " + arg);
        if (arg == "--read-percent") o.read_percent = n;
        else if (arg == "--scan-percent") o.scan_percent = n;
        else if (arg == "--delete-percent") o.delete_percent = n;
        else if (arg == "--miss-percent") o.miss_percent = n;
        else throw std::invalid_argument("unknown option: " + arg);
      }
    }
  }
  if (o.stage != "1" && o.stage != "2" && o.stage != "3" && o.stage != "all")
    throw std::invalid_argument("stage must be 1, 2, 3, or all");
  if (!o.keys || !o.versions || !o.ops || !o.threads || !o.batch_size || !o.scan_length || !o.scan_ops ||
      o.key_size < 8 || o.snapshot_lag > o.versions)
    throw std::invalid_argument("positive sizes required; key-size >= 8; snapshot-lag <= versions");
  if (o.keys > SIZE_MAX/2 || o.versions > (UINT64_MAX-o.ops)/o.keys ||
      o.value_size > UINT32_MAX-10)
    throw std::invalid_argument("dataset or version space overflow");
  if (o.distribution != "uniform" && o.distribution != "zipf" && o.distribution != "sequential")
    throw std::invalid_argument("unknown distribution");
  bool found = false;
  for (const auto& info : mb::ListMvccAdapters()) if (info.name == o.index) {
    found = true;
    if (!info.available) throw std::invalid_argument(info.reason);
    if ((o.stage == "2" || o.stage == "all") && o.threads > 1 && !info.native_concurrent)
      throw std::invalid_argument("adapter lacks native concurrency; use --threads 1");
    if (info.max_key_size && o.key_size + (info.key_encoding == "user_key_chain" ? 0 : 9) > info.max_key_size)
      throw std::invalid_argument("key size exceeds adapter limit");
  }
  if (!found) throw std::invalid_argument("unknown adapter");
  if (o.threads > 1 && !o.read_percent)
    throw std::invalid_argument("SWMR requires readers; write-only workload uses --threads 1");
  if ((o.stage == "2" || o.stage == "all") && o.ops < o.threads)
    throw std::invalid_argument("ops must be >= threads");
  if (!o.cpu_list.empty()) {
    std::stringstream input(o.cpu_list);
    std::string token;
    while (std::getline(input, token, ',')) {
      const auto id = Unsigned(token);
      if (id > INT_MAX) throw std::invalid_argument("CPU id out of range");
      o.cpus.push_back(id);
    }
  }
  mb::ValidateKeyConfig({o.keys*2, o.key_size, false, o.layout, o.prefix_bytes, o.prefix_groups, o.seed});
  return o;
}

constexpr std::uint64_t kHash = 1469598103934665603ULL;
std::uint64_t Mix(std::uint64_t x) {
  x += 0x9e3779b97f4a7c15ULL;
  x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
  x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
  return x ^ (x >> 31);
}
struct Request { std::size_t id; bool scan = false; };
struct Stats {
  std::size_t gets = 0, scans = 0, writes = 0, hits = 0, tombstones = 0, misses = 0;
  std::size_t versions_tested = 0;
};
struct Fixture {
  const Options& o;
  mb::KeyDataset keys;
  std::vector<std::string> values;
  std::vector<mb::MvccWrite> load, writes;
  std::vector<Request> reads;
  std::vector<Request> scans;
  std::array<std::uint64_t,4> read_checks{};
  std::vector<std::size_t> sorted_present;
  std::vector<double> cdf;

  explicit Fixture(const Options& options) : o(options),
    keys({o.keys*2, o.key_size, false, o.layout, o.prefix_bytes, o.prefix_groups, o.seed}) {
    values.reserve(o.versions + 1);
    for (std::size_t round = 0; round <= o.versions; ++round) {
      std::string value(o.value_size, '\0');
      for (std::size_t j = 0; j < value.size(); ++j) value[j] = static_cast<char>(Mix(o.seed+round*131+j));
      values.push_back(std::move(value));
    }
    std::vector<std::size_t> order(o.keys);
    std::iota(order.begin(), order.end(), 0);
    std::mt19937_64 rng(o.seed);
    std::shuffle(order.begin(), order.end(), rng);
    load.reserve(o.keys*o.versions);
    for (std::size_t round = 0; round < o.versions; ++round) for (auto id : order) {
      const bool deleted = Deleted(id, round);
      load.push_back({keys.Key(id), deleted ? std::string_view{} : values[round],
                      round*o.keys+id+1, deleted});
    }
    for (auto id : keys.SortedIds()) if (id < o.keys) sorted_present.push_back(id);
    if (o.distribution == "zipf") {
      double sum = 0;
      for (std::size_t i = 0; i < o.keys; ++i) { sum += 1.0/std::pow(i+1, 1.1); cdf.push_back(sum); }
      for (double& p : cdf) p /= sum;
    }
    reads.reserve(o.ops);
    for (std::size_t i = 0; i < o.ops; ++i) {
      auto id = Pick(rng, i);
      const bool scan = rng()%100 < o.scan_percent;
      if (!scan && rng()%100 < o.miss_percent) id += o.keys;
      reads.push_back({id, scan});
    }
    const auto count = o.ops - o.ops/100*o.read_percent - (o.ops%100)*o.read_percent/100;
    writes.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
      const auto id = Pick(rng, i);
      const bool deleted = Mix(o.seed+i+991)%100 < o.delete_percent;
      writes.push_back({keys.Key(id), deleted ? std::string_view{} : values.back(),
                        o.keys*o.versions+i+1, deleted});
    }
    scans.reserve(std::min(o.ops,o.scan_ops));
    for (std::size_t i=0;i<std::min(o.ops,o.scan_ops);++i) scans.push_back({reads[i].id%o.keys,true});
    read_checks={ExpectedReads(reads,Snapshot(true),false),ExpectedReads(reads,Snapshot(),false),
                 ExpectedReads(scans,Snapshot(true),true),ExpectedReads(scans,Snapshot(),true)};
  }
  bool Deleted(std::size_t id, std::size_t round) const {
    // Seed initial live rows, then permit deletes and resurrection in any round.
    return round != 0 && Mix(o.seed+id*131+round*7919)%100 < o.delete_percent;
  }
  std::size_t Pick(std::mt19937_64& rng, std::size_t ordinal) const {
    if (o.distribution == "sequential") return sorted_present[ordinal%o.keys];
    if (cdf.empty()) return rng()%o.keys;
    const auto rank = std::lower_bound(cdf.begin(), cdf.end(), std::generate_canonical<double,53>(rng))-cdf.begin();
    // IDs are independently generated binary keys; popular ranks are spread.
    return rank;
  }
  std::uint64_t Snapshot(bool latest = false) const { return (o.versions-(latest ? 0 : o.snapshot_lag))*o.keys; }
  bool Expected(std::size_t id, std::uint64_t snapshot, mb::MvccValue* value) const {
    if (id >= o.keys || snapshot < id+1) return false;
    const auto round = std::min<std::uint64_t>((snapshot-id-1)/o.keys, o.versions-1);
    value->version = round*o.keys+id+1;
    value->deleted = Deleted(id, round);
    value->value = value->deleted ? std::string_view{} : std::string_view(values[round]);
    return true;
  }
  std::uint64_t ExpectedReads(std::span<const Request> trace, std::uint64_t snapshot, bool scans) const {
    std::uint64_t hash = kHash;
    mb::MvccValue value;
    for (const auto& request : trace) {
      if (scans && request.scan) {
        auto it = std::lower_bound(sorted_present.begin(), sorted_present.end(), keys.Key(request.id),
          [&](auto id, auto key) { return keys.Key(id) < key; });
        std::size_t rows = 0;
        for (; it != sorted_present.end() && rows < o.scan_length; ++it)
          if (Expected(*it, snapshot, &value) && !value.deleted) {
            mb::HashRecord(keys.Key(*it), value.value, value.version, false, &hash); ++rows;
          }
      } else {
        const bool found = Expected(request.id, snapshot, &value);
        mb::HashRecord(keys.Key(request.id), found ? value.value : std::string_view{},
                       found ? value.version : 0, found && value.deleted, &hash);
      }
    }
    return hash;
  }
  std::size_t Read(const mb::MvccTable& table, const Request& request, std::uint64_t snapshot,
                   bool scans, Stats* stats, std::uint64_t* hash) const {
    if (scans && request.scan) {
      ++stats->scans;
      return mb::VisibleScan(table, keys.Key(request.id), snapshot, o.scan_length, hash, &stats->versions_tested);
    }
    ++stats->gets;
    mb::MvccValue result;
    const bool found = table.GetAt(keys.Key(request.id), snapshot, &result);
    if (!found) ++stats->misses;
    else if (result.deleted) ++stats->tombstones;
    else ++stats->hits;
    mb::HashRecord(keys.Key(request.id), found ? result.value : std::string_view{},
                   found ? result.version : 0, found && result.deleted, hash);
    return found && !result.deleted;
  }
};

class Csv {
 public:
  explicit Csv(const Options& o) {
    std::ifstream existing(o.output);
    const bool has_content = existing && existing.peek() != std::ifstream::traits_type::eof();
    if (has_content) {
      std::string header; std::getline(existing, header);
      if (header != kHeader) throw std::invalid_argument("CSV schema differs; use new output file");
    }
    out_.open(o.output, std::ios::app);
    if (!out_) throw std::runtime_error("cannot open output");
    if (!has_content) out_ << kHeader << '\n';
  }
  void Write(const Options& o, const Fixture& f, const mb::MvccTable* table,
             int stage, std::string_view phase, unsigned workers, std::uint64_t snapshot,
             const mb::Sample& sample, const Stats& stats, std::uint64_t baseline,
             std::uint64_t before, std::uint64_t after, std::size_t versions,
             std::string_view mode, std::string_view representation, bool native_batch,
             std::uint64_t retained, std::uint64_t overlap = 0, std::uint64_t writer_elapsed = 0) {
    (void)table;
    const double seconds = sample.elapsed_ns/1e9;
    const auto counter = [&](mb::Counter c) {
      return sample.counters[c] && sample.operations ? mb::Number(*sample.counters[c]/sample.operations) : "";
    };
    const auto delta = static_cast<std::int64_t>(after)-static_cast<std::int64_t>(baseline);
    out_ << "mvcc-v1," << run_id_ << ',' << o.index << ',' << representation << ',' << mode
         << ',' << native_batch << ',' << stage << ',' << phase << ',' << workers << ','
         << o.keys << ',' << o.versions << ',' << versions << ',' << o.key_size << ',' << o.value_size
         << ',' << o.batch_size << ',' << snapshot << ',' << o.snapshot_lag << ',' << o.delete_percent
         << ',' << o.miss_percent << ',' << o.read_percent << ',' << o.scan_percent << ',' << o.scan_length
         << ',' << o.distribution << ',' << o.layout << ',' << o.prefix_bytes << ',' << o.prefix_groups
         << ',' << o.seed << ',' << f.keys.Stats().hash << ",\"" << o.cpu_list << "\"," << o.numa_node
         << ',' << sample.operations << ',' << stats.gets << ',' << stats.scans << ',' << stats.writes
         << ',' << stats.hits << ',' << stats.tombstones << ',' << stats.misses << ',' << sample.items
         << ',' << stats.versions_tested << ',' << sample.elapsed_ns << ',' << mb::Number(sample.operations/seconds)
         << ',' << mb::Number(stats.writes/seconds) << ',' << mb::Number(sample.items/seconds)
         << ',' << (sample.latency_ns.empty() ? "" : mb::Number(mb::Percentile(sample.latency_ns,.50)))
         << ',' << (sample.latency_ns.empty() ? "" : mb::Number(mb::Percentile(sample.latency_ns,.95)))
         << ',' << (sample.latency_ns.empty() ? "" : mb::Number(mb::Percentile(sample.latency_ns,.99))) << ',' << counter(mb::kCycles)
         << ',' << counter(mb::kInstructions) << ',';
    if (sample.counters[mb::kCycles] && sample.counters[mb::kInstructions] && *sample.counters[mb::kCycles]>0)
      out_ << mb::Number(*sample.counters[mb::kInstructions] / *sample.counters[mb::kCycles]);
    out_ << ',' << counter(mb::kL1Miss) << ',' << counter(mb::kLLCMiss) << ',' << counter(mb::kBranchMiss)
         << ',' << counter(mb::kDTLBMiss) << ',' << baseline << ',' << before << ',' << after << ',' << delta
         << ',' << mb::Number(static_cast<double>(delta)/o.keys) << ',';
    if (versions) out_ << mb::Number(static_cast<double>(delta)/versions);
    out_ << ',';
    if (retained) out_ << retained;
    out_ << ',';
    if (stage==2 && workers>1) out_ << overlap;
    out_ << ',';
    if (stage==2 && writer_elapsed) out_ << writer_elapsed;
    out_ << ',' << sample.checksum << '\n'; out_.flush();
    std::cout << o.index << ' ' << phase << ": " << mb::Number(sample.operations/seconds)
              << " requests/s, " << stats.writes << " written versions, " << sample.items << " items\n";
  }
 private:
  static constexpr std::string_view kHeader =
    "schema_version,run_id,index,representation,adapter_mode,native_batch,stage,phase,threads,"
    "user_keys,initial_versions_per_key,stored_versions,key_size,value_size,batch_size,snapshot_ts,snapshot_lag,"
    "delete_percent,miss_percent,read_percent,scan_percent,scan_length,distribution,key_layout,prefix_bytes,prefix_groups,"
    "seed,dataset_hash,cpu_list,numa_node,requests,point_reads,scan_requests,written_versions,live_hits,tombstone_hits,"
    "not_found,items,versions_tested,elapsed_ns,throughput_requests_s,throughput_versions_s,items_s,"
    "latency_p50_ns,latency_p95_ns,latency_p99_ns,cycles_per_request,instructions_per_request,ipc,"
    "l1d_miss_per_request,llc_miss_per_request,branch_miss_per_request,dtlb_miss_per_request,"
    "rss_baseline_bytes,rss_before_bytes,rss_after_bytes,rss_retained_delta_bytes,bytes_per_user_key,bytes_per_version,"
    "backend_retained_bytes,concurrent_overlap_ns,writer_elapsed_ns,checksum";
  std::ofstream out_;
  std::uint64_t run_id_ = std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::system_clock::now().time_since_epoch()).count();
};

void Verify(bool ok, std::string_view reason) {
  if (!ok) throw std::runtime_error("MVCC validation failed: " + std::string(reason));
}
std::size_t Batches(std::size_t count, std::size_t batch_size) {
  return count/batch_size + (count%batch_size != 0);
}
mb::Sample Load(mb::MvccTable& table, const Fixture& f, Stats* stats) {
  return mb::Measure(Batches(f.load.size(), f.o.batch_size), [&](auto i, auto* hash) {
    const auto start = i*f.o.batch_size, count = std::min(f.o.batch_size, f.load.size()-start);
    Verify(table.Write(std::span(f.load).subspan(start, count)), "load rejected");
    stats->writes += count;
    // Hash submission metadata, keeping payload hashing out of the write phase.
    *hash = (*hash*1099511628211ULL)^count;
    return count;
  });
}
void Single(const Options& o, const Fixture& f, Csv& csv, bool lifecycle) {
  const auto baseline = mb::ResidentBytes();
  auto table = mb::MakeMvccTable(o.index, o.key_size);
  const std::string mode(table->ConcurrencyMode()), representation(table->Representation());
  const bool native_batch = table->NativeBatch();
  const int stage = lifecycle ? 3 : 1;
  auto emit = [&](auto phase, const mb::Sample& s, const Stats& stats, auto before, auto snapshot) {
    csv.Write(o,f,table.get(),stage,phase,1,snapshot,s,stats,baseline,before,mb::ResidentBytes(),
              table ? table->VersionCount() : f.load.size(),mode,representation,native_batch,
              table ? table->RetainedBytes() : 0);
  };
  Stats stats;
  auto before = mb::ResidentBytes();
  auto sample = Load(*table,f,&stats);
  Verify(table->VersionCount()==f.load.size(), "load cardinality");
  emit("batch_load",sample,stats,before,f.Snapshot(true));
  if (lifecycle) {
    before = mb::ResidentBytes();
    sample = mb::Measure(1,[&](auto,auto*) { table->Freeze(); return 0; });
    emit("freeze",sample,{},before,f.Snapshot(true));
    // Oracle uses all submitted versions sorted in user-key / descending TS order.
    std::uint64_t expected = kHash;
    for (auto id : f.sorted_present) for (std::size_t r=o.versions; r-- > 0;)
      mb::HashRecord(f.keys.Key(id),f.Deleted(id,r) ? std::string_view{} : f.values[r],
                     r*o.keys+id+1,f.Deleted(id,r),&expected);
    before = mb::ResidentBytes();
    sample = mb::Measure(1,[&](auto,auto* hash) { return mb::FlushVersions(*table,hash); });
    Verify(sample.items==f.load.size() && sample.checksum==expected,"complete ordered flush");
    emit("flush_all_versions",sample,{},before,f.Snapshot(true));
    before = mb::ResidentBytes();
    sample = mb::Measure(1,[&](auto,auto*) { table.reset(); return 0; });
    emit("destroy",sample,{},before,0);
  } else {
    for (bool latest : {true,false}) {
      const auto snapshot = f.Snapshot(latest);
      before = mb::ResidentBytes(); stats = {};
      const auto expected = f.read_checks[latest ? 0 : 1];
      sample = mb::Measure(f.reads.size(),[&](auto i,auto* hash) { return f.Read(*table,f.reads[i],snapshot,false,&stats,hash); });
      Verify(sample.checksum==expected,"point snapshot visibility / payload");
      emit(latest ? "get_latest" : "get_snapshot",sample,stats,before,snapshot);
      const auto scan_expected = f.read_checks[latest ? 2 : 3];
      before=mb::ResidentBytes(); stats={};
      sample=mb::Measure(f.scans.size(),[&](auto i,auto* hash) { return f.Read(*table,f.scans[i],snapshot,true,&stats,hash); });
      Verify(sample.checksum==scan_expected,"visible range scan");
      emit(latest ? "scan_latest" : "scan_snapshot",sample,stats,before,snapshot);
    }
  }
}

mb::Sample Merge(std::span<const mb::Sample> samples, std::uint64_t elapsed) {
  mb::Sample merged;
  merged.elapsed_ns=elapsed;
  for (const auto& s : samples) {
    merged.operations+=s.operations; merged.items+=s.items;
    merged.checksum=(merged.checksum*1099511628211ULL)^s.checksum;
    merged.latency_ns.insert(merged.latency_ns.end(),s.latency_ns.begin(),s.latency_ns.end());
  }
  for (std::size_t c=0;c<mb::kCount;++c) {
    double total=0; bool valid=!samples.empty();
    for (const auto& s : samples) { if (!s.counters[c]) valid=false; else total+=*s.counters[c]; }
    if (valid) merged.counters[c]=total;
  }
  return merged;
}
Stats MergeStats(std::span<const Stats> inputs) {
  Stats result;
  for (const auto& s:inputs) {
    result.gets+=s.gets; result.scans+=s.scans; result.writes+=s.writes;
    result.hits+=s.hits; result.tombstones+=s.tombstones; result.misses+=s.misses;
    result.versions_tested+=s.versions_tested;
  }
  return result;
}
void Concurrent(const Options& o, const Fixture& f, Csv& csv) {
  const bool writer = !f.writes.empty();
  const std::size_t read_count=o.ops-f.writes.size();
  const unsigned reader_begin=(writer && o.threads>1) ? 1 : 0;
  const auto readers=o.threads-reader_begin;
  if (read_count<readers && o.threads>1) throw std::invalid_argument("too few reads for SWMR readers");
  std::vector<std::span<const Request>> traces(o.threads);
  std::vector<std::uint64_t> expected(o.threads,kHash);
  std::vector<std::size_t> actions;
  if (o.threads==1) {
    actions.assign(read_count,0);
    actions.resize(read_count+Batches(f.writes.size(),o.batch_size),1);
    std::mt19937_64 rng(o.seed+111); std::shuffle(actions.begin(),actions.end(),rng);
    traces[0]=std::span(f.reads).first(read_count);
  } else {
    for (unsigned t=reader_begin;t<o.threads;++t) {
      const auto ordinal=t-reader_begin;
      const auto begin=read_count/readers*ordinal + std::min<std::size_t>(ordinal,read_count%readers);
      const auto count=read_count/readers+(ordinal<read_count%readers);
      traces[t]=std::span(f.reads).subspan(begin,count);
    }
  }
  for (unsigned t=reader_begin;t<o.threads;++t) expected[t]=f.ExpectedReads(traces[t],f.Snapshot(),true);
  const auto baseline=mb::ResidentBytes();
  auto table=mb::MakeMvccTable(o.index,o.key_size);
  Stats ignored; Load(*table,f,&ignored);
  const auto before=mb::ResidentBytes();
  std::vector<mb::Sample> samples(o.threads);
  std::vector<Stats> stats(o.threads);
  std::vector<std::exception_ptr> errors(o.threads);
  std::vector<mb::Clock::time_point> began(o.threads),finished(o.threads);
  mb::Clock::time_point start;
  // Also release every participant if setup fails, preventing a barrier deadlock.
  std::barrier ready(static_cast<std::ptrdiff_t>(o.threads),[&]() noexcept { start=mb::Clock::now(); });
  std::vector<std::thread> workers;
  workers.reserve(o.threads);
  std::exception_ptr spawn_error;
  try {
    for (unsigned t=0;t<o.threads;++t) workers.emplace_back([&,t] {
    bool joined=false;
    try {
      mb::ConfigureThread(o.cpus,o.numa_node,t);
      mb::Perf perf;
      ready.arrive_and_wait(); joined=true;
      began[t]=mb::Clock::now();
      auto write=[&](std::size_t batch, std::uint64_t*) {
        const auto begin=batch*o.batch_size, count=std::min(o.batch_size,f.writes.size()-begin);
        Verify(table->Write(std::span(f.writes).subspan(begin,count)),"concurrent write rejected");
        stats[t].writes+=count;
        return count;
      };
      if (o.threads==1) {
        std::size_t r=0,w=0;
        samples[t]=mb::Measure(actions.size(),[&](auto i,auto* hash) {
          return actions[i] ? write(w++,hash) : f.Read(*table,traces[t][r++],f.Snapshot(),true,&stats[t],hash);
        },&perf);
      } else if (writer && t==0) {
        samples[t]=mb::Measure(Batches(f.writes.size(),o.batch_size),write,&perf);
      } else {
        samples[t]=mb::Measure(traces[t].size(),[&](auto i,auto* hash) {
          return f.Read(*table,traces[t][i],f.Snapshot(),true,&stats[t],hash);
        },&perf);
      }
      finished[t]=mb::Clock::now();
    } catch (...) {
      errors[t]=std::current_exception();
      if (!joined) ready.arrive_and_drop();
    }
    });
  } catch (...) {
    spawn_error=std::current_exception();
    for (auto t=workers.size();t<o.threads;++t) ready.arrive_and_drop();
  }
  for (auto& worker:workers) worker.join();
  if (spawn_error) std::rethrow_exception(spawn_error);
  const auto elapsed=mb::Nanoseconds(mb::Clock::now()-start);
  for (const auto& error:errors) if (error) std::rethrow_exception(error);
  const auto overlap_start=*std::max_element(began.begin(),began.end());
  const auto overlap_end=*std::min_element(finished.begin(),finished.end());
  const auto overlap=overlap_end>overlap_start ? mb::Nanoseconds(overlap_end-overlap_start) : 0;
  for (unsigned t=reader_begin;t<o.threads;++t) Verify(samples[t].checksum==expected[t],"SWMR fixed snapshot");
  Verify(table->VersionCount()==f.load.size()+f.writes.size(),"SWMR version count");
  auto emit=[&](auto phase,unsigned threads,const mb::Sample& sample,const Stats& counts) {
    csv.Write(o,f,table.get(),2,phase,threads,f.Snapshot(),sample,counts,baseline,before,mb::ResidentBytes(),
              table->VersionCount(),table->ConcurrencyMode(),table->Representation(),table->NativeBatch(),table->RetainedBytes(),
              overlap,writer ? samples[0].elapsed_ns : 0);
  };
  auto total=Merge(samples,elapsed);
  // Aggregate latency mixes request classes. Report it only in single-worker
  // mixed mode; SWMR service latency is emitted separately for writer/readers.
  if (o.threads>1) total.latency_ns.clear();
  emit(o.threads==1 ? "mixed_snapshot" : (writer ? "swmr_total" : "parallel_readers"),o.threads,total,MergeStats(stats));
  if (o.threads>1 && writer) {
    emit("swmr_writer_batch",1,samples[0],stats[0]);
    emit("swmr_readers",readers,Merge(std::span(samples).subspan(1),elapsed),MergeStats(std::span(stats).subspan(1)));
  }
}
}  // namespace

int main(int argc,char** argv) {
  try {
    const auto o=Parse(argc,argv);
    mb::ConfigureThread(o.cpus,o.numa_node,0);
    const Fixture fixture(o);  // trace, payloads, sorting and oracle inputs before RSS baseline
    Csv csv(o);
    if (o.stage=="1" || o.stage=="all") Single(o,fixture,csv,false);
    if (o.stage=="2" || o.stage=="all") Concurrent(o,fixture,csv);
    if (o.stage=="3" || o.stage=="all") Single(o,fixture,csv,true);
    return 0;
  } catch (const std::exception& e) { std::cerr << "error: " << e.what() << '\n'; return 1; }
}
