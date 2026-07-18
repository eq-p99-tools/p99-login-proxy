use serde::{Deserialize, Serialize};

/// Three-state proxy mode matching the Python UI combo box.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProxyMode {
    EnabledSso,
    EnabledProxyOnly,
    Disabled,
}

impl Default for ProxyMode {
    fn default() -> Self {
        Self::Disabled
    }
}

impl ProxyMode {
    pub fn from_index(index: i32) -> Self {
        match index {
            1 => Self::EnabledProxyOnly,
            2 => Self::Disabled,
            _ => Self::EnabledSso,
        }
    }

    pub fn to_index(self) -> i32 {
        match self {
            Self::EnabledSso => 0,
            Self::EnabledProxyOnly => 1,
            Self::Disabled => 2,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::EnabledSso => "Enabled (SSO)",
            Self::EnabledProxyOnly => "Enabled (Proxy Only)",
            Self::Disabled => "Disabled",
        }
    }

    pub fn is_running(self) -> bool {
        !matches!(self, Self::Disabled)
    }

    pub fn proxy_only(self) -> bool {
        matches!(self, Self::EnabledProxyOnly)
    }

    /// Derive UI proxy mode from persisted ``proxy_enabled`` / ``proxy_only`` flags.
    pub fn from_config(proxy_enabled: bool, proxy_only: bool) -> Self {
        if !proxy_enabled {
            Self::Disabled
        } else if proxy_only {
            Self::EnabledProxyOnly
        } else {
            Self::EnabledSso
        }
    }
}
