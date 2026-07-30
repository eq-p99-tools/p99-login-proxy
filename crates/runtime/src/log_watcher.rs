use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};
use std::time::{Duration, SystemTime};

use proxy_core::{
    character_from_log_path, class_translate, is_raid_target, zone_to_zonekey, LogEventKind,
    LogPatterns,
};
use serde_json::{json, Value};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

use crate::events::AppEvent;
use crate::proxy_stats::ProxyStatsTracker;
use crate::watchers::WatcherHandle;
use crate::websocket::SsoClient;

const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(20);
const LOG_IDLE_SECS: u64 = 30;

struct WatcherContext {
    sso: Option<SsoClient>,
    local_character_names: Arc<RwLock<HashSet<String>>>,
    stats: Arc<ProxyStatsTracker>,
    event_tx: mpsc::Sender<AppEvent>,
}

struct LineContext<'a> {
    watcher: &'a WatcherContext,
    current_zones: &'a mut HashMap<String, String>,
    patterns: &'a LogPatterns,
}

pub struct EqLogWatcherHandle {
    cancel: CancellationToken,
}

impl EqLogWatcherHandle {
    pub fn start(
        logs_dir: PathBuf,
        sso: Option<SsoClient>,
        local_character_names: Arc<RwLock<HashSet<String>>>,
        stats: Arc<ProxyStatsTracker>,
        event_tx: mpsc::Sender<AppEvent>,
        parent_cancel: CancellationToken,
    ) -> Self {
        let cancel = parent_cancel.child_token();
        let child = cancel.child_token();
        let (event_tx_files, event_rx) = mpsc::channel(64);
        let _watcher = WatcherHandle::start(vec![logs_dir.clone()], event_tx_files, child.clone());

        tokio::spawn(async move {
            let ctx = WatcherContext {
                sso,
                local_character_names,
                stats,
                event_tx,
            };
            run_watcher_loop(logs_dir, ctx, event_rx, child).await;
        });

        Self { cancel }
    }

    pub fn stop(self) {
        self.cancel.cancel();
    }
}

async fn run_watcher_loop(
    logs_dir: PathBuf,
    ctx: WatcherContext,
    mut file_events: mpsc::Receiver<PathBuf>,
    cancel: CancellationToken,
) {
    let patterns = LogPatterns::default();
    let mut latest_log: Option<PathBuf> = None;
    let mut position: u64 = 0;
    let mut current_zones: HashMap<String, String> = HashMap::new();
    let mut heartbeat = tokio::time::interval(HEARTBEAT_INTERVAL);

    if let Some(path) = find_latest_log(&logs_dir) {
        info!(path = %path.display(), "EQ log watcher tracking");
        position = seek_to_tail(&path);
        latest_log = Some(path.clone());
        maybe_send_heartbeat(&path, ctx.sso.as_ref(), ctx.stats.as_ref(), &ctx.event_tx).await;
    } else {
        warn!(dir = %logs_dir.display(), "no eqlog_*.txt files found");
    }

    loop {
        tokio::select! {
            _ = cancel.cancelled() => break,
            _ = heartbeat.tick() => {
                if let Some(ref path) = latest_log {
                    maybe_send_heartbeat(path, ctx.sso.as_ref(), ctx.stats.as_ref(), &ctx.event_tx).await;
                }
            }
            ev = file_events.recv() => {
                if let Some(path) = ev {
                    if path.extension().and_then(|e| e.to_str()) == Some("txt") {
                        let new_latest = find_latest_log(&logs_dir);
                        if new_latest.as_ref() != latest_log.as_ref() {
                            if let Some(ref p) = new_latest {
                                info!(path = %p.display(), "switched EQ log file");
                                position = seek_to_tail(p);
                                if let Some(character) = character_from_log_path(p) {
                                    let _ = ctx.event_tx
                                        .send(AppEvent::LogFileSwitched { character })
                                        .await;
                                }
                                maybe_send_heartbeat(
                                    p,
                                    ctx.sso.as_ref(),
                                    ctx.stats.as_ref(),
                                    &ctx.event_tx,
                                )
                                .await;
                            }
                            latest_log = new_latest;
                        }
                        if latest_log.as_ref() == Some(&path) {
                            let line_ctx = LineContext {
                                watcher: &ctx,
                                current_zones: &mut current_zones,
                                patterns: &patterns,
                            };
                            position = read_new_lines(&path, position, line_ctx).await;
                        }
                    }
                }
            }
        }
    }
    debug!("EQ log watcher stopped");
}

fn find_latest_log(logs_dir: &Path) -> Option<PathBuf> {
    let mut best: Option<(SystemTime, PathBuf)> = None;
    let entries = std::fs::read_dir(logs_dir).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        let name = path.file_name()?.to_str()?;
        if !name.starts_with("eqlog_") || !name.ends_with(".txt") {
            continue;
        }
        let modified = entry.metadata().ok()?.modified().ok()?;
        if best.as_ref().is_none_or(|(t, _)| modified > *t) {
            best = Some((modified, path));
        }
    }
    best.map(|(_, p)| p)
}

fn seek_to_tail(path: &Path) -> u64 {
    let Ok(bytes) = std::fs::read(path) else {
        return 0;
    };
    LogPatterns::tail_offset(&bytes) as u64
}

async fn read_new_lines(path: &Path, position: u64, mut ctx: LineContext<'_>) -> u64 {
    let Ok(mut file) = tokio::fs::File::open(path).await else {
        return position;
    };
    use tokio::io::{AsyncReadExt, AsyncSeekExt};
    if file.seek(std::io::SeekFrom::Start(position)).await.is_err() {
        return position;
    }
    let mut buf = Vec::new();
    if file.read_to_end(&mut buf).await.is_err() {
        return position;
    }
    let text = String::from_utf8_lossy(&buf);
    let character = character_from_log_path(path).unwrap_or_default();
    let char_lc = character.to_lowercase();

    for line in text.lines() {
        let line = line.trim_end();
        if line.is_empty() {
            continue;
        }
        handle_line(line, &character, &char_lc, &mut ctx).await;
    }
    position + buf.len() as u64
}

struct LocationUpdate {
    park: Option<String>,
    bind: Option<String>,
    level: Option<u32>,
    class: Option<String>,
    items: Option<HashMap<String, Value>>,
}

async fn send_location_update(
    character: &str,
    update: &LocationUpdate,
    in_sso: bool,
    in_local: bool,
    sso: Option<&SsoClient>,
    event_tx: &mpsc::Sender<AppEvent>,
) {
    if in_sso {
        if let Some(client) = sso {
            let items_json = update.items.as_ref().map(|m| {
                m.iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect::<serde_json::Map<String, Value>>()
            });
            client
                .send_update_location(
                    character,
                    update.park.as_deref(),
                    update.bind.as_deref(),
                    update.level,
                    items_json,
                )
                .await;
        }
    }
    if in_local {
        let _ = event_tx
            .send(AppEvent::LocalCharacterUpdate {
                name: character.to_string(),
                park: update.park.clone(),
                bind: update.bind.clone(),
                level: update.level.map(|l| l as i32),
                class: update.class.clone(),
                items: update.items.clone(),
            })
            .await;
    }
}

fn character_is_tracked(
    char_lc: &str,
    sso: Option<&SsoClient>,
    local_character_names: &Arc<RwLock<HashSet<String>>>,
) -> (bool, bool) {
    let in_sso = sso.is_some_and(|client| {
        client
            .cache()
            .try_read()
            .ok()
            .is_some_and(|g| g.characters_cached.contains(char_lc))
    });
    let in_local = local_character_names
        .read()
        .ok()
        .is_some_and(|names| names.contains(char_lc));
    (in_sso, in_local)
}

async fn handle_line(line: &str, character: &str, char_lc: &str, ctx: &mut LineContext<'_>) {
    let (in_sso, in_local) = character_is_tracked(
        char_lc,
        ctx.watcher.sso.as_ref(),
        &ctx.watcher.local_character_names,
    );
    if !in_sso && !in_local {
        return;
    }

    let event = ctx.patterns.classify(line);
    let sso = ctx.watcher.sso.as_ref();
    let event_tx = &ctx.watcher.event_tx;

    match event.kind {
        LogEventKind::ZoneEnter => {
            if let Some(zone) = event.zone.as_deref() {
                let zone_key = zone_to_zonekey(zone).unwrap_or_else(|| zone.to_lowercase());
                ctx.current_zones
                    .insert(char_lc.to_string(), zone_key.clone());
                info!(%character, zone_key, "zone enter");
                send_location_update(
                    character,
                    &LocationUpdate {
                        park: Some(zone_key),
                        bind: None,
                        level: None,
                        class: None,
                        items: None,
                    },
                    in_sso,
                    in_local,
                    sso,
                    event_tx,
                )
                .await;
            }
        }
        LogEventKind::WhoZone => {
            if let Some(zone) = event.zone.as_deref() {
                if zone == "EverQuest" {
                    return;
                }
                let zone_key = zone_to_zonekey(zone).unwrap_or_else(|| zone.to_lowercase());
                ctx.current_zones
                    .insert(char_lc.to_string(), zone_key.clone());
                info!(%character, zone_key, "zone from /who");
                send_location_update(
                    character,
                    &LocationUpdate {
                        park: Some(zone_key),
                        bind: None,
                        level: None,
                        class: None,
                        items: None,
                    },
                    in_sso,
                    in_local,
                    sso,
                    event_tx,
                )
                .await;
            }
        }
        LogEventKind::BindConfirm => {
            if let Some(zone_key) = ctx.current_zones.get(char_lc) {
                info!(%character, zone_key, "bind confirm");
                send_location_update(
                    character,
                    &LocationUpdate {
                        park: None,
                        bind: Some(zone_key.clone()),
                        level: None,
                        class: None,
                        items: None,
                    },
                    in_sso,
                    in_local,
                    sso,
                    event_tx,
                )
                .await;
            } else {
                warn!(%character, "bind detected but current zone is unknown");
            }
        }
        LogEventKind::CharinfoBind => {
            if let Some(zone) = event.zone.as_deref() {
                let zone_key = zone_to_zonekey(zone).unwrap_or_else(|| zone.to_lowercase());
                info!(%character, zone_key, "bound zone from /charinfo");
                send_location_update(
                    character,
                    &LocationUpdate {
                        park: None,
                        bind: Some(zone_key),
                        level: None,
                        class: None,
                        items: None,
                    },
                    in_sso,
                    in_local,
                    sso,
                    event_tx,
                )
                .await;
            }
        }
        LogEventKind::WhoSelf => {
            let Some(who_name) = event.character.as_deref() else {
                return;
            };
            if !who_name.eq_ignore_ascii_case(character) {
                return;
            }
            let level = event.level;
            if let Some(level) = level {
                info!(%character, level, "level from /who");
                send_location_update(
                    character,
                    &LocationUpdate {
                        park: None,
                        bind: None,
                        level: Some(level),
                        class: None,
                        items: None,
                    },
                    in_sso,
                    in_local,
                    sso,
                    event_tx,
                )
                .await;
            }
            if in_local {
                if let Some(raw_class) = event.class_name.as_deref() {
                    if let Some(resolved) = class_translate::resolve_class(raw_class) {
                        info!(%character, %resolved, "class from /who");
                        send_location_update(
                            character,
                            &LocationUpdate {
                                park: None,
                                bind: None,
                                level: None,
                                class: Some(resolved),
                                items: None,
                            },
                            false,
                            true,
                            sso,
                            event_tx,
                        )
                        .await;
                    }
                }
            }
        }
        LogEventKind::LevelUp => {
            if let Some(level) = event.level {
                info!(%character, level, "level up");
                send_location_update(
                    character,
                    &LocationUpdate {
                        park: None,
                        bind: None,
                        level: Some(level),
                        class: None,
                        items: None,
                    },
                    in_sso,
                    in_local,
                    sso,
                    event_tx,
                )
                .await;
            }
        }
        LogEventKind::VeliumVapors => {
            info!(%character, "Vial of Velium Vapors used");
            let mut items = HashMap::new();
            items.insert("thurg".to_string(), json!(false));
            send_location_update(
                character,
                &LocationUpdate {
                    park: None,
                    bind: None,
                    level: None,
                    class: None,
                    items: Some(items),
                },
                in_sso,
                in_local,
                sso,
                event_tx,
            )
            .await;
        }
        LogEventKind::Fte => {
            if let (Some(mob), Some(player), Some(time)) = (
                event.mob.as_deref(),
                event.player.as_deref(),
                event.eq_log_time.as_deref(),
            ) {
                if let Some(client) = sso {
                    info!(%character, mob, player, "FTE detected");
                    client.send_fte(mob, player, character, time).await;
                }
            }
        }
        LogEventKind::YouSlain | LogEventKind::MobKill => {
            if let (Some(mob), Some(time)) = (event.mob.as_deref(), event.eq_log_time.as_deref()) {
                if is_raid_target(mob) {
                    if let Some(client) = sso {
                        info!(%character, mob, "raid target slain");
                        client.send_mob_death(mob, time, character).await;
                    }
                }
            }
        }
        _ => {}
    }
}

async fn maybe_send_heartbeat(
    path: &Path,
    sso: Option<&SsoClient>,
    stats: &ProxyStatsTracker,
    event_tx: &mpsc::Sender<AppEvent>,
) {
    let Some(client) = sso else {
        return;
    };
    if !client.is_connected() {
        return;
    }
    let Some(character) = character_from_log_path(path) else {
        return;
    };
    let char_lc = character.to_lowercase();
    let tracked = client
        .cache()
        .try_read()
        .ok()
        .is_some_and(|g| g.characters_cached.contains(&char_lc));
    if !tracked {
        return;
    }
    let Ok(meta) = std::fs::metadata(path) else {
        return;
    };
    let Ok(modified) = meta.modified() else {
        return;
    };
    let Ok(age) = SystemTime::now().duration_since(modified) else {
        return;
    };
    if age > Duration::from_secs(LOG_IDLE_SECS) {
        return;
    }
    client.send_heartbeat(&character).await;
    stats.record_heartbeat(&character);
    let _ = event_tx.send(AppEvent::StatsDirty).await;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_only_character_is_tracked_for_fte() {
        use std::collections::HashSet;
        use std::sync::{Arc, RwLock};

        use proxy_core::logs::{LogEventKind, LogPatterns};
        use secrecy::SecretString;
        use serde_json::json;

        use crate::websocket::{SsoClient, SsoClientConfig};

        let client = SsoClient::new(
            SsoClientConfig {
                api_url: "https://example.test".into(),
                backend_name: "test".into(),
                client_version: "1".into(),
                verify_tls: true,
                ca_bundle: proxy_core::SsoCaBundleMode::System,
                timeout_secs: 5,
                client_settings: json!({}),
            },
            SecretString::from("token"),
        );
        let mut names = HashSet::new();
        names.insert("hero".to_string());
        let local = Arc::new(RwLock::new(names));
        let (in_sso, in_local) = character_is_tracked("hero", Some(&client), &local);
        assert!(!in_sso);
        assert!(in_local);

        let patterns = LogPatterns::default();
        let event = patterns.classify("[Wed Jul 30 12:00:00 2026] SomeMob engages Hero!");
        assert_eq!(event.kind, LogEventKind::Fte);
        assert!(
            in_sso || in_local,
            "local-only characters should reach FTE handling when SSO is connected"
        );
    }

    #[test]
    fn zone_key_alias() {
        assert_eq!(zone_to_zonekey("Kael Drakkel").as_deref(), Some("kael"));
    }
}
