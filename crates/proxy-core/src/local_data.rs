use std::collections::HashMap;
use std::fs::File;
use std::path::{Path, PathBuf};

use csv::ReaderBuilder;
use secrecy::SecretString;
use serde_json::{json, Value};
use tempfile::NamedTempFile;
use tracing::{debug, warn};

use crate::accounts::LocalAccountStore;
use crate::characters::LocalCharacterStore;
use crate::model::LocalCharacter;

#[derive(Debug, thiserror::Error)]
pub enum LocalDataError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("csv: {0}")]
    Csv(#[from] csv::Error),
}

pub fn default_local_accounts_path() -> Option<std::path::PathBuf> {
    local_data_path(|config| &config.local_accounts_file, "local_accounts.csv")
}

pub fn default_local_characters_path() -> Option<std::path::PathBuf> {
    local_data_path(
        |config| &config.local_characters_file,
        "local_characters.csv",
    )
}

fn local_data_path(
    select: impl FnOnce(&crate::config::ConfigFileV1) -> &String,
    fallback: &str,
) -> Option<PathBuf> {
    let ini_path = crate::config::config_file_path()?;
    let configured = crate::config::load_config_file(&ini_path)
        .ok()
        .map(|config| select(&config).clone())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| fallback.to_string());
    let path = PathBuf::from(configured);
    if path.is_absolute() {
        Some(path)
    } else {
        Some(
            ini_path
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .join(path),
        )
    }
}

/// Bool item wire keys (Python ``LOCAL_CHARACTER_BOOL_ITEMS``).
pub const LOCAL_CHARACTER_BOOL_ITEMS: &[&str] = &[
    "seb",
    "vp",
    "st",
    "void",
    "neck",
    "thurg",
    "reaper",
    "brass_idol",
];

/// Count item wire keys (Python ``LOCAL_CHARACTER_COUNT_ITEMS``).
pub const LOCAL_CHARACTER_COUNT_ITEMS: &[&str] =
    &["lizard", "pearl", "peridot", "mb3", "mb4", "mb5"];

/// Flat CSV columns (Python ``LOCAL_CHARACTER_FIELDS``).
pub fn local_character_csv_fields() -> Vec<String> {
    let mut fields = vec![
        "account".to_string(),
        "name".to_string(),
        "class".to_string(),
        "level".to_string(),
        "bind".to_string(),
        "park".to_string(),
    ];
    for key in LOCAL_CHARACTER_BOOL_ITEMS {
        fields.push(format!("item_{key}"));
    }
    for key in LOCAL_CHARACTER_COUNT_ITEMS {
        fields.push(format!("item_{key}"));
    }
    fields
}

const BOOL_TRUE: &[&str] = &["true", "1", "yes", "y", "t"];
const BOOL_FALSE: &[&str] = &["false", "0", "no", "n", "f"];

fn parse_optional_bool(value: Option<&str>) -> Option<bool> {
    let v = value?.trim().to_lowercase();
    if v.is_empty() {
        return None;
    }
    if BOOL_TRUE.contains(&v.as_str()) {
        return Some(true);
    }
    if BOOL_FALSE.contains(&v.as_str()) {
        return Some(false);
    }
    None
}

fn parse_optional_int(value: Option<&str>) -> Option<i32> {
    let v = value?.trim();
    if v.is_empty() {
        return None;
    }
    v.parse().ok()
}

fn format_optional_bool(value: Option<bool>) -> String {
    match value {
        Some(true) => "true".to_string(),
        Some(false) => "false".to_string(),
        None => String::new(),
    }
}

fn format_optional_int(value: Option<i32>) -> String {
    value.map(|n| n.to_string()).unwrap_or_default()
}

fn parse_bool_item(value: Option<&str>) -> Value {
    match parse_optional_bool(value) {
        Some(b) => json!(b),
        None => Value::Null,
    }
}

fn parse_count_item(value: Option<&str>) -> Value {
    match parse_optional_int(value) {
        Some(n) => json!(n),
        None => Value::Null,
    }
}

fn parse_items_from_row(row: &csv::StringRecord, headers: &[String]) -> HashMap<String, Value> {
    let mut items = HashMap::new();
    for key in LOCAL_CHARACTER_BOOL_ITEMS {
        let col = format!("item_{key}");
        let idx = headers.iter().position(|h| h == &col);
        let cell = idx.and_then(|i| row.get(i));
        items.insert((*key).to_string(), parse_bool_item(cell));
    }
    for key in LOCAL_CHARACTER_COUNT_ITEMS {
        let col = format!("item_{key}");
        let idx = headers.iter().position(|h| h == &col);
        let cell = idx.and_then(|i| row.get(i));
        items.insert((*key).to_string(), parse_count_item(cell));
    }
    items
}

fn is_python_format(headers: &[String]) -> bool {
    headers
        .first()
        .is_some_and(|h| h.eq_ignore_ascii_case("account"))
        && headers.iter().any(|h| h == "item_seb")
}

fn is_legacy_format(headers: &[String]) -> bool {
    headers
        .first()
        .is_some_and(|h| h.eq_ignore_ascii_case("name"))
        && headers
            .get(1)
            .is_some_and(|h| h.eq_ignore_ascii_case("account_alias"))
}

fn load_python_format(
    reader: &mut csv::Reader<std::fs::File>,
    headers: &[String],
) -> Result<LocalCharacterStore, csv::Error> {
    let mut store = LocalCharacterStore::default();
    for row in reader.records() {
        let row = row?;
        let name_idx = headers.iter().position(|h| h == "name");
        let account_idx = headers.iter().position(|h| h == "account");
        let Some(name_idx) = name_idx else { continue };
        let name = row.get(name_idx).map(str::trim).unwrap_or("");
        if name.is_empty() {
            continue;
        }
        let account = account_idx
            .and_then(|i| row.get(i))
            .map(str::trim)
            .unwrap_or("")
            .to_lowercase();
        let class_idx = headers.iter().position(|h| h == "class");
        let level_idx = headers.iter().position(|h| h == "level");
        let bind_idx = headers.iter().position(|h| h == "bind");
        let park_idx = headers.iter().position(|h| h == "park");
        let klass = class_idx
            .and_then(|i| row.get(i))
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string);
        let level = level_idx
            .and_then(|i| row.get(i))
            .and_then(|v| parse_optional_int(Some(v)));
        let bind = bind_idx
            .and_then(|i| row.get(i))
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string);
        let park = park_idx
            .and_then(|i| row.get(i))
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string);
        let items = parse_items_from_row(&row, headers);
        let _ = store.upsert(LocalCharacter {
            name: name.to_string(),
            account_alias: account,
            server: String::new(),
            class: klass,
            level,
            bind,
            park,
            items,
        });
        debug!(character = %name, "loaded local character (python csv)");
    }
    Ok(store)
}

fn load_legacy_format(path: &Path) -> Result<LocalCharacterStore, LocalDataError> {
    let mut store = LocalCharacterStore::default();
    let mut reader = ReaderBuilder::new().has_headers(false).from_path(path)?;
    for (row_num, row) in reader.records().enumerate() {
        let row = row?;
        if row_num == 0 && row.get(0).is_some_and(|c| c.eq_ignore_ascii_case("name")) {
            continue;
        }
        let Some(name) = row.get(0).map(str::trim).filter(|s| !s.is_empty()) else {
            continue;
        };
        let account_alias = row.get(1).unwrap_or("").trim().to_string();
        let server = row.get(2).unwrap_or("").trim().to_string();
        if account_alias.is_empty() {
            warn!(
                row = row_num,
                "skipping legacy local character row without account"
            );
            continue;
        }
        let _ = store.upsert(LocalCharacter {
            name: name.to_string(),
            account_alias,
            server,
            class: None,
            level: None,
            bind: None,
            park: None,
            items: HashMap::new(),
        });
        debug!(character = %name, "loaded local character (legacy csv)");
    }
    Ok(store)
}

/// Load ``local_characters.csv`` (Python flat schema; legacy 3-column migrated on read).
pub fn load_local_characters(path: &Path) -> Result<LocalCharacterStore, LocalDataError> {
    if !path.is_file() {
        warn!(path = %path.display(), "No local characters file found");
        return Ok(LocalCharacterStore::default());
    }

    let mut rdr = ReaderBuilder::new().flexible(true).from_path(path)?;
    let headers: Vec<String> = rdr
        .headers()?
        .iter()
        .map(|h| h.trim().to_string())
        .collect();

    if headers.is_empty() {
        return Ok(LocalCharacterStore::default());
    }

    if is_python_format(&headers) {
        return Ok(load_python_format(&mut rdr, &headers)?);
    }

    if is_legacy_format(&headers) {
        return load_legacy_format(path);
    }

    // Headerless legacy rows or unknown header — try legacy positional parser.
    load_legacy_format(path)
}

#[derive(Debug, Default, Clone)]
pub struct LocalDataBundle {
    pub accounts: LocalAccountStore,
    pub characters: LocalCharacterStore,
}

pub fn load_local_data() -> LocalDataBundle {
    let accounts_path = default_local_accounts_path();
    let chars_path = default_local_characters_path();
    let accounts = accounts_path
        .as_ref()
        .and_then(|p| load_local_accounts(p).ok())
        .unwrap_or_default();
    let characters = chars_path
        .as_ref()
        .and_then(|p| load_local_characters(p).ok())
        .unwrap_or_default();
    LocalDataBundle {
        accounts,
        characters,
    }
}

/// Load both local CSVs without converting read or parse failures into empty data.
pub fn try_load_local_data() -> Result<LocalDataBundle, LocalDataError> {
    let accounts_path = default_local_accounts_path().ok_or_else(config_dir_unavailable)?;
    let characters_path = default_local_characters_path().ok_or_else(config_dir_unavailable)?;
    Ok(LocalDataBundle {
        accounts: load_local_accounts(&accounts_path)?,
        characters: load_local_characters(&characters_path)?,
    })
}

fn config_dir_unavailable() -> LocalDataError {
    LocalDataError::Io(std::io::Error::new(
        std::io::ErrorKind::NotFound,
        "config dir unavailable",
    ))
}

/// Load ``local_accounts.csv`` (Python-compatible: name,password,aliases).
pub fn load_local_accounts(path: &Path) -> Result<LocalAccountStore, LocalDataError> {
    let mut store = LocalAccountStore::default();
    if !path.is_file() {
        warn!(path = %path.display(), "No local accounts file found");
        return Ok(store);
    }
    let mut reader = ReaderBuilder::new().has_headers(false).from_path(path)?;
    for (row_num, row) in reader.records().enumerate() {
        let row = row?;
        if row_num == 0 && row.get(0).is_some_and(|c| c.eq_ignore_ascii_case("name")) {
            continue;
        }
        let Some(name) = row.get(0).map(str::trim).filter(|s| !s.is_empty()) else {
            continue;
        };
        let password = row.get(1).unwrap_or("").to_string();
        store.insert(
            name.to_string(),
            name.to_string(),
            SecretString::from(password),
        );
        if let Some(aliases) = row.get(2) {
            for alias in aliases.split('|').map(str::trim).filter(|s| !s.is_empty()) {
                store.insert(
                    alias.to_string(),
                    name.to_string(),
                    SecretString::from(row.get(1).unwrap_or("").to_string()),
                );
            }
        }
        debug!(account = %name, "loaded local account");
    }
    Ok(store)
}

/// Persist local accounts to the default config path (Python-compatible CSV).
pub fn save_local_accounts(store: &LocalAccountStore) -> Result<(), LocalDataError> {
    let path = default_local_accounts_path().ok_or_else(config_dir_unavailable)?;
    save_local_accounts_to(&path, store)
}

pub fn save_local_accounts_to(
    path: &Path,
    store: &LocalAccountStore,
) -> Result<(), LocalDataError> {
    atomic_csv_write(path, |wtr| {
        wtr.write_record(["name", "password", "aliases"])?;
        for (name, password, aliases) in store.rows_for_csv() {
            let alias_field = aliases.join("|");
            wtr.write_record([&name, &password, &alias_field])?;
        }
        Ok(())
    })
}

/// Persist local characters to the default config path (Python flat CSV).
pub fn save_local_characters(store: &LocalCharacterStore) -> Result<(), LocalDataError> {
    let path = default_local_characters_path().ok_or_else(config_dir_unavailable)?;
    save_local_characters_to(&path, store)
}

pub fn save_local_characters_to(
    path: &Path,
    store: &LocalCharacterStore,
) -> Result<(), LocalDataError> {
    let fields = local_character_csv_fields();
    atomic_csv_write(path, |wtr| {
        wtr.write_record(fields.iter().map(String::as_str))?;

        let mut chars: Vec<_> = store.list();
        chars.sort_by_key(|a| a.name.to_lowercase());

        for ch in chars {
            let items = &ch.items;
            let mut row = vec![
                ch.account_alias.to_lowercase(),
                ch.name.clone(),
                ch.class.clone().unwrap_or_default(),
                format_optional_int(ch.level),
                ch.bind.clone().unwrap_or_default(),
                ch.park.clone().unwrap_or_default(),
            ];
            for key in LOCAL_CHARACTER_BOOL_ITEMS {
                let val = items.get(*key);
                let parsed = val.and_then(|v| match v {
                    Value::Bool(b) => Some(*b),
                    Value::Null => None,
                    _ => None,
                });
                row.push(format_optional_bool(parsed));
            }
            for key in LOCAL_CHARACTER_COUNT_ITEMS {
                let val = items.get(*key);
                let parsed = val.and_then(|v| match v {
                    Value::Number(n) => n.as_i64().map(|i| i as i32),
                    Value::Null => None,
                    _ => None,
                });
                row.push(format_optional_int(parsed));
            }
            wtr.write_record(row.iter().map(String::as_str))?;
        }
        Ok(())
    })
}

fn atomic_csv_write(
    path: &Path,
    write_records: impl FnOnce(&mut csv::Writer<&mut File>) -> Result<(), csv::Error>,
) -> Result<(), LocalDataError> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent)?;
    let mut temp = NamedTempFile::new_in(parent)?;
    {
        let mut writer = csv::Writer::from_writer(temp.as_file_mut());
        write_records(&mut writer)?;
        writer.flush()?;
    }
    temp.as_file().sync_all()?;

    if path.is_file() {
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("csv");
        std::fs::copy(path, path.with_extension(format!("{extension}.bak")))?;
    }
    temp.persist(path).map_err(|error| error.error)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn loads_accounts_with_aliases() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("local_accounts.csv");
        std::fs::write(&path, "name,password,aliases\nmain,secret,alias1|alias2\n").unwrap();
        let store = load_local_accounts(&path).unwrap();
        assert!(store.resolve("main").is_some());
        assert!(store.resolve("alias1").is_some());
    }

    #[test]
    fn loads_python_local_characters_csv() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("local_characters.csv");
        let header = local_character_csv_fields().join(",");
        std::fs::write(
            &path,
            format!("{header}\nmain,Alice,Cleric,60,kael,nro,true,false,,,,,,,3,,,,,\n"),
        )
        .unwrap();
        let store = load_local_characters(&path).unwrap();
        let list = store.list();
        assert_eq!(list.len(), 1);
        let ch = list.into_iter().next().unwrap();
        assert_eq!(ch.name, "Alice");
        assert_eq!(ch.account_alias, "main");
        assert_eq!(ch.class.as_deref(), Some("Cleric"));
        assert_eq!(ch.level, Some(60));
        assert_eq!(ch.bind.as_deref(), Some("kael"));
        assert_eq!(ch.park.as_deref(), Some("nro"));
        assert_eq!(ch.items.get("seb"), Some(&json!(true)));
        assert_eq!(ch.items.get("vp"), Some(&json!(false)));
        assert_eq!(ch.items.get("lizard"), Some(&json!(3)));
    }

    #[test]
    fn migrates_legacy_three_column_csv() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("local_characters.csv");
        std::fs::write(&path, "name,account_alias,server\nBob,main,p99\n").unwrap();
        let store = load_local_characters(&path).unwrap();
        let ch = store.list().into_iter().next().unwrap();
        assert_eq!(ch.name, "Bob");
        assert_eq!(ch.account_alias, "main");
        assert_eq!(ch.server, "p99");
        assert!(ch.class.is_none());
    }

    #[test]
    fn saves_python_csv_format() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("local_characters.csv");
        let mut store = LocalCharacterStore::default();
        let mut items = HashMap::new();
        items.insert("st".to_string(), json!(true));
        items.insert("lizard".to_string(), json!(2));
        store
            .upsert(LocalCharacter {
                name: "Zara".to_string(),
                account_alias: "acct".to_string(),
                server: String::new(),
                class: Some("Warrior".to_string()),
                level: Some(55),
                bind: None,
                park: Some("nro".to_string()),
                items,
            })
            .unwrap();
        save_local_characters_to(&path, &store).unwrap();
        let text = std::fs::read_to_string(&path).unwrap();
        assert!(text.starts_with("account,name,class,level,bind,park,"));
        assert!(text.contains("acct,Zara,Warrior,55,,nro"));
        let reloaded = load_local_characters(&path).unwrap();
        let ch = reloaded.list().into_iter().next().unwrap();
        assert_eq!(ch.level, Some(55));
        assert_eq!(ch.items.get("st"), Some(&json!(true)));
        assert_eq!(ch.items.get("lizard"), Some(&json!(2)));
    }

    #[test]
    fn accounts_csv_round_trips_special_characters() {
        use crate::accounts::LocalAccountStore;
        use secrecy::{ExposeSecret, SecretString};

        let dir = TempDir::new().unwrap();
        let path = dir.path().join("local_accounts.csv");
        let password = "pass,word\"quote".to_string();
        let store = LocalAccountStore::from_rows([(
            "main".into(),
            "main".into(),
            SecretString::from(password.clone()),
        )]);
        save_local_accounts_to(&path, &store).unwrap();
        let reloaded = load_local_accounts(&path).unwrap();
        let (_, pw) = reloaded.resolve("main").expect("account row");
        assert_eq!(pw.expose_secret(), password.as_str());
    }

    #[test]
    fn account_save_is_atomic_and_preserves_backup() {
        use crate::accounts::LocalAccountStore;

        let dir = TempDir::new().unwrap();
        let path = dir.path().join("local_accounts.csv");
        let original = "name,password,aliases\nold,secret,\n";
        std::fs::write(&path, original).unwrap();
        let store = LocalAccountStore::from_rows([(
            "new".into(),
            "new".into(),
            SecretString::from("replacement".to_string()),
        )]);

        save_local_accounts_to(&path, &store).unwrap();

        assert_eq!(
            std::fs::read_to_string(path.with_extension("csv.bak")).unwrap(),
            original
        );
        let reloaded = load_local_accounts(&path).unwrap();
        assert!(reloaded.resolve("new").is_some());
        assert!(reloaded.resolve("old").is_none());
    }

    #[test]
    fn parse_optional_bool_values() {
        assert_eq!(parse_optional_bool(Some("true")), Some(true));
        assert_eq!(parse_optional_bool(Some("YES")), Some(true));
        assert_eq!(parse_optional_bool(Some("false")), Some(false));
        assert_eq!(parse_optional_bool(Some("")), None);
        assert_eq!(parse_optional_bool(None), None);
    }
}
