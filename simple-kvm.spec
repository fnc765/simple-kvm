# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for simple-kvm (Windows only).

Build command:
    pyinstaller --clean simple-kvm.spec

Uses PyInstaller's collect_all() to bundle PySide6 plugins/FFmpeg DLLs
without fragile path resolution. Works across PySide6 6.6 legacy layout
and 6.8+ split layout (PySide6_Essentials/PySide6_Addons).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

_SPEC_DIR = Path(SPECPATH)

# --- Collect all data/binaries/submodules from key packages ---
# collect_all returns (datas, binaries, hiddenimports) tuple for each package.
_datas = []
_binaries = []
_hiddenimports = []

for _pkg in ('PySide6', 'PySide6_Essentials', 'av'):
    _d, _b, _h = collect_all(_pkg)
    _datas.extend(_d)
    _binaries.extend(_b)
    _hiddenimports.extend(_h)

# Additional hidden imports that collect_all may miss
_hiddenimports.extend([
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'av.codec.codec',
    'av.codec.context',
    'pygrabber.dshow_graph',
])

# --- Excluded modules (reduce binary size) ---
_excludes = [
    'tkinter',
    'unittest',
    'test',
    'pydoc',
    'distutils',
]

a = Analysis(
    ['app/__main__.py'],
    pathex=['.'],
    binaries=_binaries,
    datas=_datas,
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
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='simple-kvm',
    # icon=str(_SPEC_DIR / 'installer_resources/app_icon.ico'),
    icon=None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='simple-kvm',
)
