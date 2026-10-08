find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_program(CARGO_EXECUTABLE cargo REQUIRED)
find_program(RUSTC_EXECUTABLE rustc REQUIRED)
execute_process(COMMAND ${RUSTC_EXECUTABLE} +stable -vV OUTPUT_VARIABLE rustc_info
  COMMAND_ERROR_IS_FATAL ANY)
string(REGEX MATCH "host: ([^\n]+)" rustc_host "${rustc_info}")
set(rustc_host "${CMAKE_MATCH_1}")
if(NOT rustc_host MATCHES "^x86_64-.*-linux-")
  message(FATAL_ERROR "CSE requires a native Linux x86-64 Rust toolchain")
endif()
string(TOUPPER "${rustc_host}" rust_target_env)
string(REPLACE "-" "_" rust_target_env "${rust_target_env}")
get_filename_component(cse_export "${MEMTABLE_BENCH_CSE_SOURCE_DIR}" ABSOLUTE)
execute_process(COMMAND ${Python3_EXECUTABLE} ${PROJECT_SOURCE_DIR}/scripts/export_cse_memtable.py
  --verify --output ${cse_export} COMMAND_ERROR_IS_FATAL ANY)
set(cse_target ${CMAKE_CURRENT_BINARY_DIR}/cse-rust)
set(cse_library ${cse_target}/release/${CMAKE_STATIC_LIBRARY_PREFIX}memtable_bench_cse${CMAKE_STATIC_LIBRARY_SUFFIX})
file(GLOB_RECURSE cse_bridge_sources CONFIGURE_DEPENDS ${PROJECT_SOURCE_DIR}/rust/cse_memtable/*.rs)
add_custom_command(OUTPUT ${cse_library}
  COMMAND ${Python3_EXECUTABLE} ${PROJECT_SOURCE_DIR}/scripts/export_cse_memtable.py
    --verify --output ${cse_export}
  COMMAND ${CMAKE_COMMAND} -E env --unset=HTTP_PROXY --unset=HTTPS_PROXY --unset=ALL_PROXY
    --unset=http_proxy --unset=https_proxy --unset=all_proxy
    CSE_MEMTABLE_EXPORT=${cse_export}
    CARGO_TARGET_${rust_target_env}_LINKER=${CMAKE_CXX_COMPILER}
    CARGO_ENCODED_RUSTFLAGS=
    ${CARGO_EXECUTABLE} +stable build --locked --release
    --manifest-path ${PROJECT_SOURCE_DIR}/rust/cse_memtable/Cargo.toml --target-dir ${cse_target}
  DEPENDS ${cse_bridge_sources} ${PROJECT_SOURCE_DIR}/rust/cse_memtable/Cargo.toml
    ${PROJECT_SOURCE_DIR}/scripts/export_cse_memtable.py ${PROJECT_SOURCE_DIR}/rust/cse_memtable/source-pin.json
    ${cse_export}/source-manifest.json
    ${PROJECT_SOURCE_DIR}/rust/cse_memtable/Cargo.lock
    ${cse_export}/arena.rs ${cse_export}/skl.rs ${cse_export}/crossbeam_skl.rs
  VERBATIM)
add_custom_target(cse_rust_build DEPENDS ${cse_library})
add_library(cse_rust STATIC IMPORTED GLOBAL)
set_target_properties(cse_rust PROPERTIES IMPORTED_LOCATION ${cse_library})
add_dependencies(cse_rust cse_rust_build)
target_sources(memtable_bench_index PRIVATE src/cse_index.cc)
target_compile_definitions(memtable_bench_index PRIVATE MEMTABLE_BENCH_HAVE_CSE=1)
target_link_libraries(memtable_bench_index PRIVATE cse_rust ${CMAKE_DL_LIBS} m)
