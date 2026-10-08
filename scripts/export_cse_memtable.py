#!/usr/bin/env python3
"""Export the pinned MemTable core from an authorized local CSE checkout.

The export stays in ignored vendor storage; no CSE sources are redistributed
by this repository. Use the export directory on hosts without that checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / 'rust/cse_memtable/source-pin.json'


def verify(export):
    pin = json.loads(PIN.read_text())
    manifest = json.loads((export / 'source-manifest.json').read_text())
    if manifest != pin:
        raise ValueError('CSE export manifest differs from source pin')
    for name, digest in pin['files'].items():
        if hashlib.sha256((export / Path(name).name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'CSE source hash differs: {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        verify(args.output)
        return
    if args.source is None:
        parser.error('--source is required to export')
    pin = json.loads(PIN.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    for name, digest in pin['files'].items():
        data = subprocess.check_output(['git', '-C', str(args.source), 'show', f'{pin["commit"]}:{name}'])
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'pinned source differs: {name}')
        (args.output / Path(name).name).write_bytes(data)
    for name in ['COMMERCIAL-LICENSE', 'THIRD-PARTY-LICENSE']:
        data = subprocess.check_output(['git', '-C', str(args.source), 'show', f'{pin["commit"]}:{name}'])
        (args.output / name).write_bytes(data)
    (args.output / 'source-manifest.json').write_text(json.dumps(pin, indent=2) + '\n')
    verify(args.output)
    print(f'exported and verified CSE {pin["commit"]} to {args.output}')


if __name__ == '__main__':
    main()
