#!/bin/sh
set -eu
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset CFLAGS CXXFLAGS LDFLAGS CPPFLAGS
cd "$HOME/github/memtable-bench"
cmake -S . -B build-linux -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
  -DMEMTABLE_BENCH_FETCH_ABSEIL=ON -DMEMTABLE_BENCH_FETCH_TLX=ON \
  -DMEMTABLE_BENCH_FETCH_ROCKSDB=ON -DMEMTABLE_BENCH_FETCH_BTREEOLC=ON \
  -DMEMTABLE_BENCH_FETCH_UNODB=ON -DMEMTABLE_BENCH_FETCH_MASSTREE=ON \
  -DMEMTABLE_BENCH_FETCH_HOT=ON -DMEMTABLE_BENCH_FETCH_WORMHOLE=ON \
  -DFETCHCONTENT_SOURCE_DIR_ABSEIL-CPP="$PWD/vendor/abseil-cpp" \
  -DFETCHCONTENT_SOURCE_DIR_TLX="$PWD/vendor/tlx" \
  -DFETCHCONTENT_SOURCE_DIR_ROCKSDB="$PWD/vendor/rocksdb" \
  -DFETCHCONTENT_SOURCE_DIR_BTREEOLC="$PWD/vendor/btreeolc" \
  -DFETCHCONTENT_SOURCE_DIR_UNODB="$PWD/vendor/unodb" \
  -DFETCHCONTENT_SOURCE_DIR_MASSTREE="$PWD/vendor/masstree" \
  -DFETCHCONTENT_SOURCE_DIR_HOT="$PWD/vendor/hot" \
  -DFETCHCONTENT_SOURCE_DIR_WORMHOLE="$PWD/vendor/wormhole" \
  -DBOOST_ROOT="$PWD/vendor/boost_1_86_0" \
  -DBoost_NO_SYSTEM_PATHS=ON -DBoost_NO_BOOST_CMAKE=ON
cmake --build build-linux --target memtable_bench adapter_contract -j 8
MEMTABLE_BENCH_REQUIRE_HOT=1 ctest --test-dir build-linux --output-on-failure
./build-linux/memtable_bench --list-indexes
