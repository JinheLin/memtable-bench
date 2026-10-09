#!/bin/sh
set -eu
# The host's build policy requires direct dependency downloads.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
task_source=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
task_build=${1:-"$task_source/build-all"}
if [ "$#" -gt 0 ]; then shift; fi
cmake -S "$task_source" -B "$task_build" -DCMAKE_BUILD_TYPE=Release \
  -DMEMTABLE_BENCH_FETCH_BTREEOLC=ON -DMEMTABLE_BENCH_FETCH_UNODB=ON \
  -DMEMTABLE_BENCH_FETCH_WORMHOLE=ON "$@"
cmake --build "$task_build" --target memtable_bench mvcc_bench mvcc_contract adapter_contract key_dataset_contract -j "${BUILD_JOBS:-4}"
ctest --test-dir "$task_build" --output-on-failure
"$task_build/mvcc_bench" --list-indexes
