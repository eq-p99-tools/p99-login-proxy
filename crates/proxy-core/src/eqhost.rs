use std::path::Path;

use thiserror::Error;

use crate::eq_config;

#[derive(Debug, Error)]
pub enum EqHostError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("eq directory invalid: missing eqgame.exe")]
    InvalidDirectory,
    #[error("eqhost.txt not found")]
    MissingEqHost,
    #[error("no backup file found. The proxy has not been enabled yet.")]
    MissingBackup,
}

pub struct EqHostWriter;

impl EqHostWriter {
    pub fn validate_eq_directory(dir: &Path) -> Result<(), EqHostError> {
        let exe = dir.join("eqgame.exe");
        if exe.is_file() {
            return Ok(());
        }
        #[cfg(unix)]
        {
            if std::fs::read_dir(dir)?.flatten().any(|e| {
                e.file_name()
                    .to_string_lossy()
                    .eq_ignore_ascii_case("eqgame.exe")
            }) {
                return Ok(());
            }
        }
        Err(EqHostError::InvalidDirectory)
    }

    pub fn read_eqhost(dir: &Path) -> Result<String, EqHostError> {
        let path = dir.join("eqhost.txt");
        if !path.is_file() {
            return Err(EqHostError::MissingEqHost);
        }
        let bytes = std::fs::read(path)?;
        let text = String::from_utf8_lossy(&bytes).to_string();
        Ok(text.trim_start_matches('\u{feff}').to_string())
    }

    pub fn write_eqhost(dir: &Path, content: &str) -> Result<(), EqHostError> {
        Self::validate_eq_directory(dir)?;
        let path = dir.join("eqhost.txt");
        Self::prepare_eqhost_for_write(dir, &path);
        Self::atomic_write(&path, content)?;
        Ok(())
    }

    pub fn proxy_line(listen_host: &str, listen_port: u16) -> String {
        format!("Host={listen_host}:{listen_port}")
    }

    /// Address written to eqhost.txt for the EQ client. When the UDP socket binds to
    /// `0.0.0.0`, EQ still connects via loopback (`127.0.0.1` / `localhost`).
    pub fn eqhost_client_host(listen_host: &str) -> &str {
        if listen_host == "0.0.0.0" {
            "127.0.0.1"
        } else {
            listen_host
        }
    }

    pub fn proxy_file_content(listen_host: &str, listen_port: u16) -> String {
        format!(
            "[LoginServer]\n{}\n",
            Self::proxy_line(listen_host, listen_port)
        )
    }

    pub fn default_login_server_file_content(login_host: &str, login_port: u16) -> String {
        format!("[LoginServer]\nHost={login_host}:{login_port}\n")
    }

    pub fn reset_eqhost_backup(
        dir: &Path,
        login_host: &str,
        login_port: u16,
    ) -> Result<(), EqHostError> {
        Self::validate_eq_directory(dir)?;
        let backup = dir.join("eqhost.txt").with_extension("txt.bak");
        let content = Self::default_login_server_file_content(login_host, login_port);
        Self::prepare_eqhost_for_write(dir, &backup);
        Self::atomic_write(&backup, &content)?;
        Ok(())
    }

    pub fn has_active_proxy_line(text: &str, listen_host: &str, listen_port: u16) -> bool {
        let client_host = Self::eqhost_client_host(listen_host);
        let expected = Self::proxy_line(client_host, listen_port);
        let localhost_line = if client_host == "127.0.0.1" {
            Some(Self::proxy_line("localhost", listen_port))
        } else {
            None
        };
        text.lines().map(str::trim).any(|line| {
            line.eq_ignore_ascii_case(&expected)
                || localhost_line
                    .as_ref()
                    .is_some_and(|alt| line.eq_ignore_ascii_case(alt))
        })
    }

    /// True when any uncommented ``Host=`` line is not the proxy address.
    fn has_active_non_proxy_host(text: &str, listen_host: &str, listen_port: u16) -> bool {
        text.lines().map(str::trim).any(|line| {
            if line.is_empty() || line.starts_with('#') {
                return false;
            }
            let lower = line.to_lowercase();
            lower.starts_with("host=")
                && !Self::has_active_proxy_line(line, listen_host, listen_port)
        })
    }

    fn active_host_lines(text: &str) -> Vec<String> {
        text.lines()
            .map(str::trim)
            .filter(|line| !line.is_empty() && !line.starts_with('#'))
            .filter(|line| line.to_lowercase().starts_with("host="))
            .map(str::to_string)
            .collect()
    }

    /// True when eqhost.txt has exactly one active ``Host=`` line and it points at the proxy.
    pub fn is_proxy_enabled_in_directory(dir: &Path, listen_host: &str, listen_port: u16) -> bool {
        Self::read_eqhost(dir)
            .map(|text| {
                let active = Self::active_host_lines(&text);
                active.len() == 1
                    && Self::has_active_proxy_line(&active[0], listen_host, listen_port)
            })
            .unwrap_or(false)
    }

    pub fn enable_proxy(
        dir: &Path,
        listen_host: &str,
        listen_port: u16,
        login_host: &str,
        login_port: u16,
    ) -> Result<(), EqHostError> {
        Self::validate_eq_directory(dir)?;
        let path = dir.join("eqhost.txt");
        let backup = path.with_extension("txt.bak");
        Self::prepare_eqhost_for_write(dir, &path);

        if !backup.is_file() {
            let backup_content = if path.is_file() {
                let current = Self::read_eqhost(dir).unwrap_or_default();
                if Self::has_active_non_proxy_host(&current, listen_host, listen_port) {
                    if current.ends_with('\n') {
                        current
                    } else {
                        format!("{current}\n")
                    }
                } else {
                    Self::default_login_server_file_content(login_host, login_port)
                }
            } else {
                Self::default_login_server_file_content(login_host, login_port)
            };
            Self::atomic_write(&backup, &backup_content)?;
        }

        let content = Self::proxy_file_content(listen_host, listen_port);
        Self::atomic_write(&path, &content)?;
        Ok(())
    }

    pub fn disable_proxy(dir: &Path, login_host: &str, login_port: u16) -> Result<(), EqHostError> {
        let path = dir.join("eqhost.txt");
        let backup = path.with_extension("txt.bak");
        Self::prepare_eqhost_for_write(dir, &path);

        if backup.is_file() {
            std::fs::copy(&backup, &path)?;
            let _ = std::fs::remove_file(&backup);
        } else if path.is_file() {
            let content = Self::default_login_server_file_content(login_host, login_port);
            Self::atomic_write(&path, &content)?;
        }
        Ok(())
    }

    /// Restore eqhost.txt from the backup file. Errors when no backup exists.
    pub fn restore_from_backup(dir: &Path) -> Result<(), EqHostError> {
        Self::validate_eq_directory(dir)?;
        let path = dir.join("eqhost.txt");
        let backup = path.with_extension("txt.bak");
        if !backup.is_file() {
            return Err(EqHostError::MissingBackup);
        }
        Self::prepare_eqhost_for_write(dir, &path);
        std::fs::copy(&backup, &path)?;
        let _ = std::fs::remove_file(&backup);
        Ok(())
    }

    fn prepare_eqhost_for_write(dir: &Path, eqhost_path: &Path) {
        eq_config::try_clear_readonly(dir);
        if eqhost_path.is_file() {
            eq_config::try_clear_readonly(eqhost_path);
        }
    }

    fn atomic_write(path: &Path, content: &str) -> Result<(), EqHostError> {
        let tmp = path.with_extension("txt.tmp");
        std::fs::write(&tmp, content.as_bytes())?;
        std::fs::rename(tmp, path)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn test_dir() -> TempDir {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("eqgame.exe"), b"").unwrap();
        dir
    }

    #[test]
    fn disable_without_backup_writes_default_login_server() {
        let dir = test_dir();
        EqHostWriter::write_eqhost(dir.path(), "[LoginServer]\nHost=127.0.0.1:5998\n").unwrap();
        EqHostWriter::disable_proxy(dir.path(), "login.eqemulator.net", 5998).unwrap();
        let text = EqHostWriter::read_eqhost(dir.path()).unwrap();
        assert_eq!(text, "[LoginServer]\nHost=login.eqemulator.net:5998\n");
        assert!(!dir.path().join("eqhost.txt.bak").exists());
    }

    #[test]
    fn enable_over_proxy_only_file_backs_up_synthetic_default() {
        let dir = test_dir();
        EqHostWriter::write_eqhost(dir.path(), "[LoginServer]\nHost=127.0.0.1:5998\n").unwrap();
        EqHostWriter::enable_proxy(dir.path(), "127.0.0.1", 5998, "login.eqemulator.net", 5998)
            .unwrap();
        let backup = std::fs::read_to_string(dir.path().join("eqhost.txt.bak")).unwrap();
        assert_eq!(backup, "[LoginServer]\nHost=login.eqemulator.net:5998\n");
    }

    #[test]
    fn restore_from_backup_errors_when_missing() {
        let dir = test_dir();
        let err = EqHostWriter::restore_from_backup(dir.path()).unwrap_err();
        assert!(matches!(err, EqHostError::MissingBackup));
    }

    #[test]
    fn mixed_host_lines_are_not_using_proxy() {
        let dir = test_dir();
        EqHostWriter::write_eqhost(
            dir.path(),
            "[LoginServer]\nHost=127.0.0.1:5998\nHost=login.eqemulator.net:5998\n",
        )
        .unwrap();
        assert!(!EqHostWriter::is_proxy_enabled_in_directory(
            dir.path(),
            "127.0.0.1",
            5998
        ));
    }
}
