# Build upstream support code rather than maintaining a modified skiplist copy.
# Disable RocksDB's unrelated executables and optional compression dependencies.
foreach(rocksdb_option IN ITEMS WITH_GFLAGS WITH_SNAPPY WITH_LZ4 WITH_ZLIB
    WITH_ZSTD WITH_BZ2 WITH_JEMALLOC WITH_LIBURING WITH_TESTS WITH_BENCHMARK_TOOLS
    WITH_CORE_TOOLS WITH_TOOLS WITH_JNI ROCKSDB_BUILD_SHARED FAIL_ON_WARNINGS)
  set(${rocksdb_option} OFF CACHE BOOL "Disabled by memtable-bench" FORCE)
endforeach()
set(PORTABLE ON CACHE STRING "Build for the baseline CPU architecture" FORCE)
set(USE_RTTI ON CACHE STRING "Keep RocksDB's internal ABI consistent" FORCE)

find_package(Git REQUIRED)
# Use a single-branch shallow checkout. FetchContent's generic git downloader
# fetches every branch even with GIT_SHALLOW, which is costly for this repository.
FetchContent_Declare(rocksdb
  DOWNLOAD_COMMAND ${CMAKE_COMMAND}
    -DROCKSDB_SOURCE_DIR:PATH=<SOURCE_DIR>
    -DGIT_EXECUTABLE:FILEPATH=${GIT_EXECUTABLE}
    -P ${CMAKE_CURRENT_LIST_DIR}/FetchRocksDB.cmake
  UPDATE_COMMAND "")
FetchContent_MakeAvailable(rocksdb)
execute_process(COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
  WORKING_DIRECTORY ${rocksdb_SOURCE_DIR}
  OUTPUT_VARIABLE rocksdb_commit OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY)
if(NOT rocksdb_commit STREQUAL "ae8fb3e5000e46d8d4c9dbf3a36019c0aaceebff")
  message(FATAL_ERROR "Unexpected RocksDB commit: ${rocksdb_commit}")
endif()

# Upstream exports its public include path, but its internal headers also need
# the same platform feature definitions used to compile the library.
get_directory_property(rocksdb_definitions DIRECTORY ${rocksdb_SOURCE_DIR}
  COMPILE_DEFINITIONS)
target_sources(memtable_bench_index PRIVATE src/rocksdb_index.cc)
target_include_directories(memtable_bench_index SYSTEM PRIVATE ${rocksdb_SOURCE_DIR})
target_compile_definitions(memtable_bench_index PRIVATE
  MEMTABLE_BENCH_HAVE_ROCKSDB=1 ${rocksdb_definitions})
target_link_libraries(memtable_bench_index PRIVATE rocksdb)
