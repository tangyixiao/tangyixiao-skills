#!/usr/bin/env python3
"""Pinned Skill entrypoint for a separately checked-out Jianying Headless project."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

def project_root():
    configured = os.environ.get('JIANYING_HEADLESS_ROOT')
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise SystemExit('JIANYING_HEADLESS_ROOT must be an absolute checkout path')
        candidates = [path.resolve()]
    else:
        candidates = list(Path(__file__).resolve().parents)
    for path in candidates:
        marker = path / 'project.json'
        if marker.is_file() and not marker.is_symlink():
            try:
                identity = json.loads(marker.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if identity.get('id') == 'jianying-headless' and identity.get('schema') == 'jianying-headless-project/v1':
                return path
    raise SystemExit('Jianying Headless checkout unavailable. Clone the project with authorized GitHub access, '
                     'then set JIANYING_HEADLESS_ROOT to its absolute path. The Skill alone does not include the engine.')


PROJECT_ROOT = project_root()
BACKEND = PROJECT_ROOT / 'engine'
PINS = {
    'jy14_headless.py': 'fd9ec517f35e810b3e38b340a5b344861c7fb53e56053b1c39ed9e25ddbf437f',
    'native_motion.py': '5d743caaa38c921779166e5663d36f72a0c3fdb130a690ac3942a7adcf62d6c2',
    'native_effects.py': 'c46b2fc9221dd613f220564b752e532f8f3753dd5595aaffc24f41d5236e4e97',
    'native_resources.py': '0b0f3048902f7ebb4629882f2739508a828784183c949786da4024ae24bee369',
    'native_visual_effects.py': 'f8a7a2d899383a5932deabe1c7adf644c61e37016e788d361ccd6ef6c95ac30d',
    'native-resource-catalog.json': '68021d765aa212436891056d06f205ef96365e1b687a3fdc28691f00a50105c5',
    'native_compound.py': '7b0df5a74d75d8f5623b11de3f4307569f84a4c6127ec316ed6fd133fc8d0d79',
    'compound-blueprint.json': '9cba9435053280abf9072d5eaccb8586c841b11dac6854b32daf9cbdba76af8e',
    'native_edit.py': '647a63e4346ae5514b7071a9de37f237bb1ff61abf2c399cb06683a6cd9bc777',
    'native_export.py': 'dccdfaeefc44fd5419f9cd16a0f00518f7d64b5fca69f236e77bd70b998c6920',
    'native_export.cpp': '3d74947a8b05c8ca31b0dc3909e0a08be4818985646c00cc64d63fb0645cee25',
    'headless_runtime.py': 'bff4c918721295a2d98c61f9ef10a9a386e3b3a79f4c8bdeaee8682b9fa748c1',
    'blueprint.json': '91f7eddad5bff9af23eb88b53713c180e3e3d4054edd469140cfa9aa56bc1dc9',
}

for name, expected in PINS.items():
    path = BACKEND / name
    if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Headless component changed or unavailable; reverify before updating the pin: ' + name)

sys.path.insert(0, str(BACKEND))
entrypoint = 'jy14_headless.py'
if len(sys.argv) > 1 and sys.argv[1] == 'edit':
    entrypoint = 'native_edit.py'
    del sys.argv[1]
elif len(sys.argv) > 1 and sys.argv[1] == 'export':
    entrypoint = 'native_export.py'
    del sys.argv[1]
runpy.run_path(str(BACKEND / entrypoint), run_name='__main__')
