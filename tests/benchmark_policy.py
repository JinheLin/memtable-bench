#!/usr/bin/env python3
"""Check plans, advertised capabilities and completeness of filtered archives."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
from adapter_policy import (INDEXES, NATIVE_CONCURRENT, POLICY, eligible_indexes,
                            select_rows, validate_listing, validate_rows)


def plan(script, *args):
    return json.loads(subprocess.check_output(
        [sys.executable, str(REPO / 'scripts' / script), '--list-plan', *args], text=True))


def must_fail(function, *args):
    try:
        function(*args)
    except (AssertionError, RuntimeError):
        return
    raise AssertionError('invalid matrix was accepted')


listing = subprocess.check_output([sys.argv[1], '--list-indexes'], text=True)
validate_listing(listing, ['std_map'])
must_fail(validate_listing, listing.replace('native_concurrent=1', 'native_concurrent=0'), ['std_map'])
old_listing = '\n'.join('\t'.join(f for f in line.split('\t') if not f.startswith('native_concurrent='))
                        for line in listing.splitlines())
must_fail(validate_listing, old_listing, ['std_map'])

original_plan = plan('benchmark_matrix.py')
assert original_plan['formal_processes'] == 280
representative_plan = plan('sensitivity_matrix.py', '--suite', 'representative')
assert representative_plan['formal_processes'] == 336
assert plan('sensitivity_matrix.py')['formal_processes'] == 540
assert plan('sensitivity_matrix.py', '--suite', 'range-scan')['formal_processes'] == 270
for data in (original_plan, representative_plan):
    assert data['concurrency_policy'] == POLICY
    assert data['scenario_indexes']['mixed_t1'] == INDEXES
    for name, indexes in data['scenario_indexes'].items():
        if name.startswith('mixed_t') and name != 'mixed_t1':
            assert set(indexes) == NATIVE_CONCURRENT.intersection(INDEXES)
for script in ('benchmark_matrix.py', 'sensitivity_matrix.py'):
    extra = ['--suite', 'representative'] if script.startswith('sensitivity') else []
    data = plan(script, *extra, '--threads', '4,16')
    assert data['scenario_indexes']['mixed_t1'] == INDEXES
subset = plan('sensitivity_matrix.py', '--suite', 'representative', '--indexes', 'std_map,hot')
assert subset['formal_processes'] == 48
assert subset['scenario_indexes']['mixed_t4'] == subset['scenario_indexes']['mixed_t16'] == []
subset = plan('sensitivity_matrix.py', '--suite', 'representative', '--indexes', 'std_map,oceanbase_keybtree')
assert subset['scenario_indexes']['mixed_t1'] == ['std_map', 'oceanbase_keybtree']
assert subset['scenario_indexes']['mixed_t4'] == subset['scenario_indexes']['mixed_t16'] == ['oceanbase_keybtree']

source = REPO / 'benchmarks' / 'xeon79-2026-10-08'
meta = json.loads((source / 'metadata.json').read_text())
with (source / 'raw.csv').open(newline='') as stream:
    rows = list(csv.DictReader(stream))
workloads = [(s[0], s[1], s[3]) for s in meta['scenarios']]
phases = {1: ['insert', 'get', 'scan'], 2: ['mixed'],
          3: ['insert', 'freeze', 'ordered_flush', 'destroy']}
validate_rows(meta, rows, workloads, phases)
with tempfile.TemporaryDirectory(prefix='benchmark-policy-') as directory:
    included, excluded, selection = select_rows(rows, source, Path(directory))
    assert (len(included), len(excluded)) == (595, 80)
    assert (selection['included_processes'], selection['excluded_processes']) == (280, 80)
    current = dict(meta, concurrency_policy=POLICY,
                   scenario_indexes={name: eligible_indexes(INDEXES, workers)
                                     for name, _, workers in workloads},
                   planned_processes=280, completed_processes=280)
    validate_rows(current, included, workloads, phases)
    must_fail(validate_rows, current, included[1:], workloads, phases)
    must_fail(validate_rows, current, [*included, included[0]], workloads, phases)
    must_fail(validate_rows, current, [*included, excluded[0]], workloads, phases)
    wrong_capabilities = dict(current, scenario_indexes={name: INDEXES for name, _, _ in workloads})
    must_fail(validate_rows, wrong_capabilities, included, workloads, phases)
print('Plans, binary capabilities, archive selection and incomplete-matrix rejection passed')
