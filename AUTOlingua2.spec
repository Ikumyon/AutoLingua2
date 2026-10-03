# -*- mode: python ; coding: utf-8 -*-
import json
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

sys.path.insert(0, str(Path('src').resolve()))
plugin_datas = []
plugin_imports = []
for manifest in sorted(Path('src/autolingua2/plugins').glob('*/manifest.json')):
    package = 'autolingua2.plugins.' + manifest.parent.name
    data = json.loads(manifest.read_text(encoding='utf-8'))
    plugin_datas += collect_data_files(package)
    if data.get('kind', 'python') == 'python':
        plugin_imports += collect_submodules(package)

a = Analysis(
    ['main.py'],
    pathex=['src', '.', 'build/native'],
    binaries=[],
    datas=[('ui', 'ui'), ('assets/images/app.ico', 'assets/images')]
          + plugin_datas,
    hiddenimports=['autolingua2_native'] + plugin_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='autolingua2_core',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/images/app.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='core',
)
