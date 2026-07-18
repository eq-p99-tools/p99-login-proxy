use std::collections::HashSet;
use std::path::{Path, PathBuf};

use proxy_core::{
    character_name_from_inventory_path, inventory_items_json, is_inventory_file,
    parse_inventory_file,
};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::info;

use crate::watchers::WatcherHandle;
use crate::websocket::SsoClient;

pub struct InventoryWatcherHandle {
    cancel: CancellationToken,
}

impl InventoryWatcherHandle {
    pub fn start(
        eq_roots: Vec<PathBuf>,
        sso: Option<SsoClient>,
        local_character_names: HashSet<String>,
        parent_cancel: CancellationToken,
    ) -> Self {
        let cancel = parent_cancel.child_token();
        let child = cancel.child_token();
        let (event_tx, event_rx) = mpsc::channel(64);
        let _watcher = WatcherHandle::start(eq_roots.clone(), event_tx, child.clone());

        tokio::spawn(async move {
            run_inventory_loop(eq_roots, sso, local_character_names, event_rx, child).await;
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
    local_chars: HashSet<String>,
    mut events: mpsc::Receiver<PathBuf>,
    cancel: CancellationToken,
) {
    loop {
        tokio::select! {
            _ = cancel.cancelled() => break,
            ev = events.recv() => {
                let Some(path) = ev else { break };
                handle_inventory_event(&path, &eq_roots, sso.as_ref(), &local_chars).await;
            }
        }
    }
}

async fn handle_inventory_event(
    path: &Path,
    eq_roots: &[PathBuf],
    sso: Option<&SsoClient>,
    local_chars: &HashSet<String>,
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
    let in_sso = sso.is_some_and(|client| {
        client
            .cache()
            .try_read()
            .ok()
            .is_some_and(|g| g.characters_cached.contains(&char_lc))
    });
    let in_local = local_chars.contains(&char_lc);
    if !in_sso && !in_local {
        return;
    }

    let flags = parse_inventory_file(path);
    let items = inventory_items_json(&flags);
    info!(%character, "inventory update");
    if let Some(client) = sso.filter(|_| in_sso) {
        client
            .send_update_location(&character, None, None, None, Some(items))
            .await;
    }
}

fn path_starts_under_roots(path: &Path, roots: &[PathBuf]) -> bool {
    roots.iter().any(|root| path.starts_with(root))
}
