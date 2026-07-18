use std::path::Path;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum EqHostError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("eq directory invalid: missing eqgame.exe")]
    InvalidDirectory,
    #[error("eqhost.txt not found")]
    MissingEqHost,
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

    pub fn is_proxy_enabled_in_directory(dir: &Path, listen_host: &str, listen_port: u16) -> bool {
        Self::read_eqhost(dir)
            .map(|text| Self::has_active_proxy_line(&text, listen_host, listen_port))
            .unwrap_or(false)
    }

    pub fn enable_proxy(
        dir: &Path,
        listen_host: &str,
        listen_port: u16,
    ) -> Result<(), EqHostError> {
        Self::validate_eq_directory(dir)?;
        let path = dir.join("eqhost.txt");
        let backup = path.with_extension("txt.bak");
        if path.is_file() && !backup.is_file() {
            std::fs::copy(&path, &backup)?;
        }
        let content = Self::proxy_file_content(listen_host, listen_port);
        Self::atomic_write(&path, &content)?;
        Ok(())
    }

    pub fn disable_proxy(
        dir: &Path,
        _listen_host: &str,
        _listen_port: u16,
    ) -> Result<(), EqHostError> {
        let path = dir.join("eqhost.txt");
        let backup = path.with_extension("txt.bak");
        if backup.is_file() {
            std::fs::copy(&backup, &path)?;
            let _ = std::fs::remove_file(&backup);
        } else if path.is_file() {
            let _ = std::fs::remove_file(&path);
        }
        Ok(())
    }

    fn atomic_write(path: &Path, content: &str) -> Result<(), EqHostError> {
        let tmp = path.with_extension("txt.tmp");
        std::fs::write(&tmp, content.as_bytes())?;
        std::fs::rename(tmp, path)?;
        Ok(())
    }
}
