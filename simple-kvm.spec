# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for simple-kvm (Windows only).

Build command:
    pyinstaller --clean simple-kvm.spec

Bundles PySide6 Qt plugins and FFmpeg DLLs via filesystem search
to handle any PySide6 installation layout (6.6 legacy, 6.8+ split).
"""

import sys
from pathlib import Path

_SPEC_DIR = Path(SPECPATH)


def _find_plugins_dir() -> Path | None:
    """Search site-packages for PySide6 plugins directory by filesystem scan.

    PySide6 6.6.x:  .../site-packages/PySide6/plugins/
    PySide6 6.8+:   .../site-packages/PySide6_Essentials/plugins/
    """
    for p in sys.path:
        sp = Path(p)
        if not sp.is_dir():
            continue
        for candidate in ('PySide6_Essentials/plugins',
                          'PySide6/plugins'):
            plugins_dir = sp / candidate
            if plugins_dir.is_dir():
                return plugins_dir
    return None


def _find_av_libs_dir() -> Path | None:
    """Search site-packages for av.libs (FFmpeg DLLs)."""
    for p in sys.path:
        sp = Path(p)
        if not sp.is_dir():
            continue
        avlibs = sp / 'av.libs'
        if avlibs.is_dir():
            return avlibs
    return None


# --- Data files to bundle ---
_datas = []

_plugins_dir = _find_plugins_dir()
if _plugins_dir:
    _datas.append((str(_plugins_dir), 'PySide6/plugins'))
    print(f"Bundling PySide6 plugins from: {_plugins_dir}", file=sys.stderr)
else:
    print(
        "ERROR: PySide6 plugins directory not found anywhere in sys.path. "
        "The built EXE will fail to start (qt.qpa.plugin error).",
        file=sys.stderr,
    )

_av_libs_dir = _find_av_libs_dir()
if _av_libs_dir:
    _datas.append((str(_av_libs_dir), 'av.libs'))
    print(f"Bundling av.libs from: {_av_libs_dir}", file=sys.stderr)
else:
    print("ERROR: av.libs (FFmpeg DLLs) not found in sys.path.", file=sys.stderr)

# --- Hidden imports ---
_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'av',
    'av.codec',
    'av.format',
    'av.container',
    'av.stream',
    'av.filter',
    'av.sidedata',
    'av.codec.codec',
    'av.codec.context',
    'pygrabber.dshow_graph',
    'numpy',
]

# --- Excluded modules ---
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
