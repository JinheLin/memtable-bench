memtable_fetch(hot https://github.com/speedskater/hot.git
  96bf6fb7103b27e50e16a6026db8974c090ee84a)
memtable_patch(${hot_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/cmake/patches/hot-clang.patch)
memtable_patch(${hot_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/cmake/patches/hot-leaf-bound.patch)
target_sources(memtable_bench_index PRIVATE src/hot_index.cc)
target_include_directories(memtable_bench_index SYSTEM PRIVATE
  ${hot_SOURCE_DIR}/libs/hot/commons/include
  ${hot_SOURCE_DIR}/libs/hot/single-threaded/include
  ${hot_SOURCE_DIR}/libs/idx/content-helpers/include)
# Apply ISA flags to HOT alone so the binary can reject unsupported CPUs
# before any AVX2 instructions execute.
set_source_files_properties(src/hot_index.cc PROPERTIES COMPILE_OPTIONS "-mavx2;-mbmi2;-mbmi;-mpopcnt;-mlzcnt")
target_compile_definitions(memtable_bench_index PRIVATE MEMTABLE_BENCH_HAVE_HOT=1)
