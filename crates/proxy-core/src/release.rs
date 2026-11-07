//! Release tag parsing and portable update archive validation.

use std::cmp::Ordering;
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

/// Order release versions as the release tags mean them.
///
/// Semver compares a prerelease identifier such as `rc10` as plain text, so
/// `2.0.0-rc10` sorts before `2.0.0-rc9`. This compares runs of digits inside
/// each prerelease identifier as numbers instead; everything else (core
/// version first, a release above its prereleases, more identifiers above
/// fewer) follows semver. Build metadata is ignored.
pub fn cmp_release_versions(a: &Version, b: &Version) -> Ordering {
    (a.major, a.minor, a.patch)
        .cmp(&(b.major, b.minor, b.patch))
        .then_with(|| match (a.pre.is_empty(), b.pre.is_empty()) {
            (true, true) => Ordering::Equal,
            (true, false) => Ordering::Greater,
            (false, true) => Ordering::Less,
            (false, false) => {
                let mut left = a.pre.as_str().split('.');
                let mut right = b.pre.as_str().split('.');
                loop {
                    match (left.next(), right.next()) {
                        (None, None) => return Ordering::Equal,
                        (None, Some(_)) => return Ordering::Less,
                        (Some(_), None) => return Ordering::Greater,
                        (Some(l), Some(r)) => match cmp_identifier(l, r) {
                            Ordering::Equal => {}
                            other => return other,
                        },
                    }
                }
            }
        })
}

/// Compare one prerelease identifier, digit runs numerically.
fn cmp_identifier(a: &str, b: &str) -> Ordering {
    let (mut a, mut b) = (a, b);
    loop {
        match (a.is_empty(), b.is_empty()) {
            (true, true) => return Ordering::Equal,
            (true, false) => return Ordering::Less,
            (false, true) => return Ordering::Greater,
            (false, false) => {}
        }
        let a_digits = a.starts_with(|c: char| c.is_ascii_digit());
        let b_digits = b.starts_with(|c: char| c.is_ascii_digit());
        let (a_run, a_rest) = split_run(a, a_digits);
        let (b_run, b_rest) = split_run(b, b_digits);
        let order = match (a_digits, b_digits) {
            // Semver: numeric identifiers sort below alphanumeric ones.
            (true, false) => Ordering::Less,
            (false, true) => Ordering::Greater,
            (true, true) => {
                let a_num = a_run.trim_start_matches('0');
                let b_num = b_run.trim_start_matches('0');
                a_num.len().cmp(&b_num.len()).then_with(|| a_num.cmp(b_num))
            }
            (false, false) => a_run.cmp(b_run),
        };
        if order != Ordering::Equal {
            return order;
        }
        (a, b) = (a_rest, b_rest);
    }
}

/// Split off the leading run of digits (or of non-digits).
fn split_run(text: &str, digits: bool) -> (&str, &str) {
    let end = text
        .find(|c: char| c.is_ascii_digit() != digits)
        .unwrap_or(text.len());
    text.split_at(end)
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

    fn release_cmp(a: &str, b: &str) -> Ordering {
        cmp_release_versions(&Version::parse(a).unwrap(), &Version::parse(b).unwrap())
    }

    #[test]
    fn release_candidates_order_by_number() {
        assert_eq!(release_cmp("2.0.0-rc10", "2.0.0-rc9"), Ordering::Greater);
        assert_eq!(release_cmp("2.0.0-rc9", "2.0.0-rc10"), Ordering::Less);
        assert_eq!(release_cmp("2.0.0-rc10", "2.0.0-rc10"), Ordering::Equal);
        assert_eq!(release_cmp("2.0.0-rc.10", "2.0.0-rc.9"), Ordering::Greater);
        assert_eq!(release_cmp("2.0.0-rc010", "2.0.0-rc9"), Ordering::Greater);
    }

    #[test]
    fn release_order_otherwise_follows_semver() {
        assert_eq!(release_cmp("2.0.0", "2.0.0-rc10"), Ordering::Greater);
        assert_eq!(release_cmp("2.0.1-rc1", "2.0.0-rc10"), Ordering::Greater);
        assert_eq!(release_cmp("2.0.1-rc1", "2.0.0"), Ordering::Greater);
        assert_eq!(
            release_cmp("2.0.0-beta1", "2.0.0-alpha2"),
            Ordering::Greater
        );
        assert_eq!(release_cmp("2.0.0-rc", "2.0.0-rc1"), Ordering::Less);
        assert_eq!(release_cmp("2.0.0-rc.1", "2.0.0-rc"), Ordering::Greater);
        assert_eq!(release_cmp("2.0.0-1", "2.0.0-rc"), Ordering::Less);
        assert_eq!(release_cmp("2.0.0-rc1", "2.0.0-rc1.1"), Ordering::Less);
        assert_eq!(release_cmp("2.0.0+b1", "2.0.0+b2"), Ordering::Equal);
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
