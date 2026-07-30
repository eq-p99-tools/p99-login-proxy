use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

use proxy_core::{
    character_name_from_inventory_path, inventory_items_json, is_inventory_file,
    parse_inventory_file,
};
use serde_json::Value;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::info;

use crate::events::AppEvent;
use crate::watchers::WatcherHandle;
use crate::websocket::SsoClient;

pub struct InventoryWatcherHandle {
    cancel: CancellationToken,
}

impl InventoryWatcherHandle {
    pub fn start(
        eq_roots: Vec<PathBuf>,
        sso: Option<SsoClient>,
        local_character_names: Arc<RwLock<HashSet<String>>>,
        event_tx: mpsc::Sender<AppEvent>,
        parent_cancel: CancellationToken,
    ) -> Self {
        let cancel = parent_cancel.child_token();
        let child = cancel.child_token();
        let (file_event_tx, event_rx) = mpsc::channel(64);
        let _watcher = WatcherHandle::start(eq_roots.clone(), file_event_tx, child.clone());

        tokio::spawn(async move {
            run_inventory_loop(
                eq_roots,
                sso,
                local_character_names,
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

async fn run_inventory_loop(
    eq_roots: Vec<PathBuf>,
    sso: Option<SsoClient>,
    local_character_names: Arc<RwLock<HashSet<String>>>,
    event_tx: mpsc::Sender<AppEvent>,
    mut events: mpsc::Receiver<PathBuf>,
    cancel: CancellationToken,
) {
    loop {
        tokio::select! {
            _ = cancel.cancelled() => break,
            ev = events.recv() => {
                let Some(path) = ev else { break };
                handle_inventory_event(
                    &path,
                    &eq_roots,
                    sso.as_ref(),
                    &local_character_names,
                    &event_tx,
                )
                .await;
            }
        }
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

async fn handle_inventory_event(
    path: &Path,
    eq_roots: &[PathBuf],
    sso: Option<&SsoClient>,
    local_character_names: &Arc<RwLock<HashSet<String>>>,
    event_tx: &mpsc::Sender<AppEvent>,
) {
    if !is_inventory_file(path) {
        return;
    }
    if !path_starts_under_roots(path, eq_roots) {
        return;
    }
    let Some(character) = character_name_from_inventory_path(path) else {
        return;
    };
    let char_lc = character.to_lowercase();
    let (in_sso, in_local) = character_is_tracked(&char_lc, sso, local_character_names);
    if !in_sso && !in_local {
        return;
    }

    let flags = parse_inventory_file(path);
    let items = inventory_items_json(&flags);
    info!(%character, "inventory update");

    if in_sso {
        if let Some(client) = sso {
            client
                .send_update_location(&character, None, None, None, Some(items.clone()))
                .await;
        }
    }
    if in_local {
        let items_map: HashMap<String, Value> =
            items.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let _ = event_tx
            .send(AppEvent::LocalCharacterUpdate {
                name: character,
                park: None,
                bind: None,
                level: None,
                class: None,
                items: Some(items_map),
            })
            .await;
    }
}

fn path_starts_under_roots(path: &Path, roots: &[PathBuf]) -> bool {
    roots.iter().any(|root| path.starts_with(root))
}
