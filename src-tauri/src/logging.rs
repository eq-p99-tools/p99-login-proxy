//! Tracing setup: stderr, log file, and in-memory ring buffer for the UI.

use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use proxy_core::config::app_config_dir;
use runtime::log_store::{LogLine, LogStore};
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

pub struct LogPaths {
    pub file: Option<PathBuf>,
}

struct LogStoreLayer {
    store: LogStore,
    file: Option<Arc<Mutex<File>>>,
}

impl LogStoreLayer {
    fn new(store: LogStore, file: Option<Arc<Mutex<File>>>) -> Self {
        Self { store, file }
    }
}

impl<S> tracing_subscriber::Layer<S> for LogStoreLayer
where
    S: tracing::Subscriber,
{
    fn on_event(
        &self,
        event: &tracing::Event<'_>,
        _ctx: tracing_subscriber::layer::Context<'_, S>,
    ) {
        let metadata = event.metadata();
        let level = metadata.level().to_string();
        let target = metadata.target().to_string();
        let mut visitor = MessageVisitor::default();
        event.record(&mut visitor);
        let timestamp = human_timestamp();
        let line = format!("{timestamp} {level} {target}: {}", visitor.message);

        self.store.push(LogLine {
            timestamp,
            level,
            target,
            message: visitor.message,
        });

        if let Some(file) = &self.file {
            if let Ok(mut guard) = file.lock() {
                let _ = writeln!(guard, "{line}");
            }
        }
    }
}

#[derive(Default)]
struct MessageVisitor {
    message: String,
}

impl tracing::field::Visit for MessageVisitor {
    fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn std::fmt::Debug) {
        append_field(&mut self.message, field.name(), &format!("{value:?}"));
    }

    fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
        append_field(&mut self.message, field.name(), value);
    }
}

fn append_field(out: &mut String, name: &str, value: &str) {
    if !out.is_empty() {
        out.push(' ');
    }
    if name == "message" {
        out.push_str(value.trim_matches('"'));
    } else {
        out.push_str(name);
        out.push('=');
        out.push_str(value.trim_matches('"'));
    }
}

fn human_timestamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{secs}")
}

fn default_filter() -> EnvFilter {
    EnvFilter::try_from_default_env().unwrap_or_else(|_| {
        EnvFilter::new("info,runtime=debug,p99_login_proxy_native_lib=debug,proxy_core=debug")
    })
}

pub fn init(log_store: LogStore) -> LogPaths {
    let file_path = app_config_dir().map(|dir| dir.join("proxy.log"));
    let file_handle = file_path.as_ref().and_then(|path| {
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .ok()
            .map(|file| Arc::new(Mutex::new(file)))
    });

    let stderr_layer = tracing_subscriber::fmt::layer()
        .with_writer(io::stderr)
        .with_span_events(FmtSpan::CLOSE);

    let memory_layer = LogStoreLayer::new(log_store, file_handle.clone());

    tracing_subscriber::registry()
        .with(default_filter())
        .with(stderr_layer)
        .with(memory_layer)
        .init();

    if let Some(ref path) = file_path {
        if file_handle.is_some() {
            tracing::info!(path = %path.display(), "logging to file");
        } else {
            tracing::warn!(path = %path.display(), "could not open log file; using stderr only");
        }
    }

    LogPaths {
        file: if file_handle.is_some() {
            file_path
        } else {
            None
        },
    }
}
