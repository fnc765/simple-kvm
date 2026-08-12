# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for simple-kvm (Windows only).

Build command:
    pyinstaller --clean simple-kvm.spec

Minimal spec -- PyInstaller's built-in hooks handle most dependencies.
CI uses a post-build step to copy PySide6 plugins/av.libs if needed.
"""

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

_pykakasi_datas = collect_data_files('pykakasi')
_pykakasi_metadata = copy_metadata('pykakasi')

# --- Hidden imports ---
_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'av', 'av.codec', 'av.format', 'av.container', 'av.stream',
    'av.filter', 'av.sidedata', 'av.codec.codec', 'av.codec.context',
    'pygrabber.dshow_graph',
    'pykakasi', 'pykakasi.kakasi', 'jaconv',
    'numpy',
]

# --- Excluded modules ---
_excludes = ['tkinter', 'unittest', 'test', 'pydoc', 'distutils']

a = Analysis(
    ['app/__main__.py'],
    pathex=['.'],
    binaries=[],
    datas=(
        _pykakasi_datas
        + _pykakasi_metadata
        + [('THIRD_PARTY_NOTICES.md', '.')]
    ),
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='simple-kvm',
    icon=None, debug=False,
    bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name='simple-kvm',
)
