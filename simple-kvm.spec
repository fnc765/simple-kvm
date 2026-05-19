# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for simple-kvm (Windows only).

Build command:
    pyinstaller --clean simple-kvm.spec
"""

import importlib.util
from pathlib import Path

_SPEC_DIR = Path(SPECPATH)


def _get_package_dir(pkg_name: str) -> Path | None:
    """Locate a package's install directory without importing it.
    
    Uses importlib's finder mechanism which only inspects filesystem
    metadata -- no module code is executed. Works even when import
    fails due to environment-specific runtime issues.
    """
    spec = importlib.util.find_spec(pkg_name)
    if spec is None:
        return None
    # Prefer submodule_search_locations for packages (namespace/pkg)
    if spec.submodule_search_locations:
        return Path(spec.submodule_search_locations[0])
    # Fallback to __init__.py location
    if spec.origin:
        return Path(spec.origin).parent
    return None


# --- Locate dependencies for data file bundling ---
_pyside6_dir = _get_package_dir('PySide6')
_av_dir = _get_package_dir('av')

# Derive site-packages (for av.libs which sits alongside av/)
_sp = None
if _av_dir:
    _sp = _av_dir.parent
elif _pyside6_dir:
    _sp = _pyside6_dir.parent

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
    'av.codec.codec',
    'av.codec.context',
    # pygrabber -- DirectShow device enumeration
    'pygrabber.dshow_graph',
    # numpy -- used internally by av
    'numpy',
]

# --- Data files to bundle ---
_datas = []

# PySide6 plugins (platforms, styles, imageformats etc.)
if _pyside6_dir:
    _plugins = _pyside6_dir / 'plugins'
    if _plugins.exists():
        _datas.append((str(_plugins), 'PySide6/plugins'))

# av.libs (FFmpeg DLLs) -- sits alongside av/ in site-packages
if _sp:
    _avlibs = _sp / 'av.libs'
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
