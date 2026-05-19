# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for simple-kvm (Windows only).

Build command:
    pyinstaller --clean simple-kvm.spec

Note: PyInstaller v6+ has built-in hooks for PySide6 and av that
automatically collect plugins and FFmpeg DLLs. Explicit imports
here are only for modules that the hooks may miss.
"""

import importlib.util
from pathlib import Path

_SPEC_DIR = Path(SPECPATH)


def _find_package_dir(pkg_name: str) -> Path | None:
    """Locate a package's directory without importing it."""
    spec = importlib.util.find_spec(pkg_name)
    if spec and spec.origin:
        return Path(spec.origin).parent
    return None


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
# PyInstaller v6 hooks auto-collect PySide6 plugins and av.libs.
# Only add custom data here if hooks miss something.
_datas = []

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
