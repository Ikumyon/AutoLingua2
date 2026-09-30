# -*- mode: python ; coding: utf-8 -*-
from autolingua2_native import bootstrap as native_bootstrap

if not hasattr(native_bootstrap, "CoreSession"):
    raise RuntimeError("Rebuild/install autolingua2-native before packaging")


a = Analysis(
    ['main.py'],
    pathex=['src', '.', 'build/native'],
    binaries=[],
    datas=[('ui/*.ui', 'ui')],
    hiddenimports=['autolingua2_native'],
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AUTOlingua2',
)
