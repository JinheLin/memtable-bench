include(FetchContent)
find_package(Git REQUIRED)

function(memtable_fetch name repository commit)
  FetchContent_Declare(${name}
    DOWNLOAD_COMMAND ${CMAKE_COMMAND} -DSOURCE_DIR=<SOURCE_DIR>
      -DREPOSITORY=${repository} -DCOMMIT=${commit} -DGIT_EXECUTABLE=${GIT_EXECUTABLE}
      -P ${PROJECT_SOURCE_DIR}/cmake/FetchGit.cmake
    UPDATE_COMMAND ""
    SOURCE_SUBDIR _memtable_bench_no_subdirectory)
  FetchContent_MakeAvailable(${name})
  execute_process(COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
    WORKING_DIRECTORY "${${name}_SOURCE_DIR}" OUTPUT_VARIABLE actual
    OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
  if(NOT actual STREQUAL commit)
    message(FATAL_ERROR "Unexpected ${name} commit: ${actual}; expected ${commit}")
  endif()
  set(${name}_SOURCE_DIR "${${name}_SOURCE_DIR}" PARENT_SCOPE)
  set(${name}_BINARY_DIR "${${name}_BINARY_DIR}" PARENT_SCOPE)
endfunction()

# Apply only the tracked, reviewed patch. Reconfiguration is idempotent. Local
# FETCHCONTENT_SOURCE_DIR overrides use this path too; conflicting edits fail loudly.
function(memtable_patch source patch)
  execute_process(COMMAND ${GIT_EXECUTABLE} apply --reverse --check "${patch}"
    WORKING_DIRECTORY "${source}" RESULT_VARIABLE already ERROR_QUIET OUTPUT_QUIET)
  if(NOT already EQUAL 0)
    execute_process(COMMAND ${GIT_EXECUTABLE} apply --check "${patch}"
      WORKING_DIRECTORY "${source}" COMMAND_ERROR_IS_FATAL ANY)
    execute_process(COMMAND ${GIT_EXECUTABLE} apply "${patch}"
      WORKING_DIRECTORY "${source}" COMMAND_ERROR_IS_FATAL ANY)
  endif()
endfunction()
