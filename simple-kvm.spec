# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for simple-kvm (Windows only).

Build command:
    pyinstaller --clean simple-kvm.spec
"""

from pathlib import Path

# --- Resolve package paths by direct import (robust on all environments) ---
_SPEC_DIR = Path(SPECPATH)  # directory containing this spec file

# Locate site-packages via PySide6's actual installation path
import PySide6  # noqa: E402

_SP = Path(PySide6.__file__).resolve().parent.parent  # .../site-packages

# --- Hidden imports that PyInstaller may miss ---
_hiddenimports = [
    # PySide6 -- commonly missed submodules
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    # av (PyAV) -- codec/format discovery is dynamic
    'av',
    'av.codec',
    'av.format',
    'av.container',
    'av.stream',
    'av.filter',
    'av.sidedata',
    # av codec implementations (dynamic loading)
    'av.codec.codec',
    'av.codec.context',
    # pygrabber -- DirectShow device enumeration
    'pygrabber.dshow_graph',
    # numpy -- used internally by av
    'numpy',
]

# --- Data files to bundle ---
_datas = []

# Bundle PySide6 plugins (platforms, styles, imageformats etc.)
_qtdir = _SP / 'PySide6'
if _qtdir.exists():
    _datas.append((str(_qtdir / 'plugins'), 'PySide6/plugins'))

# Bundle av.libs (FFmpeg DLLs)
_avlibs = _SP / 'av.libs'
if _avlibs.exists():
    _datas.append((str(_avlibs), 'av.libs'))

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
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    # Bytecode encryption: set to a block_cipher for basic obfuscation.
    # Generate key: from PyInstaller.building.utils import block_cipher
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
    # Set to icon path when available:
    # icon=str(_SPEC_DIR / 'installer_resources/app_icon.ico'),
    icon=None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disabled for AV compatibility
    console=False,
    disable_windowed_traceback=True,  # Suppress Python traceback dialog in release builds
    argv_emulation=False,
    target_arch=None,
    # Code signing: set to your code signing identity when available
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
