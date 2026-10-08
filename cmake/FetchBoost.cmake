foreach(variable http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy)
  unset(ENV{${variable}})
endforeach()
file(MAKE_DIRECTORY "${SOURCE_DIR}")
set(archive "${SOURCE_DIR}/boost_1_86_0.tar.bz2")
file(DOWNLOAD https://archives.boost.io/release/1.86.0/source/boost_1_86_0.tar.bz2
  "${archive}" EXPECTED_HASH
  SHA256=1bed88e40401b2cb7a1f76d4bab499e352fa4d0c5f31c0dbae64e24d34d7513b
  TLS_VERIFY ON TIMEOUT 240)
# UnoDB only needs header-only Boost.Container. Avoid extracting the unrelated
# compiled libraries, documentation, and tests from the release archive.
file(ARCHIVE_EXTRACT INPUT "${archive}" DESTINATION "${SOURCE_DIR}"
  PATTERNS "boost_1_86_0/boost/*" "boost_1_86_0/LICENSE_1_0.txt")
