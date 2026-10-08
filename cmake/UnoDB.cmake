function(memtable_unodb)
  memtable_fetch(unodb https://github.com/unodb-dev/unodb.git
    89f52799743ec2093426bdcf7a7cbaaa95ca848c)
  memtable_patch("${unodb_SOURCE_DIR}" "${PROJECT_SOURCE_DIR}/cmake/patches/unodb-thread-registration.patch")
  memtable_patch("${unodb_SOURCE_DIR}" "${PROJECT_SOURCE_DIR}/cmake/patches/unodb-iterator-restart.patch")
  # Respect an installed/user-selected Boost. Otherwise fetch only pinned headers.
  find_package(Boost QUIET)
  if(NOT Boost_FOUND)
    FetchContent_Declare(memtable_boost
      DOWNLOAD_COMMAND ${CMAKE_COMMAND} -DSOURCE_DIR=<SOURCE_DIR>
        -P ${PROJECT_SOURCE_DIR}/cmake/FetchBoost.cmake
      UPDATE_COMMAND "" SOURCE_SUBDIR _memtable_bench_no_subdirectory)
    FetchContent_MakeAvailable(memtable_boost)
    set(BOOST_ROOT "${memtable_boost_SOURCE_DIR}/boost_1_86_0")
    set(Boost_INCLUDE_DIR "${BOOST_ROOT}" CACHE PATH "Boost headers for UnoDB")
  endif()
  # Embedded builds should not auto-run the upstream developer's static-analysis
  # tools; sanitizers and this project's contract tests remain enabled.
  set(CLANG_TIDY_EXE "")
  set(CPPCHECK_EXE "")
  set(STANDALONE OFF)
  set(TESTS OFF)
  set(BENCHMARKS OFF)
  set(STATS OFF)
  set(AVX2 OFF)
  set(MAINTAINER_MODE OFF)
  set(BUILD_SHARED_LIBS OFF)
  add_subdirectory("${unodb_SOURCE_DIR}" "${unodb_BINARY_DIR}" EXCLUDE_FROM_ALL)
  target_sources(memtable_bench_index PRIVATE src/unodb_index.cc)
  target_compile_definitions(memtable_bench_index PRIVATE MEMTABLE_BENCH_HAVE_UNODB=1)
  target_link_libraries(memtable_bench_index PRIVATE unodb)
endfunction()
memtable_unodb()
