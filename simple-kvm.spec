# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for simple-kvm (Windows only).

Build command:
    pyinstaller --clean simple-kvm.spec

Note: PySide6 6.8+ split into PySide6 (meta), PySide6_Essentials (plugins),
PySide6_Addons. This spec searches both locations for plugin bundling.
"""

import importlib.util
import sys
from pathlib import Path

_SPEC_DIR = Path(SPECPATH)


def _get_package_dir(pkg_name: str) -> Path | None:
    """Locate a package's install directory without importing it.

    Uses importlib's finder mechanism which only inspects filesystem
    metadata -- no module code is executed.
    """
    spec = importlib.util.find_spec(pkg_name)
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return Path(spec.submodule_search_locations[0])
    if spec.origin:
        return Path(spec.origin).parent
    return None


# --- Locate dependencies for data file bundling ---
_pyside6_dir = _get_package_dir('PySide6')
_av_dir = _get_package_dir('av')

# Derive site-packages (for av.libs and glob fallback)
_sp = None
if _av_dir:
    _sp = _av_dir.parent
elif _pyside6_dir:
    _sp = _pyside6_dir.parent

# --- Hidden imports that PyInstaller may miss ---
_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'av', 'av.codec', 'av.format', 'av.container', 'av.stream',
    'av.filter', 'av.sidedata', 'av.codec.codec', 'av.codec.context',
    'pygrabber.dshow_graph',
    'numpy',
]

# --- Data files to bundle ---
_datas = []

# PySide6 plugins (platforms, styles, imageformats etc.)
# PySide6 6.8+ moved plugins into PySide6_Essentials.
# Search both the package dir and any PySide6_* sibling in site-packages.
_plugins = None
_pyside6_essentials_dir = _get_package_dir('PySide6_Essentials')

for _candidate in (_pyside6_essentials_dir, _pyside6_dir):
    if _candidate:
        _p = _candidate / 'plugins'
        if _p.exists():
            _plugins = _p
            break

# Fallback: glob for PySide6*/plugins in site-packages (handles any layout)
if _plugins is None and _sp:
    _matches = sorted(_sp.glob('PySide6*/plugins'))
    if _matches:
        _plugins = _matches[0]

if _plugins:
    _datas.append((str(_plugins), 'PySide6/plugins'))
else:
    print(
        "WARNING: PySide6 plugins directory not found. "
        "The built EXE will fail to start with 'qt.qpa.plugin: "
        "Could not find the Qt platform plugin' error. "
        "Checked: PySide6_Essentials/plugins, PySide6/plugins, "
        f"PySide6*/plugins under {_sp}.",
        file=sys.stderr,
    )

# av.libs (FFmpeg DLLs) -- sits alongside av/ in site-packages
if _sp:
    _avlibs = _sp / 'av.libs'
    if _avlibs.exists():
        _datas.append((str(_avlibs), 'av.libs'))
    else:
        print(
            "WARNING: av.libs directory not found at {}".format(_avlibs),
            file=sys.stderr,
        )

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
    upx=False,  # Disabled for AV compatibility
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
