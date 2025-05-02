# -*- mode: python ; coding: utf-8 -*-
from p99_sso_login_proxy import config

block_cipher = None

a = Analysis(
    ['run_server.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('tray_icon.png', '.'),
        ('tray_icon_proxy_only.png', '.'),
        ('tray_icon_disabled.png', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure, 
    a.zipped_data,
    cipher=block_cipher
)

CONSOLE_BUILD = bool(config.APP_VERSION.build)

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
)
