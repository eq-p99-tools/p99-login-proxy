import semver

__version_semver__ = semver.Version(
    major=1,
    minor=0,
    patch=0,
    prerelease=None,
    build=None
)
__version__ = f"{__version_semver__.major}.{__version_semver__.minor}.{__version_semver__.patch}"
if __version_semver__.prerelease:
    __version__ += f"+{__version_semver__.prerelease}"
if __version_semver__.build:
    __version__ += f"-{__version_semver__.build}"
