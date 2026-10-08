if(NOT DEFINED ROCKSDB_SOURCE_DIR OR NOT DEFINED GIT_EXECUTABLE)
  message(FATAL_ERROR "RocksDB source directory and Git executable are required")
endif()
execute_process(COMMAND ${CMAKE_COMMAND} -E env
  --unset=http_proxy --unset=https_proxy --unset=HTTP_PROXY --unset=HTTPS_PROXY
  --unset=ALL_PROXY --unset=all_proxy
  ${GIT_EXECUTABLE} -c http.proxy= -c https.proxy= clone
  --depth 1 --single-branch --branch v9.10.0
  https://github.com/facebook/rocksdb.git ${ROCKSDB_SOURCE_DIR}
  COMMAND_ERROR_IS_FATAL ANY TIMEOUT 180)
execute_process(COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
  WORKING_DIRECTORY ${ROCKSDB_SOURCE_DIR}
  OUTPUT_VARIABLE rocksdb_commit OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY)
if(NOT rocksdb_commit STREQUAL "ae8fb3e5000e46d8d4c9dbf3a36019c0aaceebff")
  message(FATAL_ERROR "Unexpected RocksDB commit: ${rocksdb_commit}")
endif()
