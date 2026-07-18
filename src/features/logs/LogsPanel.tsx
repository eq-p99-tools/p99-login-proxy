import { useEffect, useRef, useState } from "react";

import { Button } from "../../components";
import { useDesktopClient } from "../../app/AppProviders";
import { useRecentLogs } from "./useRecentLogs";

const LOG_LEVELS = ["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"] as const;

export function LogsPanel() {
  const client = useDesktopClient();
  const [autoScroll, setAutoScroll] = useState(true);
  const [wordWrap, setWordWrap] = useState(false);
  const [level, setLevel] = useState<(typeof LOG_LEVELS)[number]>("INFO");
  const [clearBusy, setClearBusy] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const { snapshot, error, refresh } = useRecentLogs(client, level);
  const lines = snapshot?.lines ?? [];

  useEffect(() => {
    if (!autoScroll || !logRef.current) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines.length, autoScroll]);

  const clearLogs = async () => {
    setClearBusy(true);
    try {
      await client.clearLogs();
      await refresh();
    } finally {
      setClearBusy(false);
    }
  };

  return (
    <section className="panel logs-panel">
      <div className="log-toolbar">
        <div className="log-toolbar-controls">
          <label className="checkbox-inline">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
            />
            Auto-scroll
          </label>
          <label className="checkbox-inline">
            <input
              type="checkbox"
              checked={wordWrap}
              onChange={(e) => setWordWrap(e.target.checked)}
            />
            Word wrap
          </label>
          <label className="checkbox-inline">
            Level:
            <select className="field-select field-select-inline" value={level} onChange={(e) => setLevel(e.target.value as typeof level)}>
              {LOG_LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <Button variant="secondary" busy={clearBusy} onClick={() => void clearLogs()}>
            Clear
          </Button>
        </div>
        {snapshot?.file_path ? (
          <span className="log-path muted" title={snapshot.file_path}>
            Log file: {snapshot.file_path}
          </span>
        ) : null}
      </div>

      {error != null ? (
        <p className="error-banner" role="alert">
          {error}
        </p>
      ) : null}

      <div className="log-view" role="log" aria-live="polite" ref={logRef}>
        {lines.length === 0 ? (
          <p className="muted">No log lines yet. Enable the proxy and try an EQ login.</p>
        ) : (
          <ul className={`log-list${wordWrap ? "" : " nowrap"}`}>
            {lines.map((line, index) => (
              <li
                key={`${line.timestamp}-${index}`}
                className={`log-line log-${line.level.toLowerCase()}`}
              >
                <span className="log-ts">{line.timestamp}</span>
                <span className="log-level">{line.level}</span>
                <span className="log-message">{line.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
