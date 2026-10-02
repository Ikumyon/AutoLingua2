# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files



a = Analysis(
    ['main.py'],
    pathex=['src', '.', 'build/native'],
    binaries=[],
    datas=[('ui', 'ui'), ('assets/images/app.ico', 'assets/images')]
          + collect_data_files('autolingua2.plugins.paradox_yaml', includes=['translations/*']),
    hiddenimports=['autolingua2_native', 'autolingua2.plugins.paradox_yaml.entry'],
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
