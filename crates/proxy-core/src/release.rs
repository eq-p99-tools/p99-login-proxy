//! Release tag parsing and portable update archive validation.

use std::io::Cursor;

use semver::Version;
use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ReleaseTagError {
    #[error("release tag must start with 'v'")]
    MissingVPrefix,
    #[error("release tag must match v2.<minor>.<patch>[-prerelease]: {0}")]
    InvalidFormat(String),
}

/// Parse a strict v2 release tag (`v2.0.0`, `v2.0.0-rc1`, …).
pub fn parse_v2_release_tag(tag: &str) -> Result<Version, ReleaseTagError> {
    let version_text = tag
        .strip_prefix('v')
        .ok_or(ReleaseTagError::MissingVPrefix)?;
    if !version_text.starts_with("2.") {
        return Err(ReleaseTagError::InvalidFormat(
            "major version must be 2".into(),
        ));
    }
    Version::parse(version_text).map_err(|error| ReleaseTagError::InvalidFormat(error.to_string()))
}

/// True when the tag suffix denotes a GitHub prerelease (e.g. `-rc1`).
pub fn release_tag_is_prerelease(tag: &str) -> bool {
    parse_v2_release_tag(tag)
        .ok()
        .is_some_and(|version| !version.pre.is_empty())
}

/// Portable executable member name inside the update zip.
pub fn expected_portable_exe_name(version: &Version) -> String {
    format!("P99LoginProxy-{version}.exe")
}

/// GitHub release asset name for the Windows portable updater zip.
pub fn expected_windows_zip_asset_name(version: &Version) -> String {
    format!("P99LoginProxy-{version}.zip")
}

/// GitHub release asset name for the Linux x86-64 AppImage.
pub fn expected_linux_appimage_asset_name(version: &Version) -> String {
    format!("P99LoginProxy-{version}-x86_64.AppImage")
}

/// Validate a legacy-compatible update archive before publication.
pub fn validate_update_zip(zip_bytes: &[u8], version: &Version) -> Result<(), String> {
    let archive = zip::ZipArchive::new(Cursor::new(zip_bytes))
        .map_err(|error| format!("invalid zip: {error}"))?;
    if archive.len() != 1 {
        return Err(format!(
            "expected exactly one zip member, found {}",
            archive.len()
        ));
    }
    let expected = expected_portable_exe_name(version);
    let entry = archive
        .index_for_path(&expected)
        .ok_or_else(|| format!("expected top-level member {expected}"))?;
    if entry != 0 {
        return Err(format!(
            "expected {expected} as the first zip member (index 0), found index {entry}"
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use super::*;

    fn sample_zip(member: &str, payload: &[u8]) -> Vec<u8> {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        zip.start_file(member, zip::write::SimpleFileOptions::default())
            .unwrap();
        zip.write_all(payload).unwrap();
        zip.finish().unwrap().into_inner()
    }

    #[test]
    fn accepts_stable_v2_tag() {
        let version = parse_v2_release_tag("v2.0.0").unwrap();
        assert_eq!(version.major, 2);
        assert!(!release_tag_is_prerelease("v2.0.0"));
    }

    #[test]
    fn accepts_prerelease_v2_tag() {
        let version = parse_v2_release_tag("v2.0.0-rc1").unwrap();
        assert_eq!(version.pre.as_str(), "rc1");
        assert!(release_tag_is_prerelease("v2.0.0-rc1"));
    }

    #[test]
    fn rejects_v1_and_malformed_tags() {
        assert!(parse_v2_release_tag("v1.4.2").is_err());
        assert!(parse_v2_release_tag("2.0.0").is_err());
        assert!(parse_v2_release_tag("v2.0").is_err());
    }

    #[test]
    fn validates_single_member_archive() {
        let version = Version::parse("2.0.0-rc1").unwrap();
        let member = expected_portable_exe_name(&version);
        let archive = sample_zip(&member, b"portable exe");
        validate_update_zip(&archive, &version).unwrap();
    }

    #[test]
    fn formats_platform_release_asset_names() {
        let version = Version::parse("2.0.0-rc1").unwrap();
        assert_eq!(
            expected_windows_zip_asset_name(&version),
            "P99LoginProxy-2.0.0-rc1.zip"
        );
        assert_eq!(
            expected_linux_appimage_asset_name(&version),
            "P99LoginProxy-2.0.0-rc1-x86_64.AppImage"
        );
    }

    #[test]
    fn rejects_extra_members_and_wrong_names() {
        let version = Version::parse("2.0.0").unwrap();
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        zip.start_file("notes.txt", zip::write::SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"extra").unwrap();
        zip.start_file(
            "P99LoginProxy-2.0.0.exe",
            zip::write::SimpleFileOptions::default(),
        )
        .unwrap();
        zip.write_all(b"exe").unwrap();
        let archive = zip.finish().unwrap().into_inner();
        assert!(validate_update_zip(&archive, &version).is_err());

        let wrong_name = sample_zip("P99LoginProxy.exe", b"exe");
        assert!(validate_update_zip(&wrong_name, &version).is_err());
    }
}
