if(NOT UNIX OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8 OR
   NOT CMAKE_CXX_COMPILER_ID MATCHES "^(AppleClang|Clang|GNU)$")
  message(FATAL_ERROR "Masstree integration requires 64-bit Unix with Clang/GCC")
endif()
memtable_fetch(masstree https://github.com/kohler/masstree-beta.git
  11198427a1170654ca646dd20d96c8f349bca2bd)
memtable_patch(${masstree_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/cmake/patches/masstree-arm64.patch)
memtable_patch(${masstree_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/cmake/patches/masstree-permutation.patch)
include(CheckCXXSourceCompiles)
check_cxx_source_compiles("#include <cstdint>\n#include <type_traits>\nstatic_assert(std::is_same_v<int64_t,long>);\nint main(){}" HAVE_INT64_T_IS_LONG)
check_cxx_source_compiles("#include <cstdint>\n#include <type_traits>\nstatic_assert(std::is_same_v<int64_t,long long>);\nint main(){}" HAVE_INT64_T_IS_LONG_LONG)
check_cxx_source_compiles("#include <cstddef>\n#include <type_traits>\nstatic_assert(std::is_same_v<size_t,unsigned long>);\nint main(){}" HAVE_SIZE_T_IS_UNSIGNED_LONG)
check_cxx_source_compiles("#include <cstddef>\n#include <type_traits>\nstatic_assert(std::is_same_v<size_t,unsigned long long>);\nint main(){}" HAVE_SIZE_T_IS_UNSIGNED_LONG_LONG)
check_cxx_source_compiles("#include <sys/types.h>\n#include <type_traits>\nstatic_assert(std::is_same_v<off_t,long long>);\nint main(){}" HAVE_OFF_T_IS_LONG_LONG)
set(masstree_config_dir "${CMAKE_CURRENT_BINARY_DIR}/masstree-config")
configure_file(cmake/masstree_config.h.in ${masstree_config_dir}/config.h)
add_library(memtable_masstree STATIC
  ${masstree_SOURCE_DIR}/compiler.cc ${masstree_SOURCE_DIR}/string.cc
  ${masstree_SOURCE_DIR}/str.cc ${masstree_SOURCE_DIR}/straccum.cc)
target_include_directories(memtable_masstree SYSTEM PUBLIC ${masstree_SOURCE_DIR} ${masstree_config_dir})
target_compile_options(memtable_masstree PRIVATE -include ${masstree_config_dir}/config.h)
target_link_libraries(memtable_masstree PUBLIC Threads::Threads)
target_sources(memtable_bench_index PRIVATE src/masstree_index.cc)
set_source_files_properties(src/masstree_index.cc PROPERTIES
  COMPILE_OPTIONS "-include;${masstree_config_dir}/config.h")
target_compile_definitions(memtable_bench_index PRIVATE MEMTABLE_BENCH_HAVE_MASSTREE=1)
target_link_libraries(memtable_bench_index PRIVATE memtable_masstree)
