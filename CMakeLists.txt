cmake_minimum_required(VERSION 3.20)
project(memtable_bench VERSION 0.1.0 LANGUAGES CXX)

option(MEMTABLE_BENCH_FETCH_ABSEIL "Build the Abseil B-tree adapter" OFF)
option(MEMTABLE_BENCH_FETCH_TLX "Build the TLX B+tree adapter" OFF)
option(MEMTABLE_BENCH_FETCH_ROCKSDB "Build the RocksDB InlineSkipList adapter" OFF)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Threads REQUIRED)
add_library(memtable_bench_index src/index.cc)
target_include_directories(memtable_bench_index PUBLIC include)
target_link_libraries(memtable_bench_index PUBLIC Threads::Threads)
add_executable(memtable_bench src/main.cc)
target_link_libraries(memtable_bench PRIVATE memtable_bench_index)
target_compile_options(memtable_bench PRIVATE -Wall -Wextra -Wpedantic)
target_compile_options(memtable_bench_index PRIVATE -Wall -Wextra -Wpedantic)

if(MEMTABLE_BENCH_FETCH_ABSEIL OR MEMTABLE_BENCH_FETCH_TLX OR MEMTABLE_BENCH_FETCH_ROCKSDB)
  include(FetchContent)
endif()

if(MEMTABLE_BENCH_FETCH_ABSEIL)
  set(ABSL_PROPAGATE_CXX_STD ON)
  set(ABSL_BUILD_TESTING OFF)
  FetchContent_Declare(abseil-cpp
    GIT_REPOSITORY https://github.com/abseil/abseil-cpp.git
    GIT_TAG 76bb24329e8bf5f39704eb10d21b9a80befa7c81)
  FetchContent_MakeAvailable(abseil-cpp)
  target_compile_definitions(memtable_bench_index PRIVATE MEMTABLE_BENCH_HAVE_ABSEIL=1)
  target_link_libraries(memtable_bench_index PRIVATE absl::btree)
endif()

if(MEMTABLE_BENCH_FETCH_TLX)
  FetchContent_Declare(tlx
    GIT_REPOSITORY https://github.com/tlx/tlx.git
    GIT_TAG 502601e2328129263eeb31a61342e4a48f519a2b)
  FetchContent_MakeAvailable(tlx)
  target_include_directories(memtable_bench_index PRIVATE ${tlx_SOURCE_DIR})
  target_compile_definitions(memtable_bench_index PRIVATE MEMTABLE_BENCH_HAVE_TLX=1)
endif()

if(MEMTABLE_BENCH_FETCH_ROCKSDB)
  include(cmake/RocksDB.cmake)
endif()

enable_testing()
add_executable(adapter_contract tests/adapter_contract.cc)
target_link_libraries(adapter_contract PRIVATE memtable_bench_index)
add_test(NAME adapter_contract COMMAND adapter_contract)
add_test(NAME smoke COMMAND memtable_bench --stage all --index std_map
  --keys 1000 --ops 2000 --threads 2 --output ${CMAKE_CURRENT_BINARY_DIR}/smoke.csv)
if(MEMTABLE_BENCH_FETCH_ROCKSDB)
  add_test(NAME rocksdb_smoke COMMAND memtable_bench --stage all
    --index rocksdb_inlineskiplist --internal-key --keys 1000 --ops 2000
    --threads 4 --output ${CMAKE_CURRENT_BINARY_DIR}/rocksdb-smoke.csv)
  add_test(NAME rocksdb_reject_upsert COMMAND memtable_bench --stage 2
    --index rocksdb_inlineskiplist --keys 10 --ops 10 --read-percent 0
    --output ${CMAKE_CURRENT_BINARY_DIR}/rocksdb-rejected.csv)
  set_tests_properties(rocksdb_reject_upsert PROPERTIES WILL_FAIL TRUE)
endif()
