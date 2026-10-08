cmake_minimum_required(VERSION 3.20)
project(memtable_bench VERSION 0.1.0 LANGUAGES CXX)

option(MEMTABLE_BENCH_FETCH_ABSEIL "Build the Abseil B-tree adapter" OFF)
option(MEMTABLE_BENCH_FETCH_TLX "Build the TLX B+tree adapter" OFF)
option(MEMTABLE_BENCH_FETCH_ROCKSDB "Build the RocksDB InlineSkipList adapter" OFF)
option(MEMTABLE_BENCH_FETCH_BTREEOLC "Build the BTreeOLC adapter" OFF)
option(MEMTABLE_BENCH_FETCH_UNODB "Build the UnoDB OLC ART adapter" OFF)
option(MEMTABLE_BENCH_FETCH_MASSTREE "Build the Masstree adapter" OFF)
option(MEMTABLE_BENCH_FETCH_HOT "Build the HOT adapter (x86_64 AVX2/BMI2)" OFF)
option(MEMTABLE_BENCH_FETCH_WORMHOLE "Build the Wormhole adapter" OFF)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Threads REQUIRED)
add_library(memtable_bench_index src/index.cc src/key_dataset.cc)
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

if(MEMTABLE_BENCH_FETCH_BTREEOLC OR MEMTABLE_BENCH_FETCH_UNODB OR
   MEMTABLE_BENCH_FETCH_MASSTREE OR MEMTABLE_BENCH_FETCH_HOT OR MEMTABLE_BENCH_FETCH_WORMHOLE)
  include(cmake/Vendor.cmake)
endif()
if(MEMTABLE_BENCH_FETCH_BTREEOLC)
  include(cmake/BTreeOLC.cmake)
endif()
if(MEMTABLE_BENCH_FETCH_UNODB)
  include(cmake/UnoDB.cmake)
endif()
if(MEMTABLE_BENCH_FETCH_MASSTREE)
  include(cmake/Masstree.cmake)
endif()
if(MEMTABLE_BENCH_FETCH_HOT)
  include(cmake/HOT.cmake)
endif()
if(MEMTABLE_BENCH_FETCH_WORMHOLE)
  include(cmake/Wormhole.cmake)
endif()

enable_testing()
add_executable(key_dataset_contract tests/key_dataset_contract.cc)
target_link_libraries(key_dataset_contract PRIVATE memtable_bench_index)
add_test(NAME key_dataset_contract COMMAND key_dataset_contract)
add_executable(adapter_contract tests/adapter_contract.cc)
target_link_libraries(adapter_contract PRIVATE memtable_bench_index)
add_test(NAME adapter_contract COMMAND adapter_contract)
set_tests_properties(adapter_contract PROPERTIES TIMEOUT 120)
add_test(NAME smoke COMMAND memtable_bench --stage all --index std_map
  --keys 1000 --ops 2000 --threads 1 --output ${CMAKE_CURRENT_BINARY_DIR}/smoke-v3.csv)
if(MEMTABLE_BENCH_FETCH_ROCKSDB)
  add_test(NAME rocksdb_smoke COMMAND memtable_bench --stage all
    --index rocksdb_inlineskiplist --internal-key --keys 1000 --ops 2000
    --threads 4 --output ${CMAKE_CURRENT_BINARY_DIR}/rocksdb-smoke-v3.csv)
  add_test(NAME rocksdb_reject_upsert COMMAND memtable_bench --stage 2
    --index rocksdb_inlineskiplist --keys 10 --ops 10 --read-percent 0
    --output ${CMAKE_CURRENT_BINARY_DIR}/rocksdb-rejected.csv)
  set_tests_properties(rocksdb_reject_upsert PROPERTIES WILL_FAIL TRUE)
endif()

foreach(candidate IN ITEMS btreeolc unodb_art masstree wormhole)
  if(candidate STREQUAL "unodb_art")
    set(candidate_option UNODB)
  else()
    string(TOUPPER "${candidate}" candidate_option)
  endif()
  if(MEMTABLE_BENCH_FETCH_${candidate_option})
    add_test(NAME ${candidate}_smoke COMMAND memtable_bench --stage all
      --index ${candidate} --internal-key --keys 2000 --ops 5000 --threads 4
      --key-size 24 --value-size 64 --output ${CMAKE_CURRENT_BINARY_DIR}/${candidate}-smoke-v3.csv)
  endif()
endforeach()
if(MEMTABLE_BENCH_FETCH_UNODB)
  add_test(NAME unodb_reject_upsert COMMAND memtable_bench --stage 2
    --index unodb_art --keys 10 --ops 10 --read-percent 0
    --output ${CMAKE_CURRENT_BINARY_DIR}/unodb-rejected.csv)
  set_tests_properties(unodb_reject_upsert PROPERTIES WILL_FAIL TRUE)
endif()

find_package(Python3 QUIET COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND)
  add_test(NAME benchmark_policy COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/benchmark_policy.py $<TARGET_FILE:memtable_bench>)
  add_test(NAME harness_integration COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/harness_integration.py $<TARGET_FILE:memtable_bench>)
  set_tests_properties(harness_integration PROPERTIES TIMEOUT 180)
endif()
