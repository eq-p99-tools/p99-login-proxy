"""Generate a PyInstaller VSVersionInfo file from config."""

from p99_sso_login_proxy import config

_M = config.APP_VERSION.major
_m = config.APP_VERSION.minor
_p = config.APP_VERSION.patch
_V = str(config.APP_VERSION)

VERSION_INFO_TEMPLATE = f"""\
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({_M}, {_m}, {_p}, 0),
    prodvers=({_M}, {_m}, {_p}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName',
                         u'P99 Login Proxy'),
            StringStruct(u'FileDescription',
                         u'P99 SSO Login Proxy'),
            StringStruct(u'FileVersion',
                         u'{_V}'),
            StringStruct(u'InternalName',
                         u'P99LoginProxy'),
            StringStruct(u'LegalCopyright',
                         u'P99 Login Proxy Contributors'),
            StringStruct(u'OriginalFilename',
                         u'P99LoginProxy-{_V}.exe'),
            StringStruct(u'ProductName',
                         u'P99 Login Proxy'),
            StringStruct(u'ProductVersion',
                         u'{_V}'),
          ])
      ]),
    VarFileInfo([VarStruct(u'Translation',
                           [1033, 1200])])
  ]
)
"""

if __name__ == "__main__":
    with open("version_info.txt", "w", encoding="utf-8") as f:
        f.write(VERSION_INFO_TEMPLATE)
    print(f"Wrote version_info.txt for v{_V}")
