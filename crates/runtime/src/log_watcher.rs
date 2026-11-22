use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};
use std::time::{Duration, SystemTime};

use proxy_core::{
    character_from_log_path, class_translate, is_raid_target, server_from_log_path,
    zone_to_zonekey, FactionHit, LogEventKind, LogPatterns,
};
use serde_json::{json, Value};
use tokio::sync::mpsc;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

use crate::events::AppEvent;
use crate::proxy_stats::ProxyStatsTracker;
use crate::watchers::WatcherHandle;
use crate::websocket::SsoClient;

const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(20);
const LOG_IDLE_SECS: u64 = 30;
/// A kill or turn-in logs all of its faction lines in the same second, but they
/// can arrive across several file reads; wait this long for more before sending.
const FACTION_FLUSH_DELAY: Duration = Duration::from_secs(1);
const FACTION_BATCH_MAX_HITS: usize = 50;

/// Faction hits one character logged within one log second, sent as a single
/// `faction_hits` message.
#[derive(Debug)]
struct FactionBatch {
    character: String,
    eq_log_time: String,
    hits: Vec<FactionHit>,
    flush_at: Instant,
}

/// Add a hit to the pending batch. Returns the previous batch when it is
/// complete (different character or log second, or full) and must be sent first.
fn push_faction_hit(
    batch: &mut Option<FactionBatch>,
    character: &str,
    eq_log_time: String,
    hit: FactionHit,
    now: Instant,
) -> Option<FactionBatch> {
    let done = batch.take_if(|b| {
        b.character != character
            || b.eq_log_time != eq_log_time
            || b.hits.len() >= FACTION_BATCH_MAX_HITS
    });
    let pending = batch.get_or_insert_with(|| FactionBatch {
        character: character.to_string(),
        eq_log_time,
        hits: Vec::new(),
        flush_at: now,
    });
    pending.hits.push(hit);
    pending.flush_at = now + FACTION_FLUSH_DELAY;
    done
}

async fn send_faction_batch(batch: Option<FactionBatch>, sso: Option<&SsoClient>) {
    let (Some(batch), Some(client)) = (batch, sso) else {
        return;
    };
    info!(
        character = %batch.character,
        hits = batch.hits.len(),
        "faction hits detected"
    );
    client
        .send_faction_hits(&batch.character, &batch.eq_log_time, &batch.hits)
        .await;
}

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
    faction_batch: &'a mut Option<FactionBatch>,
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
    let mut faction_batch: Option<FactionBatch> = None;
    let mut heartbeat = tokio::time::interval(HEARTBEAT_INTERVAL);

    if let Some(path) = find_latest_log(&logs_dir) {
        info!(
            path = %path.display(),
            server = server_from_log_path(&path).as_deref().unwrap_or("?"),
            sso_reporting = ctx.sso.as_ref().is_some_and(|c| c.reports_from_log(&path)),
            "EQ log watcher tracking"
        );
        position = seek_to_tail(&path);
        latest_log = Some(path.clone());
        maybe_send_heartbeat(&path, ctx.sso.as_ref(), ctx.stats.as_ref(), &ctx.event_tx).await;
    } else {
        warn!(dir = %logs_dir.display(), "no eqlog_*.txt files found");
    }

    loop {
        let faction_flush_at = faction_batch.as_ref().map(|b| b.flush_at);
        tokio::select! {
            _ = cancel.cancelled() => break,
            _ = async {
                match faction_flush_at {
                    Some(at) => tokio::time::sleep_until(at).await,
                    None => std::future::pending().await,
                }
            } => {
                send_faction_batch(faction_batch.take(), ctx.sso.as_ref()).await;
            }
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
                            send_faction_batch(faction_batch.take(), ctx.sso.as_ref()).await;
                            if let Some(ref p) = new_latest {
                                info!(
                                    path = %p.display(),
                                    server = server_from_log_path(p).as_deref().unwrap_or("?"),
                                    sso_reporting = ctx.sso.as_ref().is_some_and(|c| c.reports_from_log(p)),
                                    "switched EQ log file"
                                );
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
                                faction_batch: &mut faction_batch,
                            };
                            position = read_new_lines(&path, position, line_ctx).await;
                        }
                    }
                }
            }
        }
    }
    send_faction_batch(faction_batch.take(), ctx.sso.as_ref()).await;
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
    let reports_to_sso = ctx
        .watcher
        .sso
        .as_ref()
        .is_some_and(|client| client.reports_from_log(path));

    for line in text.lines() {
        let line = line.trim_end();
        if line.is_empty() {
            continue;
        }
        handle_line(line, &character, &char_lc, reports_to_sso, &mut ctx).await;
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

async fn handle_line(
    line: &str,
    character: &str,
    char_lc: &str,
    reports_to_sso: bool,
    ctx: &mut LineContext<'_>,
) {
    // Logs from servers outside the guild's report servers (e.g. a test
    // server) still update local characters but send nothing to the SSO backend.
    let sso = ctx.watcher.sso.as_ref().filter(|_| reports_to_sso);
    let (in_sso, in_local) = character_is_tracked(char_lc, sso, &ctx.watcher.local_character_names);
    if !in_sso && !in_local {
        return;
    }

    if let Some((eq_log_time, hit)) = ctx.patterns.faction_hit(line) {
        // Faction standing is tracked for SSO characters only.
        if in_sso && sso.is_some() {
            debug!(%character, faction = %hit.faction, direction = ?hit.direction, "faction hit");
            let done = push_faction_hit(
                ctx.faction_batch,
                character,
                eq_log_time,
                hit,
                Instant::now(),
            );
            send_faction_batch(done, sso).await;
        }
        return;
    }

    let event = ctx.patterns.classify(line);
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
    if !client.is_connected() || !client.reports_from_log(path) {
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

    fn hit(faction: &str, direction: proxy_core::FactionDirection) -> FactionHit {
        FactionHit {
            faction: faction.into(),
            direction,
        }
    }

    #[test]
    fn faction_hits_batch_per_character_and_log_second() {
        use proxy_core::FactionDirection::*;
        let t0 = Instant::now();
        let mut batch = None;
        let s1 = "Sat Nov 21 09:55:01 2026".to_string();
        let s2 = "Sat Nov 21 09:55:02 2026".to_string();

        assert!(
            push_faction_hit(&mut batch, "Hero", s1.clone(), hit("Coldain", Better), t0).is_none()
        );
        assert!(
            push_faction_hit(&mut batch, "Hero", s1.clone(), hit("Kromrif", Worse), t0).is_none()
        );
        let pending = batch.as_ref().unwrap();
        assert_eq!(pending.hits.len(), 2);
        assert_eq!(pending.flush_at, t0 + FACTION_FLUSH_DELAY);

        let done = push_faction_hit(&mut batch, "Hero", s2.clone(), hit("Coldain", Max), t0)
            .expect("new log second completes the batch");
        assert_eq!(done.eq_log_time, s1);
        assert_eq!(
            done.hits,
            vec![hit("Coldain", Better), hit("Kromrif", Worse)]
        );

        let done = push_faction_hit(&mut batch, "Other", s2.clone(), hit("Coldain", Min), t0)
            .expect("new character completes the batch");
        assert_eq!(done.character, "Hero");
        assert_eq!(batch.as_ref().unwrap().character, "Other");
    }

    #[test]
    fn faction_batch_splits_when_full() {
        use proxy_core::FactionDirection::Better;
        let t0 = Instant::now();
        let mut batch = None;
        let s = "Sat Nov 21 09:55:01 2026";
        for _ in 0..FACTION_BATCH_MAX_HITS {
            assert!(
                push_faction_hit(&mut batch, "Hero", s.into(), hit("Coldain", Better), t0)
                    .is_none()
            );
        }
        let done =
            push_faction_hit(&mut batch, "Hero", s.into(), hit("Coldain", Better), t0).unwrap();
        assert_eq!(done.hits.len(), FACTION_BATCH_MAX_HITS);
        assert_eq!(batch.unwrap().hits.len(), 1);
    }

    #[test]
    fn zone_key_alias() {
        assert_eq!(zone_to_zonekey("Kael Drakkel").as_deref(), Some("kael"));
    }
}
