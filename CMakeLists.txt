cmake_minimum_required(VERSION 3.20)
project(memtable_bench VERSION 0.1.0 LANGUAGES CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR
   NOT CMAKE_HOST_SYSTEM_NAME STREQUAL "Linux" OR CMAKE_CROSSCOMPILING OR
   NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$" OR
   NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "memtable-bench supports native Linux x86-64 builds only")
endif()
if(NOT CMAKE_CXX_COMPILER_ID MATCHES "^(Clang|GNU)$")
  message(FATAL_ERROR "memtable-bench requires GCC or Clang on Linux x86-64")
endif()

option(MEMTABLE_BENCH_FETCH_ROCKSDB "Build the required RocksDB InlineSkipList baseline" ON)
option(MEMTABLE_BENCH_FETCH_BTREEOLC "Build the BTreeOLC adapter" OFF)
option(MEMTABLE_BENCH_FETCH_UNODB "Build the UnoDB OLC ART adapter" OFF)
option(MEMTABLE_BENCH_FETCH_WORMHOLE "Build the Wormhole adapter" OFF)
set(MEMTABLE_BENCH_CSE_SOURCE_DIR "" CACHE PATH "Pinned CSE MemTable export directory")

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Threads REQUIRED)
add_library(memtable_bench_index src/index.cc src/key_dataset.cc src/mvcc.cc)
target_include_directories(memtable_bench_index PUBLIC include)
target_link_libraries(memtable_bench_index PUBLIC Threads::Threads)
add_executable(memtable_bench src/main.cc)
target_link_libraries(memtable_bench PRIVATE memtable_bench_index)
target_compile_options(memtable_bench PRIVATE -Wall -Wextra -Wpedantic)
target_compile_options(memtable_bench_index PRIVATE -Wall -Wextra -Wpedantic)
add_executable(mvcc_bench src/mvcc_main.cc)
target_link_libraries(mvcc_bench PRIVATE memtable_bench_index)
target_compile_options(mvcc_bench PRIVATE -Wall -Wextra -Wpedantic)

if(NOT MEMTABLE_BENCH_FETCH_ROCKSDB)
  message(FATAL_ERROR "RocksDB InlineSkipList is the required baseline")
endif()
foreach(removed IN ITEMS ABSEIL TLX MASSTREE HOT OCEANBASE)
  if(MEMTABLE_BENCH_FETCH_${removed})
    message(FATAL_ERROR "${removed} was removed; see docs/index-selection.md")
  endif()
endforeach()
include(FetchContent)
include(cmake/RocksDB.cmake)

if(MEMTABLE_BENCH_FETCH_BTREEOLC OR MEMTABLE_BENCH_FETCH_UNODB OR MEMTABLE_BENCH_FETCH_WORMHOLE)
  include(cmake/Vendor.cmake)
endif()
if(MEMTABLE_BENCH_FETCH_BTREEOLC)
  include(cmake/BTreeOLC.cmake)
endif()
if(MEMTABLE_BENCH_FETCH_UNODB)
  include(cmake/UnoDB.cmake)
endif()
if(MEMTABLE_BENCH_FETCH_WORMHOLE)
  include(cmake/Wormhole.cmake)
endif()
if(MEMTABLE_BENCH_CSE_SOURCE_DIR)
  include(cmake/CSE.cmake)
endif()

enable_testing()
add_executable(mvcc_contract tests/mvcc_contract.cc)
target_link_libraries(mvcc_contract PRIVATE memtable_bench_index)
add_test(NAME mvcc_contract COMMAND mvcc_contract)
set_tests_properties(mvcc_contract PROPERTIES TIMEOUT 120)
add_test(NAME mvcc_smoke COMMAND mvcc_bench --index rocksdb_inlineskiplist --stage all
  --keys 100 --versions 4 --ops 300 --batch-size 7
  --output ${CMAKE_CURRENT_BINARY_DIR}/mvcc-smoke-v2.csv)
add_executable(key_dataset_contract tests/key_dataset_contract.cc)
target_link_libraries(key_dataset_contract PRIVATE memtable_bench_index)
add_test(NAME key_dataset_contract COMMAND key_dataset_contract)
add_executable(adapter_contract tests/adapter_contract.cc)
target_link_libraries(adapter_contract PRIVATE memtable_bench_index)
add_test(NAME adapter_contract COMMAND adapter_contract)
set_tests_properties(adapter_contract PROPERTIES TIMEOUT 120)
add_test(NAME smoke COMMAND memtable_bench --stage all --index rocksdb_inlineskiplist --internal-key
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

foreach(candidate IN ITEMS btreeolc unodb_art wormhole)
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
  add_test(NAME mvcc_integration COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/mvcc_integration.py $<TARGET_FILE:mvcc_bench>)
  set_tests_properties(mvcc_integration PROPERTIES TIMEOUT 180)
  add_test(NAME mvcc_matrix_integration COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/mvcc_matrix_integration.py $<TARGET_FILE:mvcc_bench>)
  set_tests_properties(mvcc_matrix_integration PROPERTIES TIMEOUT 180)
  add_test(NAME benchmark_policy COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/benchmark_policy.py $<TARGET_FILE:memtable_bench>)
  add_test(NAME harness_integration COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/harness_integration.py $<TARGET_FILE:memtable_bench>)
  set_tests_properties(harness_integration PROPERTIES TIMEOUT 180)
endif()
