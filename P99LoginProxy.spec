# -*- mode: python ; coding: utf-8 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(SPEC)))

from version_info import VERSION_INFO_TEMPLATE
from p99_sso_login_proxy import config

# Write version info for this build
with open('version_info.txt', 'w', encoding='utf-8') as _vf:
    _vf.write(VERSION_INFO_TEMPLATE)

a = Analysis(
    ['p99loginproxy.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('tray_icon.png', '.'),
        ('tray_icon_proxy_only.png', '.'),
        ('tray_icon_disabled.png', '.'),
    ],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# Console + debug exe only when semver *build* metadata contains "console" (e.g. build="console" or "qt.console").
# Plain build tags like "qt" stay GUI-only (no console window).
_build_meta = getattr(config.APP_VERSION, "build", None)
CONSOLE_BUILD = "console" in str(_build_meta or "").lower()

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name=f'P99LoginProxy-{config.APP_VERSION}',
    debug=CONSOLE_BUILD,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=CONSOLE_BUILD,
    icon='tray_icon.png',
    version='version_info.txt',
)

import zipfile
import os

os.chdir('dist')
zipfile.ZipFile(f"P99LoginProxy-{config.APP_VERSION}.zip", "w", zipfile.ZIP_DEFLATED).write(
    f"P99LoginProxy-{config.APP_VERSION}.exe")
os.chdir('..')
