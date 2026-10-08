#!/usr/bin/env python3
"""Fetch a verified, pinned KeyBtree subset; preserve algorithms, isolate includes.

The generated port is an index core, not a standalone ObMemtable implementation.
No upstream files are edited. See docs/oceanbase.md for the boundary.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.request

REPO = Path(__file__).resolve().parents[1]
PIN = json.loads((REPO / 'vendor/oceanbase-port/source-pin.json').read_text())
ASSERT = ('STATIC_ASSERT(sizeof(keybtree::BtreeIterator<memtable::ObStoreRowkeyWrapper, '
          'memtable::ObMvccRow *>) == 4016, "btree iterator size exceeded");')
INCLUDES = {
    'ob_keybtree.h': ['oceanbase_compat.h', 'ob_counter.h', 'ob_keybtree_deps.h'],
    'ob_keybtree.cpp': ['ob_qsync.h', 'ob_retire_station.h'],
    'ob_keybtree_deps.h': ['oceanbase_compat.h', 'ob_retire_station.h'],
    'ob_retire_station.h': ['oceanbase_compat.h', 'ob_link.h', 'ob_tsi_utils.h'],
    'ob_qsync.h': ['oceanbase_compat.h', 'ob_tsi_utils.h'],
    'ob_counter.h': ['oceanbase_compat.h', 'ob_tsi_utils.h'],
    'ob_link.h': ['oceanbase_compat.h'],
    'ob_tsi_utils.h': ['oceanbase_compat.h'],
    'ob_tsi_utils.cpp': ['ob_tsi_utils.h'],
    'ob_atomic.h': ['oceanbase_macros.h'],
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def isolate(path, data):
    """Isolate includes, qualify typedefs for GCC, replace the row-type assertion."""
    name = Path(path).name
    if name not in INCLUDES:
        return data
    text = data.decode()
    first = True

    def replace(match):
        nonlocal first
        if not first:
            return ''
        first = False
        return '\n'.join('#include "' + inc + '"' for inc in INCLUDES[name]) + '\n'

    # Keep system includes and the template's final #include "ob_keybtree.cpp".
    text = re.sub(r'^#include "(?!ob_keybtree\.cpp")[^"\n]+"[^\n]*\n', replace, text,
                  flags=re.MULTILINE)
    if name in ('ob_keybtree.h', 'ob_keybtree_deps.h'):
        # Clang accepts aliases named like the unqualified template. GCC needs
        # the template qualified; this changes declarations, never method bodies.
        text = re.sub(r'\btypedef (\w+)<BtreeKey, BtreeVal>',
                      r'typedef ::oceanbase::keybtree::\1<BtreeKey, BtreeVal>', text)
    if name == 'ob_keybtree.h':
        if text.count(ASSERT) != 1:
            raise RuntimeError('upstream iterator assertion changed')
        text = text.replace(ASSERT, '// The adapter checks this layout for its byte-key instantiation.')
    if first:
        raise RuntimeError('expected upstream includes were not found: ' + path)
    return text.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path, help='optional pinned full Git checkout; offline')
    parser.add_argument('--verify', action='store_true', help='verify without downloading or rewriting')
    args = parser.parse_args()
    if args.source:
        actual = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != PIN['commit']:
            parser.error('OceanBase checkout must be at ' + PIN['commit'])
    # Direct downloads also apply when inherited shell proxy variables are set.
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    manifest = dict(repository=PIN['repository'], commit=PIN['commit'],
                    scope='ported_keybtree_index_core', files={})
    for path, expected in PIN['files'].items():
        original = args.output / 'upstream' / path
        if args.verify or original.exists():
            data = original.read_bytes()
        elif args.source:
            data = (args.source / path).read_bytes()
        else:
            url = (PIN['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/')
                   + '/' + PIN['commit'] + '/' + path)
            with client.open(url, timeout=60) as response:
                data = response.read()
        if digest(data) != expected:
            raise RuntimeError('OceanBase source checksum mismatch: ' + path)
        generated = isolate(path, data)
        destination = args.output / ('include' if path not in ('LICENSE', 'NOTICE') else '') / Path(path).name
        if args.verify:
            if destination.read_bytes() != generated:
                raise RuntimeError('OceanBase generated port differs: ' + path)
        else:
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(data)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(generated)
        manifest['files'][path] = dict(upstream_sha256=expected, port_sha256=digest(generated))
    encoded = json.dumps(manifest, indent=2) + '\n'
    target = args.output / 'source-manifest.json'
    if args.verify:
        if target.read_text() != encoded:
            raise RuntimeError('OceanBase source manifest differs')
    else:
        target.write_text(encoded)
    print('Verified OceanBase KeyBtree core at ' + PIN['commit'])


if __name__ == '__main__':
    main()
