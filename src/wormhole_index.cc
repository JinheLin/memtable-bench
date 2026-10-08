#include "memtable_bench/index.h"
#include "adapter_common.h"

#include "lib.h"
#include "kv.h"
#include "wh.h"

#include <atomic>
#include <cstdlib>
#include <limits>
#include <mutex>

namespace memtable_bench {
namespace {
std::string_view KeyView(const kvref& record) {
  return {reinterpret_cast<const char*>(record.kptr), record.hdr.klen};
}
std::string_view ValueView(const kvref& record) {
  return {reinterpret_cast<const char*>(record.vptr), record.hdr.vlen};
}
kref Probe(std::string_view key) {
  if (key.size() > 65535) throw std::length_error("Wormhole key exceeds 65535 bytes");
  return {static_cast<u32>(key.size()), {kv_crc32c(key.data(), static_cast<u32>(key.size()))},
          reinterpret_cast<const u8*>(key.data())};
}
std::atomic<std::uint64_t> next_instance{1};

class WormholeIndex final : public Index {
 public:
  WormholeIndex() : id_(next_instance.fetch_add(1)), map_(wormhole_create(nullptr)) {
    if (!map_) throw std::bad_alloc();
  }
  ~WormholeIndex() override {
    // Workers have finished; TLS caches hold only raw pointers and never unref.
    for (auto* ref : refs_) wormhole_unref(ref);
    wormhole_destroy(map_);
  }

  bool Insert(std::string_view key, std::string_view value) override {
    WriteAdmission::Guard admitted(admission_);
    if (!admitted) return false;
    const auto probe = Probe(key);
    if (value.size() > std::numeric_limits<u32>::max())
      throw std::length_error("Wormhole value exceeds uint32");
    // The default memory manager duplicates the callback's temporary record.
    // The merge callback runs under the native leaf write lock, so exact size
    // tracking handles races between duplicate upserts without a global lock.
    std::unique_ptr<kv, decltype(&std::free)> record(
        kv_create(key.data(), static_cast<u32>(key.size()), value.data(),
                  static_cast<u32>(value.size())), &std::free);
    if (!record) throw std::bad_alloc();
    struct Merge { kv* record; bool inserted; } merge{record.get(), false};
    const bool accepted = whsafe_merge(Reference(), &probe, [](kv* old, void* opaque) -> kv* {
      auto& context = *static_cast<Merge*>(opaque);
      context.inserted = old == nullptr;
      return context.record;
    }, &merge);
    if (!accepted) throw std::bad_alloc();
    if (merge.inserted) size_.fetch_add(1, std::memory_order_relaxed);
    return true;
  }

  bool Contains(std::string_view key) const override {
    const auto probe = Probe(key);
    return whsafe_probe(Reference(), &probe);
  }

  bool Get(std::string_view key, std::string* value) const override {
    const auto probe = Probe(key);
    std::unique_ptr<kv, decltype(&std::free)> found(
        whsafe_get(Reference(), &probe, nullptr), &std::free);
    if (!found) return false;
    value->assign(static_cast<const char*>(kv_vptr_c(found.get())), found->vlen);
    return true;
  }

  class WormCursor final : public Cursor {
   public:
    WormCursor(wormhole* map, bool frozen) : frozen_(frozen) {
      if (frozen_) it_ = whunsafe_iter_create(map);
      else {
        ref_ = whsafe_ref(map);
        if (!ref_) throw std::bad_alloc();
        it_ = wormhole_iter_create(ref_);
      }
      if (!it_) { if (ref_) wormhole_unref(ref_); throw std::bad_alloc(); }
    }
    ~WormCursor() override {
      if (frozen_) whunsafe_iter_destroy(it_);
      else { whsafe_iter_destroy(it_); wormhole_unref(ref_); }
    }
    bool Seek(std::string_view key) override { return Position(key, false); }
    bool Next() override {
      if (!valid_) return false;
      if (!frozen_) return Position(key_, true);
      whunsafe_iter_skip1(it_);
      return Refresh();
    }
    bool Valid() const override { return valid_; }
    std::string_view Key() const override {
      return frozen_ ? (valid_ ? KeyView(view_) : std::string_view{}) : std::string_view(key_);
    }
    std::string_view Value() const override {
      return frozen_ ? (valid_ ? ValueView(view_) : std::string_view{}) : std::string_view(value_);
    }
   private:
    bool Position(std::string_view key, bool strict) {
      const auto probe = Probe(key);
      if (frozen_) { whunsafe_iter_seek(it_, &probe); return Refresh(); }
      whsafe_iter_seek(it_, &probe);
      // Park on every movement: no leaf latch is held while the caller writes
      // through this index or retains another active cursor in the same thread.
      if (wormhole_iter_kvref(it_, &view_) && strict && KeyView(view_) == key)
        wormhole_iter_skip1(it_);
      Refresh();
      whsafe_iter_park(it_);
      return valid_;
    }
    bool Refresh() {
      valid_ = wormhole_iter_kvref(it_, &view_);
      if (!frozen_) {
        if (valid_) { key_.assign(KeyView(view_)); value_.assign(ValueView(view_)); }
        else { key_.clear(); value_.clear(); }
      }
      return valid_;
    }
    bool frozen_, valid_ = false;
    wormref* ref_ = nullptr;
    wormhole_iter* it_ = nullptr;
    kvref view_{};
    std::string key_, value_;
  };

  std::unique_ptr<Cursor> NewCursor() const override {
    return std::make_unique<WormCursor>(map_, admission_.Frozen());
  }
  void Freeze() override { admission_.Freeze(); }
  std::size_t Size() const override { return size_.load(std::memory_order_relaxed); }
  std::string_view ConcurrencyMode() const override { return "native_whsafe"; }
 private:
  wormref* Reference() const {
    struct Cache { std::uint64_t id = 0; wormref* ref = nullptr; };
    static thread_local Cache cache;
    if (cache.id == id_) return cache.ref;
    std::lock_guard lock(ref_mutex_);
    auto* ref = whsafe_ref(map_);
    if (!ref) throw std::bad_alloc();
    try { refs_.push_back(ref); }
    catch (...) { wormhole_unref(ref); throw; }
    cache = {id_, ref};
    return ref;
  }
  const std::uint64_t id_;
  wormhole* map_;
  mutable std::mutex ref_mutex_;
  mutable std::vector<wormref*> refs_;
  WriteAdmission admission_;
  std::atomic<std::size_t> size_{0};
};
}  // namespace

std::unique_ptr<Index> MakeWormhole() { return std::make_unique<WormholeIndex>(); }
}  // namespace memtable_bench
