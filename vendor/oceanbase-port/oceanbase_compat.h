#pragma once

#include "oceanbase_macros.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <pthread.h>
#include <sched.h>
#include <strings.h>
#include <string>
#include <unistd.h>
#include "ob_atomic.h"
#include "ob_errno.h"

inline void ob_abort() noexcept { std::abort(); }

namespace oceanbase {
namespace lib {
struct ObMemAttr {};  // Only used by the uninstantiated ObDynamicQSync helper.
}
namespace common {
inline constexpr std::int64_t OB_MAX_CPU_NUM = 128;  // upstream Linux x86-64
// The KeyBtree calls only alloc(size). The backing allocator is supplied by the
// benchmark and retains every allocation through native tree destruction.
class ObIAllocator {
 public:
  virtual ~ObIAllocator() = default;
  virtual void* alloc(std::int64_t size) = 0;
};
template <typename T> class ObIArray;  // range-estimation APIs are not instantiated
template <typename Signature> class ObFunction;  // insert_or_get is not instantiated
class ObTimeGuard {
 public:
  ObTimeGuard(const char*, std::int64_t) {}
  void click() {}
};
class ObCStringHelper {
 public:
  template <typename T> const char* convert(const T& key) {
    buffer_ = key.DebugString();
    return buffer_.c_str();
  }
 private:
  std::string buffer_;
};
// Unused by ObKeyBtree/ObQSync; these resolve the separate DynamicQSync helper.
inline void* ob_malloc(std::int64_t size, const lib::ObMemAttr&) { return std::malloc(size); }
inline void ob_free(void* pointer) { std::free(pointer); }
inline std::int64_t get_cpu_count() { return sysconf(_SC_NPROCESSORS_ONLN); }
}  // namespace common
}  // namespace oceanbase
