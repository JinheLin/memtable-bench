memtable_fetch(btreeolc https://github.com/wangziqi2016/index-microbench.git
  74cafa57d74798f209d8fcbce8c4f317ce066eae)
memtable_patch(${btreeolc_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/cmake/patches/btreeolc.patch)
target_sources(memtable_bench_index PRIVATE src/btreeolc_index.cc)
target_include_directories(memtable_bench_index SYSTEM PRIVATE ${btreeolc_SOURCE_DIR})
target_compile_definitions(memtable_bench_index PRIVATE MEMTABLE_BENCH_HAVE_BTREEOLC=1)
