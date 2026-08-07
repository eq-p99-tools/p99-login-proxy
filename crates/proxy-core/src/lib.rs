//! Pure domain logic: config models, credential routing, EQ files, log parsing.

pub mod accounts;
pub mod accounts_cache;
pub mod app_version;
pub mod characters;
pub mod class_translate;
pub mod config;
pub mod decision;
pub mod eq_config;
pub mod eqhost;
pub mod inventory_parser;
pub mod local_data;
pub mod logs;
pub mod model;
pub mod net_util;
pub mod proxy_mode;
pub mod proxyconfig_ini;
pub mod release;
pub mod zone_translate;

pub use accounts_cache::AccountCache;
pub use app_version::{version, version_string, window_title, APP_NAME};
pub use class_translate::resolve_class;
pub use config::{
    builtin_sso_backends, config_file_path, list_sso_backend_options, load_config,
    load_config_file, parse_skip_sso_accounts, resolve_sso_api_url, resolve_sso_ca_bundle,
    save_config_file, ConfigFileV1, SsoCaBundleMode, ValidatedConfig, SSO_BACKENDS,
};
pub use decision::{CredentialDecision, CredentialRouter};
pub use eq_config::{
    detect_rustle_ui, discover_and_persist_eq_directory, ensure_eqclient_log_enabled,
    find_eq_directory, get_client_settings, is_valid_eq_directory, read_eqclient_log_enabled,
    EqConfigStatus,
};
pub use eqhost::EqHostWriter;
pub use inventory_parser::{
    character_name_from_inventory_path, inventory_items_json, is_inventory_file,
    parse_inventory_file,
};
pub use local_data::{
    load_local_accounts, load_local_characters, load_local_data, save_local_accounts,
    save_local_characters, LocalDataBundle, LocalDataError,
};
pub use logs::{character_from_log_path, is_raid_target, LogEvent, LogEventKind, LogPatterns};
pub use model::*;
pub use net_util::split_host_port;
pub use proxy_mode::ProxyMode;
pub use proxyconfig_ini::{parse_proxyconfig_ini, scrub_proxyconfig_tokens, write_proxyconfig_ini};
pub use release::{
    expected_linux_appimage_asset_name, expected_portable_exe_name,
    expected_windows_zip_asset_name, parse_v2_release_tag, release_tag_is_prerelease,
    validate_update_zip, ReleaseTagError,
};
pub use zone_translate::zone_to_zonekey;
