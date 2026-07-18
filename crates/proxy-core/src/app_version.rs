use std::sync::LazyLock;

use semver::Version;

static APP_VERSION: LazyLock<Version> = LazyLock::new(|| {
    Version::parse(env!("CARGO_PKG_VERSION"))
        .expect("CARGO_PKG_VERSION must be valid semver")
});

pub const APP_NAME: &str = "P99 Login Proxy";

/// Parsed application semver (from `CARGO_PKG_VERSION` / workspace `Cargo.toml`).
pub fn version() -> &'static Version {
    &APP_VERSION
}

/// Canonical semver string for display and SSO client version reporting.
pub fn version_string() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

pub fn window_title() -> String {
    format!("{APP_NAME} v{}", version_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cargo_pkg_version_is_valid_semver() {
        assert_eq!(version_string(), env!("CARGO_PKG_VERSION"));
        assert_eq!(version().to_string(), version_string());
    }
}
