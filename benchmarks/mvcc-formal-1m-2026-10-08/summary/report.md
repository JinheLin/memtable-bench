# MVCC benchmark results

Validated **906 processes / 2928 phase rows**.

Each table reports the median of independent fresh-process repetitions. summary.csv includes quartiles, min/max and sample counts. Quartiles are descriptive, not confidence intervals. Compare candidates within a cohort; different key populations are kept separate.

The prefix profile changes both user-key width and shared-prefix length; the deep profile changes both version depth and snapshot lag. These are representative configurations, not independent estimates of each factor. Actual live/tombstone/missing counts remain in raw CSV.

Writes are batch submissions, not atomic transactions. GetAt materializes values; scans hash visible live rows; flush hashes every retained version and tombstone. Adapter/encoding/FFI costs are included. No WAL, SST encoding or disk I/O is measured. SWMR uses one writer and N-1 readers at a fixed historical snapshot; single-worker mixed timing is a different interleaving. Reader service throughput uses the complete group wall interval, including the tail after writing.

The shared host has CPU/NUMA binding but no frequency lock or reserved CPUs. Stage-1 scans have 1024 calls and about 16 latency samples; their p99 is not a stable tail estimate. Aggregate SWMR latency is intentionally absent. Reader service latency mixes Get and Scan. RSS deltas include allocator/runtime retention and are measured after input preparation. CSE backend accounting is not interchangeable with RSS. Phase elapsed time includes PMU start/stop and sampling setup. For a one-request Freeze phase this overhead dominates; the separately sampled call excludes PMU control but still includes clock/call instrumentation. Neither is a stable native-only Freeze latency estimate. OceanBase is the KeyBtree core port with InternalKey visibility, not full ObMemtable; its common GetAt includes filling the first native 225-entry iterator batch.

## base-1m: base

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "key_size": 16, "snapshot_lag": 2, "value_size": 32, "versions": 4}`.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Historical Get Mreq/s | Latest scan Mrows/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.551 | 0.441 | 0.443 | 0.586 | 0.517 | 779.621 | 204.373 |
| abseil_btree | 0.449 | 0.425 | 0.412 | 0.620 | 0.575 | 721.605 | 189.165 |
| tlx_btree | 0.404 | 0.525 | 0.501 | 0.671 | 0.617 | 764.188 | 200.327 |
| rocksdb_inlineskiplist | 0.539 | 0.383 | 0.386 | 1.517 | 1.214 | 300.148 | 78.682 |
| btreeolc | 0.395 | 0.421 | 0.415 | 0.424 | 0.398 | 807.723 | 211.740 |
| unodb_art | 1.053 | 0.637 | 0.630 | 0.245 | 0.239 | 822.992 | 215.742 |
| masstree | 0.878 | 0.787 | 0.738 | 0.418 | 0.379 | 1650.570 | 432.687 |
| hot | 0.862 | 0.774 | 0.762 | 0.288 | 0.278 | 1109.988 | 290.977 |
| wormhole | 1.032 | 0.521 | 0.623 | 0.627 | 0.574 | 425.148 | 111.450 |
| oceanbase_keybtree | 0.464 | 0.084 | 0.085 | 1.117 | 0.782 | 895.031 | 234.627 |
| cse_arena | 0.466 | 0.423 | 0.373 | 1.587 | 1.068 | 275.875 | 72.319 |
| cse_crossbeam | 0.408 | 0.399 | 0.344 | 1.954 | 1.086 | 714.172 | 187.216 |

### Fixed-snapshot mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.046 | — | — | — | — | — | — |
| abseil_btree | 0.046 | — | — | — | — | — | — |
| tlx_btree | 0.050 | — | — | — | — | — | — |
| rocksdb_inlineskiplist | 0.088 | 0.242 | 0.569 | 0.240 | 0.565 | 0.422 | 0.422 |
| btreeolc | 0.034 | 0.100 | 0.234 | 0.099 | 0.232 | 0.330 | 0.329 |
| unodb_art | 0.023 | 0.066 | 0.157 | 0.066 | 0.156 | 0.735 | 0.747 |
| masstree | 0.034 | 0.103 | 0.253 | 0.103 | 0.251 | 0.824 | 0.799 |
| hot | 0.025 | — | — | — | — | — | — |
| wormhole | 0.050 | 0.138 | 0.324 | 0.137 | 0.322 | 0.798 | 0.802 |
| oceanbase_keybtree | 0.040 | 0.122 | 0.284 | 0.121 | 0.281 | 0.396 | 0.399 |
| cse_arena | 0.075 | 0.237 | 0.535 | 0.235 | 0.531 | 0.389 | 0.384 |
| cse_crossbeam | 0.077 | 0.244 | 0.545 | 0.242 | 0.541 | 0.362 | 0.363 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| std_map | 7.280 | 25.726 | 0.675 | 2.949 | 1.098 |
| abseil_btree | 8.853 | 25.630 | 0.565 | 3.404 | 0.848 |
| tlx_btree | 9.893 | 25.847 | 0.576 | 4.675 | 0.694 |
| rocksdb_inlineskiplist | 7.425 | 25.191 | 0.316 | 5.524 | 0.001 |
| btreeolc | 10.172 | 25.763 | 0.677 | 3.683 | 0.173 |
| unodb_art | 3.757 | 25.846 | 0.490 | 1.901 | 1.263 |
| masstree | 4.536 | 25.190 | 0.413 | 2.267 | 0.560 |
| hot | 4.624 | 25.883 | 0.676 | 3.000 | 0.409 |
| wormhole | 3.844 | 25.164 | 0.391 | 5.396 | 1.602 |
| oceanbase_keybtree | 8.550 | 25.310 | 0.474 | 3.076 | 0.436 |
| cse_arena | 8.498 | 25.428 | 0.444 | 3.338 | 0.000 |
| cse_crossbeam | 9.842 | 25.266 | 0.497 | 3.468 | 1.293 |

## deep-1m: deep

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "key_size": 16, "snapshot_lag": 15, "value_size": 32, "versions": 16}`.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Historical Get Mreq/s | Latest scan Mrows/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.449 | 0.328 | 0.391 | 0.139 | 0.137 | 3105.105 | 203.496 |
| abseil_btree | 0.365 | 0.334 | 0.322 | 0.153 | 0.149 | 2794.965 | 183.171 |
| tlx_btree | 0.329 | 0.405 | 0.416 | 0.167 | 0.168 | 3482.297 | 228.216 |
| rocksdb_inlineskiplist | 0.391 | 0.289 | 0.287 | 0.409 | 0.320 | 1192.164 | 78.130 |
| btreeolc | 0.324 | 0.314 | 0.314 | 0.097 | 0.097 | 3219.777 | 211.011 |
| unodb_art | 0.977 | 0.585 | 0.577 | 0.064 | 0.069 | 2408.785 | 157.862 |
| masstree | 0.966 | 0.628 | 0.622 | 0.114 | 0.116 | 4483.930 | 293.859 |
| hot | 0.735 | 0.661 | 0.660 | 0.070 | 0.073 | 4473.473 | 293.174 |
| wormhole | 0.917 | 0.322 | 0.604 | 0.151 | 0.148 | 1650.492 | 108.167 |
| oceanbase_keybtree | 0.379 | 0.072 | 0.070 | 0.322 | 0.165 | 3569.816 | 233.951 |
| cse_crossbeam | 0.389 | 0.398 | 0.196 | 1.955 | 0.270 | 2510.852 | 164.551 |

### Fixed-snapshot mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.013 | — | — | — | — | — | — |
| abseil_btree | 0.014 | — | — | — | — | — | — |
| tlx_btree | 0.016 | — | — | — | — | — | — |
| rocksdb_inlineskiplist | 0.028 | 0.068 | 0.160 | 0.067 | 0.158 | 0.326 | 0.323 |
| btreeolc | 0.009 | 0.026 | 0.068 | 0.026 | 0.067 | 0.270 | 0.279 |
| unodb_art | 0.007 | 0.019 | 0.045 | 0.019 | 0.045 | 0.718 | 0.677 |
| masstree | 0.011 | 0.031 | 0.071 | 0.030 | 0.071 | 0.673 | 0.662 |
| hot | 0.007 | — | — | — | — | — | — |
| wormhole | 0.014 | 0.038 | 0.092 | 0.038 | 0.091 | 0.322 | 0.324 |
| oceanbase_keybtree | 0.013 | 0.039 | 0.096 | 0.038 | 0.095 | 0.320 | 0.324 |
| cse_crossbeam | 0.023 | 0.072 | 0.168 | 0.072 | 0.166 | 0.339 | 0.349 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| std_map | 35.681 | 26.649 | 0.627 | 2.698 | 5.159 |
| abseil_btree | 43.396 | 26.410 | 0.708 | 2.945 | 4.148 |
| tlx_btree | 48.136 | 26.021 | 0.666 | 4.571 | 3.312 |
| rocksdb_inlineskiplist | 40.555 | 28.591 | 0.442 | 4.888 | 0.002 |
| btreeolc | 49.530 | 26.322 | 0.687 | 3.022 | 1.601 |
| unodb_art | 16.231 | 26.437 | 0.608 | 1.947 | 4.878 |
| masstree | 16.275 | 26.136 | 0.470 | 2.586 | 1.350 |
| hot | 22.393 | 26.017 | 0.700 | 2.540 | 3.226 |
| wormhole | 17.405 | 26.837 | 0.576 | 5.294 | 7.346 |
| oceanbase_keybtree | 41.684 | 27.155 | 0.635 | 2.695 | 1.898 |
| cse_crossbeam | 41.143 | 26.341 | 0.573 | 2.925 | 5.511 |

## prefix-1m: prefix

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "key_layout": "global-prefix", "key_size": 32, "prefix_bytes": 24, "snapshot_lag": 2, "value_size": 32, "versions": 4}`.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Historical Get Mreq/s | Latest scan Mrows/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.539 | 0.445 | 0.468 | 0.564 | 0.527 | 840.523 | 220.338 |
| abseil_btree | 0.439 | 0.415 | 0.419 | 0.583 | 0.550 | 782.773 | 205.199 |
| tlx_btree | 0.400 | 0.521 | 0.510 | 0.661 | 0.605 | 840.207 | 220.255 |
| rocksdb_inlineskiplist | 0.512 | 0.377 | 0.379 | 1.441 | 1.171 | 361.250 | 94.700 |
| btreeolc | 0.408 | 0.420 | 0.425 | 0.411 | 0.375 | 868.789 | 227.748 |
| unodb_art | 0.993 | 0.611 | 0.608 | 0.223 | 0.216 | 700.848 | 183.723 |
| masstree | 0.982 | 0.648 | 0.655 | 0.277 | 0.265 | 1251.477 | 328.067 |
| hot | 0.795 | 0.720 | 0.697 | 0.280 | 0.269 | 1291.836 | 338.647 |
| wormhole | 0.985 | 0.496 | 0.608 | 0.585 | 0.526 | 489.238 | 128.251 |
| oceanbase_keybtree | 0.469 | 0.084 | 0.083 | 0.998 | 0.714 | 955.934 | 250.592 |
| cse_arena | 0.451 | 0.412 | 0.365 | 1.544 | 1.047 | 291.105 | 76.312 |
| cse_crossbeam | 0.403 | 0.388 | 0.344 | 1.814 | 1.054 | 729.125 | 191.136 |

### Fixed-snapshot mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.044 | — | — | — | — | — | — |
| abseil_btree | 0.046 | — | — | — | — | — | — |
| tlx_btree | 0.049 | — | — | — | — | — | — |
| rocksdb_inlineskiplist | 0.083 | 0.229 | 0.548 | 0.228 | 0.544 | 0.403 | 0.407 |
| btreeolc | 0.033 | 0.097 | 0.230 | 0.096 | 0.229 | 0.345 | 0.342 |
| unodb_art | 0.021 | 0.061 | 0.147 | 0.060 | 0.146 | 0.681 | 0.710 |
| masstree | 0.025 | 0.074 | 0.177 | 0.074 | 0.175 | 0.918 | 0.899 |
| hot | 0.024 | — | — | — | — | — | — |
| wormhole | 0.047 | 0.132 | 0.329 | 0.131 | 0.326 | 0.778 | 0.766 |
| oceanbase_keybtree | 0.038 | 0.118 | 0.280 | 0.117 | 0.278 | 0.412 | 0.406 |
| cse_arena | 0.074 | 0.221 | 0.537 | 0.219 | 0.533 | 0.363 | 0.374 |
| cse_crossbeam | 0.075 | 0.237 | 0.533 | 0.235 | 0.529 | 0.356 | 0.358 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| std_map | 7.404 | 25.838 | 0.678 | 2.590 | 1.175 |
| abseil_btree | 9.089 | 25.534 | 0.560 | 2.930 | 0.900 |
| tlx_btree | 10.063 | 24.813 | 0.570 | 3.961 | 0.759 |
| rocksdb_inlineskiplist | 7.824 | 24.818 | 0.411 | 4.826 | 0.001 |
| btreeolc | 9.834 | 25.454 | 0.710 | 2.876 | 0.186 |
| unodb_art | 4.045 | 25.561 | 0.407 | 1.857 | 1.120 |
| masstree | 4.055 | 25.694 | 0.277 | 2.540 | 0.409 |
| hot | 5.057 | 26.182 | 0.590 | 2.376 | 0.434 |
| wormhole | 4.053 | 25.437 | 0.293 | 4.672 | 1.670 |
| oceanbase_keybtree | 8.418 | 25.843 | 0.380 | 2.491 | 0.239 |
| cse_arena | 8.859 | 25.020 | 0.416 | 3.147 | 0.000 |
| cse_crossbeam | 9.944 | 25.580 | 0.480 | 3.249 | 1.315 |

## value-1m: value

User keys: 1,000,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "key_size": 16, "snapshot_lag": 2, "value_size": 1024, "versions": 4}`.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Historical Get Mreq/s | Latest scan Mrows/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.383 | 0.259 | 0.257 | 0.265 | 0.259 | 4279.930 | 1121.958 |
| abseil_btree | 0.331 | 0.249 | 0.242 | 0.279 | 0.272 | 4222.164 | 1106.815 |
| tlx_btree | 0.244 | 0.294 | 0.288 | 0.309 | 0.298 | 4768.004 | 1249.904 |
| rocksdb_inlineskiplist | 0.337 | 0.201 | 0.188 | 0.438 | 0.409 | 3837.652 | 1006.018 |
| btreeolc | 0.300 | 0.248 | 0.247 | 0.262 | 0.250 | 4307.535 | 1129.194 |
| unodb_art | 0.611 | 0.327 | 0.322 | 0.159 | 0.154 | 4323.371 | 1133.346 |
| masstree | 0.592 | 0.387 | 0.388 | 0.263 | 0.249 | 5167.133 | 1354.533 |
| hot | 0.585 | 0.375 | 0.376 | 0.183 | 0.184 | 4610.352 | 1208.576 |
| wormhole | 0.646 | 0.283 | 0.320 | 0.264 | 0.257 | 3925.734 | 1029.108 |
| oceanbase_keybtree | 0.354 | 0.064 | 0.069 | 0.409 | 0.362 | 4395.410 | 1152.230 |
| cse_crossbeam | 0.287 | 0.243 | 0.220 | 0.475 | 0.383 | 4214.293 | 1104.752 |

### Fixed-snapshot mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.022 | — | — | — | — | — | — |
| abseil_btree | 0.023 | — | — | — | — | — | — |
| tlx_btree | 0.025 | — | — | — | — | — | — |
| rocksdb_inlineskiplist | 0.032 | 0.093 | 0.222 | 0.093 | 0.220 | 0.262 | 0.275 |
| btreeolc | 0.022 | 0.065 | 0.152 | 0.065 | 0.151 | 0.253 | 0.254 |
| unodb_art | 0.014 | 0.041 | 0.099 | 0.041 | 0.098 | 0.477 | 0.466 |
| masstree | 0.023 | 0.064 | 0.141 | 0.063 | 0.140 | 0.559 | 0.532 |
| hot | 0.017 | — | — | — | — | — | — |
| wormhole | 0.023 | 0.067 | 0.158 | 0.067 | 0.157 | 0.513 | 0.519 |
| oceanbase_keybtree | 0.023 | 0.070 | 0.168 | 0.070 | 0.166 | 0.288 | 0.296 |
| cse_crossbeam | 0.030 | 0.095 | 0.226 | 0.094 | 0.224 | 0.264 | 0.260 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| std_map | 10.471 | 26.610 | 0.607 | 0.619 | 1.644 |
| abseil_btree | 12.043 | 25.923 | 0.569 | 0.556 | 1.345 |
| tlx_btree | 16.349 | 25.736 | 0.577 | 0.725 | 1.213 |
| rocksdb_inlineskiplist | 12.532 | 25.470 | 0.333 | 0.688 | 0.013 |
| btreeolc | 13.044 | 25.296 | 0.536 | 0.661 | 0.494 |
| unodb_art | 6.529 | 25.372 | 0.406 | 0.518 | 1.585 |
| masstree | 6.740 | 31.226 | 0.361 | 0.598 | 1.085 |
| hot | 6.856 | 25.609 | 0.559 | 0.633 | 1.611 |
| wormhole | 6.120 | 25.727 | 0.357 | 0.705 | 1.377 |
| oceanbase_keybtree | 11.337 | 25.555 | 0.401 | 0.640 | 0.547 |
| cse_crossbeam | 13.569 | 25.899 | 0.607 | 0.606 | 1.594 |

## deep-500k: deep

User keys: 500,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "key_size": 16, "snapshot_lag": 15, "value_size": 32, "versions": 16}`.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Historical Get Mreq/s | Latest scan Mrows/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.501 | 0.376 | 0.445 | 0.149 | 0.143 | 1552.512 | 203.491 |
| abseil_btree | 0.411 | 0.385 | 0.369 | 0.164 | 0.156 | 1397.340 | 183.152 |
| tlx_btree | 0.366 | 0.469 | 0.420 | 0.174 | 0.169 | 1741.062 | 228.205 |
| rocksdb_inlineskiplist | 0.456 | 0.335 | 0.327 | 0.442 | 0.339 | 596.117 | 78.134 |
| btreeolc | 0.359 | 0.363 | 0.361 | 0.101 | 0.102 | 1608.746 | 210.862 |
| unodb_art | 1.042 | 0.618 | 0.526 | 0.062 | 0.064 | 1407.195 | 184.444 |
| masstree | 1.061 | 0.683 | 0.658 | 0.123 | 0.120 | 2241.992 | 293.862 |
| hot | 0.788 | 0.764 | 0.702 | 0.072 | 0.074 | 2236.941 | 293.200 |
| wormhole | 0.994 | 0.450 | 0.648 | 0.162 | 0.158 | 833.332 | 109.226 |
| oceanbase_keybtree | 0.426 | 0.079 | 0.079 | 0.349 | 0.176 | 1785.242 | 233.995 |
| cse_arena | 0.551 | 0.501 | 0.252 | 0.476 | 0.249 | 486.066 | 63.710 |
| cse_crossbeam | 0.453 | 0.476 | 0.230 | 2.003 | 0.301 | 1255.570 | 164.570 |

### Fixed-snapshot mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.013 | — | — | — | — | — | — |
| abseil_btree | 0.014 | — | — | — | — | — | — |
| tlx_btree | 0.016 | — | — | — | — | — | — |
| rocksdb_inlineskiplist | 0.030 | 0.069 | 0.159 | 0.068 | 0.158 | 0.367 | 0.361 |
| btreeolc | 0.010 | 0.027 | 0.069 | 0.027 | 0.069 | 0.294 | 0.309 |
| unodb_art | 0.007 | 0.018 | 0.044 | 0.018 | 0.044 | 0.675 | 0.715 |
| masstree | 0.011 | 0.032 | 0.079 | 0.032 | 0.078 | 0.731 | 0.718 |
| hot | 0.007 | — | — | — | — | — | — |
| wormhole | 0.015 | 0.040 | 0.093 | 0.039 | 0.092 | 0.514 | 0.517 |
| oceanbase_keybtree | 0.014 | 0.042 | 0.100 | 0.041 | 0.099 | 0.365 | 0.360 |
| cse_arena | 0.022 | 0.066 | 0.148 | 0.065 | 0.147 | 0.458 | 0.436 |
| cse_crossbeam | 0.025 | 0.081 | 0.188 | 0.080 | 0.187 | 0.407 | 0.403 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| std_map | 15.948 | 26.225 | 0.742 | 2.837 | 2.370 |
| abseil_btree | 19.448 | 26.530 | 0.642 | 3.122 | 1.883 |
| tlx_btree | 21.995 | 26.019 | 0.561 | 4.654 | 1.434 |
| rocksdb_inlineskiplist | 17.632 | 25.627 | 0.378 | 5.273 | 0.001 |
| btreeolc | 22.290 | 25.767 | 0.726 | 3.354 | 0.349 |
| unodb_art | 7.641 | 25.392 | 0.415 | 1.842 | 2.970 |
| masstree | 7.736 | 25.090 | 0.358 | 2.683 | 0.684 |
| hot | 10.161 | 25.912 | 0.736 | 2.702 | 1.850 |
| wormhole | 8.062 | 25.494 | 0.379 | 5.384 | 3.176 |
| oceanbase_keybtree | 18.641 | 25.579 | 0.431 | 2.812 | 0.879 |
| cse_arena | 14.534 | 26.313 | 0.407 | 3.145 | 0.014 |
| cse_crossbeam | 17.640 | 25.902 | 0.636 | 3.197 | 2.547 |

## value-100k: value

User keys: 100,000; operation budget: 1,000,000; repetitions: 3. Profile: `{"batch_size": 32, "key_size": 16, "snapshot_lag": 2, "value_size": 1024, "versions": 4}`.

### Single-thread operations

| Index | Load Mversions/s | Latest Get Mreq/s | Historical Get Mreq/s | Latest scan Mrows/s | Historical scan Mrows/s | RSS MiB after load | Bytes/version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.548 | 0.353 | 0.345 | 0.290 | 0.277 | 427.707 | 1121.208 |
| abseil_btree | 0.479 | 0.345 | 0.339 | 0.297 | 0.288 | 422.094 | 1106.493 |
| tlx_btree | 0.320 | 0.383 | 0.372 | 0.328 | 0.312 | 476.492 | 1249.096 |
| rocksdb_inlineskiplist | 0.569 | 0.325 | 0.327 | 0.499 | 0.469 | 383.738 | 1005.947 |
| btreeolc | 0.448 | 0.349 | 0.347 | 0.283 | 0.270 | 430.086 | 1127.444 |
| unodb_art | 0.661 | 0.357 | 0.342 | 0.159 | 0.157 | 437.305 | 1146.368 |
| masstree | 0.726 | 0.452 | 0.454 | 0.285 | 0.265 | 516.512 | 1354.004 |
| hot | 0.682 | 0.436 | 0.428 | 0.198 | 0.196 | 461.637 | 1210.153 |
| wormhole | 0.851 | 0.365 | 0.352 | 0.277 | 0.276 | 400.438 | 1049.723 |
| oceanbase_keybtree | 0.495 | 0.098 | 0.097 | 0.463 | 0.393 | 439.992 | 1153.413 |
| cse_arena | 0.586 | 0.408 | 0.370 | 0.534 | 0.456 | 377.984 | 990.863 |
| cse_crossbeam | 0.469 | 0.363 | 0.324 | 0.521 | 0.428 | 421.613 | 1105.234 |

### Fixed-snapshot mixed / SWMR

| Index | 1 workers Mreq/s | 4 workers Mreq/s | 8 workers Mreq/s | 4 workers: readers Mreq/s | 8 workers: readers Mreq/s | 4 workers: writer Mversions/s | 8 workers: writer Mversions/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| std_map | 0.021 | — | — | — | — | — | — |
| abseil_btree | 0.022 | — | — | — | — | — | — |
| tlx_btree | 0.025 | — | — | — | — | — | — |
| rocksdb_inlineskiplist | 0.037 | 0.102 | 0.239 | 0.101 | 0.238 | 0.439 | 0.439 |
| btreeolc | 0.021 | 0.056 | 0.134 | 0.056 | 0.133 | 0.341 | 0.343 |
| unodb_art | 0.013 | 0.033 | 0.079 | 0.033 | 0.079 | 0.523 | 0.527 |
| masstree | 0.022 | 0.061 | 0.147 | 0.060 | 0.145 | 0.676 | 0.676 |
| hot | 0.015 | — | — | — | — | — | — |
| wormhole | 0.022 | 0.056 | 0.134 | 0.056 | 0.133 | 0.640 | 0.630 |
| oceanbase_keybtree | 0.025 | 0.069 | 0.164 | 0.069 | 0.163 | 0.388 | 0.394 |
| cse_arena | 0.035 | 0.099 | 0.238 | 0.099 | 0.236 | 0.509 | 0.471 |
| cse_crossbeam | 0.033 | 0.096 | 0.224 | 0.096 | 0.223 | 0.404 | 0.397 |

### Lifecycle

| Index | Load s | Freeze phase µs | Freeze sampled call µs | Flush Mversions/s | Destroy s |
| --- | --- | --- | --- | --- | --- |
| std_map | 0.729 | 25.693 | 0.685 | 0.629 | 0.124 |
| abseil_btree | 0.835 | 25.793 | 0.676 | 0.616 | 0.093 |
| tlx_btree | 1.235 | 25.157 | 0.501 | 0.735 | 0.106 |
| rocksdb_inlineskiplist | 0.727 | 25.581 | 0.438 | 0.699 | 0.001 |
| btreeolc | 0.878 | 25.347 | 0.541 | 0.672 | 0.048 |
| unodb_art | 0.593 | 25.204 | 0.393 | 0.514 | 0.142 |
| masstree | 0.567 | 26.331 | 0.605 | 0.618 | 0.088 |
| hot | 0.585 | 25.427 | 0.608 | 0.644 | 0.150 |
| wormhole | 0.470 | 25.536 | 0.399 | 0.709 | 0.090 |
| oceanbase_keybtree | 0.794 | 25.542 | 0.507 | 0.634 | 0.057 |
| cse_arena | 0.678 | 25.092 | 0.425 | 0.642 | 0.026 |
| cse_crossbeam | 0.866 | 26.304 | 0.565 | 0.616 | 0.129 |
