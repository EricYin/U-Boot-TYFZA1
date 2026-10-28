#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pack both verified board loaders for automatic selection in TYFZA1 recovery."""
import argparse
import hashlib
import json
from pathlib import Path

from verify_loader import loader_entries, verify

MAGIC = b"TYFZA1-UBOOT-V1\0"


def package(four_ge, two_p5g, output, stock_four_ge, stock_two_p5g):
    images = [Path(four_ge).read_bytes(), Path(two_p5g).read_bytes()]
    entries = [loader_entries(data) for data in images]
    reports = [verify(data) for data in images]
    if entries[0]['bl33'] != entries[1]['bl33']:
        raise ValueError('Both board loaders must contain the same U-Boot build')
    profiles = json.loads((Path(__file__).resolve().parents[1] / 'evidence/stock-inputs.json').read_text())
    for variant, image, stock in zip(('4ge', '2p5g'), images, (stock_four_ge, stock_two_p5g)):
        profile = next(p for p in profiles if p['variant'] == variant)
        original = Path(stock).read_bytes()
        if hashlib.sha256(original).hexdigest() != profile['boot_sha256']:
            raise ValueError('Stock backup does not match the selected board profile')
        verify(image, original)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(MAGIC + b''.join(images))
    manifest = {'format': 'TYFZA1-UBOOT-V1', 'bytes': output.stat().st_size,
                'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'variants': {name: report['boot_sha256']
                             for name, report in zip(('4ge', '2p5g'), reports)},
                'selection': 'Runtime MDIO7 RTL8221B discovery; installer independently matches local GPT/BL2/BL31'}
    output.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--4ge', dest='four_ge', type=Path, required=True)
    parser.add_argument('--2p5g', dest='two_p5g', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stock-4ge', type=Path, required=True)
    parser.add_argument('--stock-2p5g', type=Path, required=True)
    args = parser.parse_args()
    package(args.four_ge, args.two_p5g, args.output, args.stock_4ge, args.stock_2p5g)
