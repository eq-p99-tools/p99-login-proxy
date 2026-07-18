use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use proxy_core::{
    character_from_log_path, is_raid_target, zone_to_zonekey, LogEventKind, LogPatterns,
};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

use crate::events::AppEvent;
use crate::proxy_stats::ProxyStatsTracker;
use crate::watchers::WatcherHandle;
use crate::websocket::SsoClient;

const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(20);
const LOG_IDLE_SECS: u64 = 30;

pub struct EqLogWatcherHandle {
    cancel: CancellationToken,
}

impl EqLogWatcherHandle {
    pub fn start(
        logs_dir: PathBuf,
        sso: Option<SsoClient>,
        local_character_names: HashSet<String>,
        stats: Arc<ProxyStatsTracker>,
        event_tx: mpsc::Sender<AppEvent>,
        parent_cancel: CancellationToken,
    ) -> Self {
        let cancel = parent_cancel.child_token();
        let child = cancel.child_token();
        let (event_tx_files, event_rx) = mpsc::channel(64);
        let _watcher = WatcherHandle::start(vec![logs_dir.clone()], event_tx_files, child.clone());

        tokio::spawn(async move {
            run_watcher_loop(
                logs_dir,
                sso,
                local_character_names,
                stats,
                event_tx,
                event_rx,
                child,
            )
            .await;
        });

        Self { cancel }
    }

    pub fn stop(self) {
        self.cancel.cancel();
    }
}

async fn run_watcher_loop(
    logs_dir: PathBuf,
    sso: Option<SsoClient>,
    local_character_names: HashSet<String>,
    stats: Arc<ProxyStatsTracker>,
    event_tx: mpsc::Sender<AppEvent>,
    mut file_events: mpsc::Receiver<PathBuf>,
    cancel: CancellationToken,
) {
    let patterns = LogPatterns::default();
    let mut latest_log: Option<PathBuf> = None;
    let mut position: u64 = 0;
    let mut heartbeat = tokio::time::interval(HEARTBEAT_INTERVAL);

    if let Some(path) = find_latest_log(&logs_dir) {
        info!(path = %path.display(), "EQ log watcher tracking");
        position = seek_to_tail(&path);
        latest_log = Some(path);
    } else {
        warn!(dir = %logs_dir.display(), "no eqlog_*.txt files found");
    }

    loop {
        tokio::select! {
            _ = cancel.cancelled() => break,
            _ = heartbeat.tick() => {
                if let Some(ref path) = latest_log {
                    maybe_send_heartbeat(path, sso.as_ref(), stats.as_ref(), &event_tx).await;
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
                            }
                            latest_log = new_latest;
                        }
                        if latest_log.as_ref() == Some(&path) {
                            position = read_new_lines(
                                &path,
                                position,
                                &patterns,
                                sso.as_ref(),
                                &local_character_names,
                            )
                            .await;
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

async fn read_new_lines(
    path: &Path,
    position: u64,
    patterns: &LogPatterns,
    sso: Option<&SsoClient>,
    local_chars: &HashSet<String>,
) -> u64 {
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
        handle_line(line, &character, &char_lc, patterns, sso, local_chars).await;
    }
    position + buf.len() as u64
}

async fn handle_line(
    line: &str,
    character: &str,
    char_lc: &str,
    patterns: &LogPatterns,
    sso: Option<&SsoClient>,
    local_chars: &HashSet<String>,
) {
    let in_sso = sso.is_some_and(|client| {
        client
            .cache()
            .try_read()
            .ok()
            .is_some_and(|g| g.characters_cached.contains(char_lc))
    });
    let in_local = local_chars.contains(char_lc);
    if !in_sso && !in_local {
        return;
    }

    let event = patterns.classify(line);
    let Some(client) = sso.filter(|_| in_sso) else {
        return;
    };

    match event.kind {
        LogEventKind::ZoneEnter => {
            if let Some(zone) = event.zone.as_deref() {
                let zone_key = zone_to_zonekey(zone).unwrap_or_else(|| zone.to_lowercase());
                info!(%character, %zone_key, "zone enter");
                client
                    .send_update_location(character, Some(&zone_key), None, None, None)
                    .await;
            }
        }
        LogEventKind::LevelUp => {
            if let Some(level) = event.level {
                info!(%character, level, "level up");
                client
                    .send_update_location(character, None, None, Some(level), None)
                    .await;
            }
        }
        LogEventKind::Fte => {
            if let (Some(mob), Some(player), Some(time)) = (
                event.mob.as_deref(),
                event.player.as_deref(),
                event.eq_log_time.as_deref(),
            ) {
                info!(%character, mob, player, "FTE detected");
                client.send_fte(mob, player, character, time).await;
            }
        }
        LogEventKind::YouSlain | LogEventKind::MobKill => {
            if let (Some(mob), Some(time)) = (event.mob.as_deref(), event.eq_log_time.as_deref()) {
                if is_raid_target(mob) {
                    info!(%character, mob, "raid target slain");
                    client.send_mob_death(mob, time, character).await;
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
    fn zone_key_alias() {
        assert_eq!(zone_to_zonekey("Kael Drakkel").as_deref(), Some("kael"));
    }
}
