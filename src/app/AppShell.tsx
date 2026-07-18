import { useEffect, useRef, useState } from "react";

import { Button } from "../components";
import { AdvancedPanel } from "../features/advanced";
import { ChangelogPanel } from "../features/changelog";
import { ExtrasPanel } from "../features/extras";
import { LogsPanel } from "../features/logs";
import { ProxyPanel } from "../features/proxy";
import { SsoPanel } from "../features/sso";
import { useRuntimeStore } from "../features/runtime/store";
import { UpdatePrompt } from "../features/updater";
import { useDesktopClient } from "./AppProviders";
import { visibleNavTabs, type NavTab } from "./navigation";
import { SystemDialogs } from "./SystemDialogs";
import { applyAppTheme } from "./theme";

function ActivePanel({ tab }: { tab: NavTab }) {
  switch (tab) {
    case "proxy":
      return <ProxyPanel />;
    case "sso":
      return <SsoPanel />;
    case "advanced":
      return <AdvancedPanel />;
    case "logs":
      return <LogsPanel />;
    case "changelog":
      return <ChangelogPanel />;
    case "extras":
      return <ExtrasPanel />;
  }
}

export function AppShell() {
  const client = useDesktopClient();
  const version = useRuntimeStore((s) => s.runtime?.bootstrap.version);
  const [tab, setTab] = useState<NavTab>("proxy");
  const [quitting, setQuitting] = useState(false);
  const [launchBusy, setLaunchBusy] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [debugRegions, setDebugRegions] = useState(false);
  const advancedClickTimesRef = useRef<number[]>([]);

  const handleTabClick = (id: NavTab) => {
    setTab(id);
    if (id !== "advanced") {
      return;
    }
    // Easter egg (parity with Python): 7 clicks on Advanced within 3s toggles
    // region-color debug styling.
    const now = Date.now();
    const recent = [...advancedClickTimesRef.current, now].filter((t) => now - t <= 3000);
    advancedClickTimesRef.current = recent;
    if (recent.length >= 7) {
      advancedClickTimesRef.current = [];
      setDebugRegions((v) => {
        const next = !v;
        if (!next) {
          setTab((current) => (current === "extras" ? "proxy" : current));
        }
        return next;
      });
    }
  };

  const tabs = visibleNavTabs(debugRegions);

  useEffect(() => {
    void client.getAppConfig().then((cfg) => {
      applyAppTheme(cfg.theme_mode);
    });
  }, [client]);

  useEffect(() => {
    if (version) {
      document.title = `P99 Login Proxy v${version}`;
    }
  }, [version]);

  const handleQuit = async () => {
    setQuitting(true);
    try {
      await client.requestShutdown();
    } catch {
      setQuitting(false);
    }
  };

  const handleLaunch = async () => {
    setLaunchBusy(true);
    setLaunchError(null);
    try {
      await client.launchEverquest();
    } catch (e) {
      setLaunchError(e instanceof Error ? e.message : String(e));
    } finally {
      setLaunchBusy(false);
    }
  };

  return (
    <div className={`app-shell${debugRegions ? " debug-regions" : ""}`}>
      <nav className="nav-tabs" aria-label="Main navigation">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? "active" : ""}
            onClick={() => handleTabClick(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <main className="app-main">
        <ActivePanel tab={tab} />
      </main>
      <SystemDialogs />
      <UpdatePrompt />
      <footer className="app-footer">
        <div className="footer-actions">
          <Button variant="secondary" className="btn-plain" busy={launchBusy} onClick={() => void handleLaunch()}>
            Launch EverQuest
          </Button>
          <Button variant="secondary" className="btn-plain" busy={quitting} onClick={() => void handleQuit()}>
            {quitting ? "Exiting…" : "Exit"}
          </Button>
        </div>
        {launchError ? <span className="footer-error">{launchError}</span> : null}
      </footer>
    </div>
  );
}
