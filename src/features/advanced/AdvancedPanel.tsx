import { useCallback, useEffect, useState } from "react";

import { Button, ConfirmDialog, ErrorAlert, GroupBox } from "../../components";
import { CheckIcon, PencilIcon } from "../../components/EqhostEditIcons";
import { useDesktopClient } from "../../app/AppProviders";
import type { AppConfig, EqSettingsView } from "../../ipc/schemas";

export function AdvancedPanel() {
  const client = useDesktopClient();
  const [settings, setSettings] = useState<EqSettingsView | null>(null);
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  const [launchOnStart, setLaunchOnStart] = useState(false);
  const [launchAdmin, setLaunchAdmin] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmRestore, setConfirmRestore] = useState(false);
  const [confirmResetBackup, setConfirmResetBackup] = useState(false);
  const [eqhostEditing, setEqhostEditing] = useState(false);
  const [eqhostDraft, setEqhostDraft] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [eq, cfg] = await Promise.all([client.getEqSettings(), client.getAppConfig()]);
      setSettings(eq);
      setAppConfig(cfg);
      setLaunchOnStart(cfg.launch_startup);
      setLaunchAdmin(cfg.launch_admin);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const persistConfig = async (next: AppConfig) => {
    setAppConfig(next);
    try {
      await client.saveAppConfig(next);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    }
  };

  const toggleLaunchOnStart = async (checked: boolean) => {
    if (!appConfig) return;
    const previous = launchOnStart;
    setLaunchOnStart(checked);
    try {
      await persistConfig({ ...appConfig, launch_startup: checked });
    } catch {
      setLaunchOnStart(previous);
    }
  };

  const toggleLaunchAdmin = async (checked: boolean) => {
    if (!appConfig) return;
    const previous = launchAdmin;
    setLaunchAdmin(checked);
    try {
      await persistConfig({ ...appConfig, launch_admin: checked });
    } catch {
      setLaunchAdmin(previous);
    }
  };

  const browsePrimary = async () => {
    setBusy(true);
    try {
      const path = await client.browseEqExecutable();
      if (path) {
        await client.setEqDirectory(path);
        await refresh();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const restoreBackup = async () => {
    setBusy(true);
    try {
      await client.restoreEqhostBackup();
      setConfirmRestore(false);
      setEqhostEditing(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const resetBackup = async () => {
    setBusy(true);
    try {
      await client.resetEqhostBackup();
      setConfirmResetBackup(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const startEqhostEdit = () => {
    setEqhostDraft(settings?.eqhost_contents ?? "");
    setEqhostEditing(true);
  };

  const saveEqhostEdit = async () => {
    setBusy(true);
    try {
      const updated = await client.saveEqhostContents(eqhostDraft);
      setSettings(updated);
      setEqhostEditing(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const eqDirTone =
    settings == null ? "muted" : settings.eq_directory_valid ? "success" : "error";
  const eqDirDisplay =
    settings == null
      ? "Checking…"
      : settings.eq_directory_valid && settings.eq_directory
        ? settings.eq_directory
        : "Not Found";

  const eqhostFound = settings?.eqhost_contents != null;
  const eqhostTone = settings == null ? "muted" : eqhostFound ? "success" : "error";
  const eqhostDisplay =
    settings == null ? "Checking…" : eqhostFound && settings.eqhost_path ? settings.eqhost_path : "Not Found";
  const eqhostCanEdit = Boolean(settings?.eq_directory_valid);
  const eqhostDisplayValue = settings?.eqhost_contents ?? "(no file)";

  return (
    <section className="panel advanced-panel">
      <GroupBox title="EverQuest Configuration">
        <div className="advanced-path-row">
          <span className="path-label">EverQuest Path:</span>
          <span className={`path-value tone-${eqDirTone}`}>{eqDirDisplay}</span>
          <Button
            variant="secondary"
            busy={busy}
            title="Browse to eqgame.exe; the install folder is taken from that file's location"
            onClick={() => void browsePrimary()}
          >
            Browse…
          </Button>
        </div>

        <div className="advanced-path-row">
          <span className="path-label">eqhost.txt Path:</span>
          <span className={`path-value tone-${eqhostTone}`}>{eqhostDisplay}</span>
          <label
            className="checkbox-inline"
            title="Launch EverQuest automatically when the proxy starts"
          >
            <input
              type="checkbox"
              checked={launchOnStart}
              onChange={(e) => void toggleLaunchOnStart(e.target.checked)}
            />
            Launch EQ on Start
          </label>
          <label
            className="checkbox-inline"
            title="Uncheck if EverQuest is on a RAMDisk or mapped drive that isn't visible to elevated processes"
          >
            <input
              type="checkbox"
              checked={launchAdmin}
              onChange={(e) => void toggleLaunchAdmin(e.target.checked)}
            />
            as Admin
          </label>
        </div>

        <div className="eqhost-text-panels">
          <div className="eqhost-panel">
            <div className="eqhost-panel-header">
              <p className="eqhost-panel-label">eqhost.txt (current):</p>
              {eqhostCanEdit ? (
                <button
                  type="button"
                  className="eqhost-edit-toggle"
                  title={eqhostEditing ? "Save eqhost.txt" : "Edit eqhost.txt"}
                  aria-label={eqhostEditing ? "Save eqhost.txt" : "Edit eqhost.txt"}
                  disabled={busy}
                  onClick={() => void (eqhostEditing ? saveEqhostEdit() : startEqhostEdit())}
                >
                  {eqhostEditing ? <CheckIcon /> : <PencilIcon />}
                </button>
              ) : null}
            </div>
            <textarea
              className={`eqhost-textarea${eqhostEditing ? " eqhost-textarea-editing" : ""}`}
              readOnly={!eqhostEditing}
              value={eqhostEditing ? eqhostDraft : eqhostDisplayValue}
              onChange={(e) => setEqhostDraft(e.target.value)}
            />
          </div>
          <div className="eqhost-panel">
            <p className="eqhost-panel-label">eqhost.txt.bak (backup):</p>
            <textarea
              className="eqhost-textarea"
              readOnly
              value={
                settings?.eqhost_backup_exists
                  ? (settings.eqhost_backup_contents ?? "")
                  : "(no backup file)"
              }
            />
          </div>
        </div>

        <div className="button-row">
          <Button
            variant="secondary"
            title="Restore eqhost.txt from eqhost.txt.bak and disable the proxy."
            disabled={!settings?.eqhost_backup_exists || busy}
            onClick={() => setConfirmRestore(true)}
          >
            Restore Backup
          </Button>
          <Button
            variant="secondary"
            title="Overwrite eqhost.txt.bak with the default P99 login server (login.eqemulator.net:5998)."
            disabled={!eqhostCanEdit || busy}
            onClick={() => setConfirmResetBackup(true)}
          >
            Reset Backup
          </Button>
          <Button
            variant="secondary"
            busy={busy}
            title="Open the EverQuest install directory."
            onClick={() => void client.openEqFolder()}
          >
            Open Folder
          </Button>
        </div>
      </GroupBox>

      {error ? <ErrorAlert message={error} /> : null}

      <ConfirmDialog
        open={confirmRestore}
        title="Restore eqhost backup"
        message="This will disable the proxy and restore eqhost.txt from the backup file. Continue?"
        confirmLabel="Restore"
        busy={busy}
        onConfirm={() => void restoreBackup()}
        onCancel={() => setConfirmRestore(false)}
      />

      <ConfirmDialog
        open={confirmResetBackup}
        title="Reset eqhost backup"
        message="This will overwrite eqhost.txt.bak with the default P99 login server. Continue?"
        confirmLabel="Reset Backup"
        busy={busy}
        onConfirm={() => void resetBackup()}
        onCancel={() => setConfirmResetBackup(false)}
      />
    </section>
  );
}
