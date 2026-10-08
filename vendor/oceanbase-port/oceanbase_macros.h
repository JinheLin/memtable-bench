#pragma once

// Standalone mappings for OceanBase's build/runtime macros. Atomic operations
// themselves come from the verified upstream ob_atomic.h. Coroutine scheduling
// is outside this index benchmark; its RLOCAL storage is OS-thread-local here.
#define UNUSED(v) ((void)(v))
#define OB_INLINE inline __attribute__((always_inline))
#define CACHE_ALIGN_SIZE 64
#define CACHE_ALIGNED __attribute__((aligned(CACHE_ALIGN_SIZE)))
#define OB_LIKELY(x) __builtin_expect(!!(x), 1)
#define OB_UNLIKELY(x) __builtin_expect(!!(x), 0)
#define OB_SUCC(statement) (OB_LIKELY(::oceanbase::common::OB_SUCCESS == (ret = (statement))))
#define OB_FAIL(statement) (OB_UNLIKELY(::oceanbase::common::OB_SUCCESS != (ret = (statement))))
#define OB_ISNULL(statement) (OB_UNLIKELY(nullptr == (statement)))
#define OB_NOT_NULL(statement) (OB_LIKELY(nullptr != (statement)))
#define STATIC_ASSERT(condition, message) static_assert(condition, message)
#define DISALLOW_COPY_AND_ASSIGN(T) T(const T&) = delete; T& operator=(const T&) = delete
#define MAX(x, y) ((x) > (y) ? (x) : (y))
#define TLOCAL(T, var) thread_local T var
#define RLOCAL(T, var) static thread_local T var{}
#define RLOCAL_INLINE(T, var) static thread_local T var{}

// Tenant logging, time guards and atomic profiling are not initialized in the
// standalone process. Assertions still abort; native return codes are checked.
#define OB_LOG(...) ((void)0)
#define COMMON_LOG(...) ((void)0)
#define COMMON_LOG_RET(...) ((void)0)
#define STORAGE_LOG(...) ((void)0)
#define TRANS_LOG(...) ((void)0)
#define OB_ATOMIC_EVENT(...) ((void)0)
#define REACH_TIME_INTERVAL(...) false
