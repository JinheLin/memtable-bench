foreach(required SOURCE_DIR REPOSITORY COMMIT GIT_EXECUTABLE)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "Missing ${required} for pinned vendor download")
  endif()
endforeach()
file(MAKE_DIRECTORY "${SOURCE_DIR}")
set(no_proxy ${CMAKE_COMMAND} -E env
  --unset=http_proxy --unset=https_proxy --unset=HTTP_PROXY --unset=HTTPS_PROXY
  --unset=ALL_PROXY --unset=all_proxy ${GIT_EXECUTABLE} -c http.proxy= -c https.proxy=)
execute_process(COMMAND ${no_proxy} init "${SOURCE_DIR}" COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND ${no_proxy} fetch --depth 1 "${REPOSITORY}" "${COMMIT}"
  WORKING_DIRECTORY "${SOURCE_DIR}" COMMAND_ERROR_IS_FATAL ANY TIMEOUT 180)
execute_process(COMMAND ${GIT_EXECUTABLE} checkout --detach FETCH_HEAD
  WORKING_DIRECTORY "${SOURCE_DIR}" COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND ${GIT_EXECUTABLE} rev-parse HEAD WORKING_DIRECTORY "${SOURCE_DIR}"
  OUTPUT_VARIABLE actual OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
if(NOT actual STREQUAL COMMIT)
  message(FATAL_ERROR "Expected ${COMMIT}, got ${actual} in ${SOURCE_DIR}")
endif()
