import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

import {
  ErrorAlert,
  FormLayout,
  FormRow,
  FormValue,
  GroupBox,
  PasswordField,
} from "../../components";
import { tooltipProps } from "../../components/tooltip";
import { useDesktopClient } from "../../app/AppProviders";
import { applyAppTheme } from "../../app/theme";
import type { DesktopClient } from "../../ipc/Client";
import type { AppConfig, ProxyMode, SsoBackendOption } from "../../ipc/schemas";
import type { AccountTree } from "../sso/roster";
import {
  localAccountsSummary,
  normalizeAccountTree,
  ssoAccountsSummary,
  ssoLoggedInSummary,
} from "../sso/roster";
import { selectLifecycle, useRuntimeStore } from "../runtime/store";
import { ProxyStatusBadge, EqConfigBadge } from "./ProxyStatusBadge";
import { HeartbeatIcon } from "./HeartbeatIcon";
import { lastLoginDisplay } from "./lastLoginDisplay";

const PROXY_MODES: { value: ProxyMode; label: string }[] = [
  { value: "enabled_sso", label: "Enabled (SSO)" },
  { value: "enabled_proxy_only", label: "Enabled (Proxy Only)" },
  { value: "disabled", label: "Disabled" },
];

const PROXY_MODE_TOOLTIP =
  "Enabled (SSO): Full proxy with SSO authentication\n" +
  "Enabled (Proxy Only): Proxy active but no SSO interaction ('middlemand' mode)\n" +
  "Disabled: Proxy inactive, direct connection to server";

function wsStateLabel(state: string, detail?: string | null): string {
  switch (state) {
    case "connected":
      return "Connected (Live)";
    case "connecting":
      return "Connecting";
    case "auth_failed": {
      const text = detail || "Authentication Failed";
      return text.length <= 60 ? text : `${text.slice(0, 57)}...`;
    }
    case "parked":
      return "Parked";
    default:
      return "Disconnected";
  }
}

function ssoServiceStatus(
  status: Awaited<ReturnType<DesktopClient["getSsoStatus"]>> | null,
  wsState: string | undefined,
  wsError: string | null | undefined,
  hasToken: boolean,
): string {
  if (status == null && wsState == null) {
    return "Checking…";
  }
  if (!hasToken) {
    return "No API Token";
  }
  return wsStateLabel(wsState ?? status?.ws_state ?? "disconnected", wsError ?? status?.ws_error);
}

function ssoServiceTone(
  status: Awaited<ReturnType<DesktopClient["getSsoStatus"]>> | null,
  wsState: string | undefined,
  hasToken: boolean,
): "default" | "success" | "warning" | "error" | "muted" {
  if (!hasToken) {
    return "muted";
  }
  switch (wsState ?? status?.ws_state) {
    case "connected":
      return "success";
    case "connecting":
      return "warning";
    case "auth_failed":
      return "error";
    default:
      return "muted";
  }
}

export function ProxyPanel() {
  const client = useDesktopClient();
  const runtime = useRuntimeStore((s) => s.runtime);
  const stats = runtime?.stats;
  const bootstrap = runtime?.bootstrap;
  const lifecycle = useRuntimeStore(selectLifecycle);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [ssoStatus, setSsoStatus] = useState<Awaited<ReturnType<typeof client.getSsoStatus>> | null>(null);
  const [backends, setBackends] = useState<SsoBackendOption[]>([]);
  const [localSummary, setLocalSummary] = useState<{ text: string; tone: "success" | "muted" }>({
    text: "None",
    tone: "muted",
  });
  const [accountTree, setAccountTree] = useState<AccountTree>({});
  const [activityTick, setActivityTick] = useState(0);
  const [modeBusy, setModeBusy] = useState(false);
  const [tokenBusy, setTokenBusy] = useState(false);
  const [alwaysOnTop, setAlwaysOnTop] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [portEditing, setPortEditing] = useState(false);
  const [portDraft, setPortDraft] = useState("");
  const [portBusy, setPortBusy] = useState(false);
  const tokenDirtyRef = useRef(false);
  const tokenSaveTimerRef = useRef<number | null>(null);
  const portInputRef = useRef<HTMLInputElement | null>(null);
  const skipPortBlurSaveRef = useRef(false);

  const currentMode = stats?.proxy_mode ?? "disabled";
  const [selectedMode, setSelectedMode] = useState<ProxyMode>(currentMode);
  const previousModeRef = useRef<ProxyMode>(currentMode);
  const previousWsStateRef = useRef<string | null>(null);
  const wsState = bootstrap?.ws_state;
  const wsError = bootstrap?.ws_error;
  const hasToken = ssoStatus?.has_token ?? bootstrap?.has_token ?? false;
  const loggedInSummary = useMemo(
    () => ssoLoggedInSummary(accountTree),
    [accountTree, activityTick],
  );
  const ssoSummary = useMemo(() => ssoAccountsSummary(accountTree), [accountTree]);

  useEffect(() => {
    setSelectedMode(currentMode);
    previousModeRef.current = currentMode;
  }, [currentMode]);

  const applySsoStatus = useCallback((status: Awaited<ReturnType<typeof client.getSsoStatus>>) => {
    setSsoStatus(status);
    if (!tokenDirtyRef.current) {
      setToken(status.api_token);
    }
  }, []);

  const refreshMeta = useCallback(async () => {
    try {
      const [s, b, cfg, local, accounts] = await Promise.all([
        client.getSsoStatus(),
        client.getSsoBackends(),
        client.getAppConfig(),
        client.getLocalData(),
        client.getSsoAccounts(),
      ]);
      applySsoStatus(s);
      setBackends(b);
      setConfig(cfg);
      setAlwaysOnTop(cfg.always_on_top);
      setLocalSummary(localAccountsSummary(local.accounts, local.characters.length));
      const tree = normalizeAccountTree(accounts.account_tree);
      setAccountTree(tree);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client, applySsoStatus]);

  useEffect(() => {
    void refreshMeta();
    const id = window.setInterval(() => void refreshMeta(), 8000);
    return () => window.clearInterval(id);
  }, [refreshMeta]);

  useEffect(() => {
    const id = window.setInterval(() => setActivityTick((t) => t + 1), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const previous = previousWsStateRef.current;
    previousWsStateRef.current = wsState ?? null;
    if (wsState === "connected" && previous !== "connected") {
      void refreshMeta();
    }
  }, [wsState, refreshMeta]);

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) {
      return;
    }
    void getCurrentWindow()
      .setAlwaysOnTop(alwaysOnTop)
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
      });
  }, [alwaysOnTop]);

  useEffect(() => {
    if (!ssoStatus || token === ssoStatus.api_token) {
      return;
    }
    if (tokenSaveTimerRef.current != null) {
      window.clearTimeout(tokenSaveTimerRef.current);
    }
    tokenSaveTimerRef.current = window.setTimeout(() => {
      setTokenBusy(true);
      void client
        .setSsoToken(token)
        .then((next) => {
          tokenDirtyRef.current = false;
          applySsoStatus(next);
          setError(null);
        })
        .catch((e) => {
          setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => setTokenBusy(false));
    }, 1500);
    return () => {
      if (tokenSaveTimerRef.current != null) {
        window.clearTimeout(tokenSaveTimerRef.current);
      }
    };
  }, [token, ssoStatus, client, applySsoStatus]);

  const changeMode = async (mode: ProxyMode) => {
    const previous = previousModeRef.current;
    setSelectedMode(mode);
    setModeBusy(true);
    setError(null);
    try {
      const next = await client.setProxyModeSelection(mode);
      useRuntimeStore.getState().setRuntime(next);
      previousModeRef.current = mode;
      await refreshMeta();
    } catch (e) {
      try {
        const runtimeAfterFailure = await client.getRuntimeState();
        useRuntimeStore.getState().setRuntime(runtimeAfterFailure);
        const configuredMode = runtimeAfterFailure.stats.proxy_mode;
        setSelectedMode(configuredMode);
        previousModeRef.current = configuredMode;
      } catch {
        setSelectedMode(previous);
      }
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setModeBusy(false);
    }
  };

  const changeBackend = async (backend: string) => {
    if (!backend) return;
    setTokenBusy(true);
    tokenDirtyRef.current = false;
    try {
      const backendOpt = backends.find((b) => b.name === backend);
      applySsoStatus(await client.setSsoBackend(backend, backendOpt?.api_url));
      await refreshMeta();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTokenBusy(false);
    }
  };

  const forceReconnect = async () => {
    setTokenBusy(true);
    try {
      await client.reloadLocalData();
      await client.reconnectSso();
      await refreshMeta();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTokenBusy(false);
    }
  };

  const changeTheme = async (themeMode: AppConfig["theme_mode"]) => {
    if (!config) return;
    const systemDark =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = {
      ...config,
      theme_mode: themeMode,
      dark_mode: themeMode === "dark" || (themeMode === "system" && systemDark),
    };
    setConfig(next);
    applyAppTheme(themeMode);
    try {
      await client.saveAppConfig(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const toggleAlwaysOnTop = async (checked: boolean) => {
    setAlwaysOnTop(checked);
    if (!config) return;
    const next = { ...config, always_on_top: checked };
    setConfig(next);
    try {
      await client.saveAppConfig(next);
    } catch (e) {
      setAlwaysOnTop(!checked);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const listenHost = stats?.listen_address ?? bootstrap?.listen_address;
  const listenPort = stats?.listen_port ?? bootstrap?.listen_port;
  const listen =
    listenHost != null && listenPort != null ? `${listenHost}:${listenPort}` : "—";
  const lastLogin = lastLoginDisplay(
    stats?.last_username,
    stats?.last_account,
    stats?.last_login_method,
  );

  const startPortEdit = () => {
    if (listenPort == null || portBusy) {
      return;
    }
    setPortDraft(String(listenPort));
    setPortEditing(true);
  };

  useEffect(() => {
    if (portEditing) {
      portInputRef.current?.focus();
      portInputRef.current?.select();
    }
  }, [portEditing]);

  const cancelPortEdit = () => {
    setPortEditing(false);
    setPortDraft("");
  };

  const cancelPortEditFromEscape = () => {
    skipPortBlurSaveRef.current = true;
    cancelPortEdit();
  };

  const saveListenPort = async () => {
    if (listenPort == null) {
      return;
    }
    const nextPort = Number.parseInt(portDraft, 10);
    if (!Number.isFinite(nextPort) || nextPort < 1 || nextPort > 65535) {
      setError("Listen port must be between 1 and 65535.");
      return;
    }
    if (nextPort === listenPort) {
      cancelPortEdit();
      return;
    }

    setPortBusy(true);
    setError(null);
    try {
      const runtimeState = await client.updateListenPort(nextPort);
      useRuntimeStore.getState().setRuntime(runtimeState);
      cancelPortEdit();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPortBusy(false);
    }
  };

  return (
    <section className="panel proxy-panel">
      <div className="proxy-top-row">
        <GroupBox title="Status" className="proxy-group-stretch">
          <FormLayout spacing="status">
            <FormRow label="Proxy:">
              <ProxyStatusBadge lifecycle={lifecycle} />
            </FormRow>
            <FormRow label="EQ Config:">
              <EqConfigBadge
                enabled={stats?.eq_config_enabled ?? false}
                eqhostProxyEnabled={stats?.eqhost_proxy_enabled ?? false}
                eqclientLogEnabled={stats?.eqclient_log_enabled ?? false}
              />
            </FormRow>
            <FormRow label="Listening on:">
              <FormValue title="Double-click to change the listen port">
                {portEditing && listenHost != null ? (
                  <span className="listen-port-editor">
                    <code>{listenHost}:</code>
                    <input
                      ref={portInputRef}
                      type="number"
                      className="listen-port-input"
                      min={1}
                      max={65535}
                      aria-label="Listen port"
                      value={portDraft}
                      disabled={portBusy}
                      onChange={(e) => setPortDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void saveListenPort();
                        } else if (e.key === "Escape") {
                          e.preventDefault();
                          cancelPortEditFromEscape();
                        }
                      }}
                      onBlur={() => {
                        if (skipPortBlurSaveRef.current) {
                          skipPortBlurSaveRef.current = false;
                          return;
                        }
                        void saveListenPort();
                      }}
                    />
                  </span>
                ) : (
                  <code
                    className="listen-endpoint-editable"
                    onDoubleClick={() => startPortEdit()}
                  >
                    {listen}
                  </code>
                )}
              </FormValue>
            </FormRow>
            <FormRow label="Last Login:">
              <span className="last-login-field">
                <FormValue title={lastLogin.tooltip}>{lastLogin.text}</FormValue>
                <HeartbeatIcon
                  lastHeartbeatAtMs={stats?.last_heartbeat_at_ms}
                  character={stats?.heartbeat_character}
                  wsState={wsState}
                />
              </span>
            </FormRow>
          </FormLayout>
        </GroupBox>
        <GroupBox title="Statistics" className="proxy-group-stretch">
          <FormLayout spacing="stats">
            <FormRow label="Uptime:">
              <FormValue>{stats?.uptime_display ?? "—"}</FormValue>
            </FormRow>
            <FormRow label="Total Connections:">
              <FormValue>{stats?.total_connections ?? 0}</FormValue>
            </FormRow>
            <FormRow label="Active Connections:">
              <FormValue>{stats?.active_connections ?? 0}</FormValue>
            </FormRow>
            <FormRow label="Completed Connections:">
              <FormValue>{stats?.completed_connections ?? 0}</FormValue>
            </FormRow>
          </FormLayout>
        </GroupBox>
      </div>

      <GroupBox title="Settings" className="proxy-group-stretch">
        <FormLayout spacing="settings">
          <FormRow label="Proxy Mode:" bold>
            <div className="proxy-mode-row">
              <select
                aria-label="Proxy Mode"
                className="field-select"
                {...tooltipProps(PROXY_MODE_TOOLTIP)}
                value={selectedMode}
                disabled={modeBusy}
                onChange={(e) => void changeMode(e.target.value as ProxyMode)}
              >
                {PROXY_MODES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <span className="mode-spacer" />
              <select
                aria-label="Theme"
                value={config?.theme_mode ?? "system"}
                onChange={(e) => void changeTheme(e.target.value as AppConfig["theme_mode"])}
                {...tooltipProps("Choose dark, light, or the Windows system theme")}
              >
                <option value="system">System Default</option>
                <option value="dark">Dark Mode</option>
                <option value="light">Light Mode</option>
              </select>
              <label
                className="checkbox-inline"
                {...tooltipProps("Keep the application window on top of other windows")}
              >
                <input
                  type="checkbox"
                  checked={alwaysOnTop}
                  onChange={(e) => void toggleAlwaysOnTop(e.target.checked)}
                />
                Always On Top
              </label>
            </div>
          </FormRow>
          <FormRow label="SSO API:" bold>
            <select
              aria-label="SSO API"
              className="field-select"
              {...tooltipProps("Select the SSO API server endpoint")}
              value={ssoStatus?.backend ?? ""}
              disabled={tokenBusy}
              onChange={(e) => void changeBackend(e.target.value)}
            >
              <option value="">Select SSO Server…</option>
              {backends.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name}
                </option>
              ))}
            </select>
          </FormRow>
          <FormRow label="API Token:" bold>
            <div>
              <PasswordField
                label=""
                aria-label="API Token"
                placeholder="Access key"
                visibilityMode="hold"
                holdTip="Hold to show API token"
                tooltip="API Token for auto-authentication. When this is set, the password entered in the EQ UI will be ignored."
                value={token}
                disabled={tokenBusy}
                onChange={(e) => {
                  tokenDirtyRef.current = true;
                  setToken(e.target.value);
                }}
              />
              {tokenBusy ? <span className="token-saving muted">Saving…</span> : null}
            </div>
          </FormRow>
        </FormLayout>
      </GroupBox>

      <GroupBox title="Account Data" className="proxy-group-stretch proxy-group-grow">
        <div className="cache-controls">
          <FormLayout spacing="cache" className="cache-info">
            <FormRow label="SSO Service:">
              <FormValue
                tone={ssoServiceTone(ssoStatus, wsState, hasToken)}
                title={
                  ((wsState ?? ssoStatus?.ws_state) === "auth_failed" &&
                    (wsError ?? ssoStatus?.ws_error)) ||
                  "WebSocket connection status for real-time account updates"
                }
              >
                {ssoServiceStatus(ssoStatus, wsState, wsError, hasToken)}
              </FormValue>
            </FormRow>
            <FormRow label="SSO Accounts:">
              <FormValue
                tone={ssoSummary.tone}
                title="Number of accounts, characters, and aliases/tags from the SSO server"
              >
                {ssoSummary.text}
              </FormValue>
            </FormRow>
            <FormRow label="SSO Logged In:">
              <FormValue tone={loggedInSummary.tone} title={loggedInSummary.title}>
                {loggedInSummary.text}
              </FormValue>
            </FormRow>
            <FormRow label="Local Accounts:">
              <FormValue
                tone={localSummary.tone}
                title="Accounts, characters, and aliases from local_accounts.csv and local_characters.csv (SSO tab → Local Accounts / Local Characters)"
              >
                {localSummary.text}
              </FormValue>
            </FormRow>
          </FormLayout>
          <button
            type="button"
            className="btn btn-secondary"
            {...tooltipProps("Disconnect and reconnect to the SSO server for fresh data")}
            disabled={tokenBusy}
            onClick={() => void forceReconnect()}
          >
            Force Reconnect
          </button>
        </div>
      </GroupBox>

      {error ? <ErrorAlert message={error} /> : null}
    </section>
  );
}
