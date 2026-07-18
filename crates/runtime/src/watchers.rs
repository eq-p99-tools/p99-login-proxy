use std::path::PathBuf;
use std::time::Duration;

use notify_debouncer_mini::{new_debouncer, DebounceEventResult};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::warn;

pub struct WatcherHandle {
    cancel: CancellationToken,
}

impl WatcherHandle {
    pub fn start(
        paths: Vec<PathBuf>,
        event_tx: mpsc::Sender<PathBuf>,
        cancel: CancellationToken,
    ) -> Self {
        let child = cancel.child_token();
        tokio::spawn(async move {
            let (debounce_tx, mut debounce_rx) = mpsc::channel::<DebounceEventResult>(32);
            let mut debouncer = match new_debouncer(Duration::from_millis(250), move |res| {
                let _ = debounce_tx.blocking_send(res);
            }) {
                Ok(d) => d,
                Err(e) => {
                    warn!("watcher debouncer init failed: {e}");
                    return;
                }
            };
            for path in &paths {
                if let Err(e) = debouncer
                    .watcher()
                    .watch(path, notify::RecursiveMode::NonRecursive)
                {
                    warn!("watch {path:?} failed: {e}");
                }
            }
            loop {
                tokio::select! {
                    _ = child.cancelled() => break,
                    msg = debounce_rx.recv() => {
                        if let Some(Ok(events)) = msg {
                            for ev in events {
                                let _ = event_tx.send(ev.path).await;
                            }
                        }
                    }
                }
            }
        });
        Self { cancel }
    }

    pub fn stop(self) {
        self.cancel.cancel();
    }
}
