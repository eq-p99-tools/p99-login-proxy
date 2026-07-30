import { useCallback, useEffect, useState } from "react";

import { Button, ErrorAlert, GroupBox, StatusValue } from "../../components";
import { useDesktopClient } from "../../app/AppProviders";
import { useUpdaterStore } from "../updater";
import { useRuntimeStore, selectLifecycle } from "../runtime/store";
import type { ProxySettings } from "../../ipc/schemas";

export function ExtrasPanel() {
  const client = useDesktopClient();
  const syncError = useRuntimeStore((s) => s.syncError);
  const proxyLifecycle = useRuntimeStore(selectLifecycle);
  const proxyRunning = proxyLifecycle !== "stopped";
  const [settings, setSettings] = useState<ProxySettings | null>(null);
  const [secondary, setSecondary] = useState("");
  const [prerelease, setPrerelease] = useState(false);
  const [autoAddLocalCharacters, setAutoAddLocalCharacters] = useState(false);
  const [busy, setBusy] = useState(false);
  const [updateStatus, setUpdateStatus] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [proxySettings, cfg] = await Promise.all([
        client.getProxySettings(),
        client.getAppConfig(),
      ]);
      setSettings(proxySettings);
      setSecondary(cfg.eq_directory_secondary ?? "");
      setPrerelease(cfg.prerelease_updates);
      setAutoAddLocalCharacters(cfg.auto_add_local_characters ?? false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const saveSkipSso = async () => {
    if (!settings) return;
    setBusy(true);
    try {
      await client.updateProxySettings(settings);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveSecondary = async () => {
    setBusy(true);
    try {
      const cfg = await client.getAppConfig();
      await client.saveAppConfig({ ...cfg, eq_directory_secondary: secondary || null });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const savePrerelease = async (checked: boolean) => {
    setPrerelease(checked);
    setBusy(true);
    try {
      const cfg = await client.getAppConfig();
      await client.saveAppConfig({ ...cfg, prerelease_updates: checked });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveAutoAddLocalCharacters = async (checked: boolean) => {
    setAutoAddLocalCharacters(checked);
    setBusy(true);
    try {
      const cfg = await client.getAppConfig();
      await client.saveAppConfig({ ...cfg, auto_add_local_characters: checked });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const checkUpdates = async () => {
    setBusy(true);
    try {
      const result = await client.checkForUpdates();
      setUpdateStatus(result.message);
      setError(null);
      if (result.available) {
        useUpdaterStore.getState().promptUpdate(result.version ?? null, result.message);
      } else {
        useUpdaterStore.getState().showUpdateInfo(result.title, result.message);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel extras-panel">
      <GroupBox title="Native-only controls">
        <p className="panel-intro">
          Settings that have no Python UI equivalent. Secondary EQ path, skip-SSO list, and
          prerelease update preference live here instead of Advanced.
        </p>
        {syncError ? <p className="error-banner tone-error">{syncError}</p> : null}
      </GroupBox>

      <GroupBox title="Proxy extras">
        <label className="form-field">
          <span>Skip SSO accounts</span>
          <input
            type="text"
            value={settings?.skip_sso_accounts ?? ""}
            disabled={busy || !settings || proxyRunning}
            onChange={(e) =>
              setSettings((s) => (s ? { ...s, skip_sso_accounts: e.target.value } : s))
            }
          />
        </label>
        {proxyRunning ? (
          <p className="field-hint">Stop the proxy before changing skip-SSO accounts.</p>
        ) : null}
        <Button busy={busy} disabled={!settings || proxyRunning} onClick={() => void saveSkipSso()}>
          Save skip SSO accounts
        </Button>
      </GroupBox>

      <GroupBox title="EverQuest extras">
        <label className="form-field">
          <span>Secondary EQ directory (logs/inventory)</span>
          <input
            type="text"
            value={secondary}
            disabled={busy}
            onChange={(e) => setSecondary(e.target.value)}
          />
        </label>
        <Button busy={busy} onClick={() => void saveSecondary()}>
          Save secondary path
        </Button>
        <label className="checkbox-inline">
          <input
            type="checkbox"
            checked={autoAddLocalCharacters}
            disabled={busy}
            onChange={(e) => void saveAutoAddLocalCharacters(e.target.checked)}
          />
          Auto-add local characters after local login
        </label>
        <p className="field-hint">
          When enabled, the first EQ log file seen after a local-account login creates a row in
          Local Characters. Off by default in the native app.
        </p>
      </GroupBox>

      <GroupBox title="Updates">
        <label className="checkbox-inline">
          <input
            type="checkbox"
            checked={prerelease}
            disabled={busy}
            onChange={(e) => void savePrerelease(e.target.checked)}
          />
          Opt into prerelease updates
        </label>
        <div className="button-row">
          <Button busy={busy} onClick={() => void checkUpdates()}>
            Check for updates
          </Button>
        </div>
        {updateStatus ? <StatusValue label="Status" value={updateStatus} /> : null}
      </GroupBox>

      {error ? <ErrorAlert message={error} /> : null}
    </section>
  );
}
