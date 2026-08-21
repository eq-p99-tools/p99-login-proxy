import { invoke } from "@tauri-apps/api/core";
import { disable, enable, isEnabled } from "@tauri-apps/plugin-autostart";

import type {
  DesktopClient,
  LocalAccountInput,
  LocalCharacterInput,
  UpdateCheckResult,
} from "./Client";
import {
  AppConfigSchema,
  EqSettingsSchema,
  LocalDataSchema,
  LogSnapshotSchema,
  ProxySettingsSchema,
  RuntimeStateSchema,
  SsoAccountsSchema,
  SsoBackendOptionSchema,
  SsoStatusSchema,
  type AppConfig,
  type EqSettingsView,
  type LocalDataView,
  type LogSnapshot,
  type ProxyMode,
  type ProxySettings,
  type RuntimeState,
  type SsoAccountsView,
  type SsoBackendOption,
  type SsoStatus,
} from "./schemas";

export class TauriClient implements DesktopClient {
  async getRuntimeState(): Promise<RuntimeState> {
    return RuntimeStateSchema.parse(await invoke("get_runtime_state"));
  }

  async setProxyModeSelection(mode: ProxyMode): Promise<RuntimeState> {
    return RuntimeStateSchema.parse(await invoke("set_proxy_mode_selection", { mode }));
  }

  async updateListenPort(listenPort: number): Promise<RuntimeState> {
    return RuntimeStateSchema.parse(await invoke("update_listen_port", { listenPort }));
  }

  async getProxySettings(): Promise<ProxySettings> {
    return ProxySettingsSchema.parse(await invoke("get_proxy_settings"));
  }

  async updateProxySettings(settings: ProxySettings): Promise<ProxySettings> {
    return ProxySettingsSchema.parse(await invoke("update_proxy_settings", { settings }));
  }

  async getAppConfig(): Promise<AppConfig> {
    return AppConfigSchema.parse(await invoke("get_app_config"));
  }

  async saveAppConfig(config: AppConfig): Promise<AppConfig> {
    return AppConfigSchema.parse(await invoke("save_app_config", { config }));
  }

  async getSsoStatus(): Promise<SsoStatus> {
    return SsoStatusSchema.parse(await invoke("get_sso_status"));
  }

  async getSsoBackends(): Promise<SsoBackendOption[]> {
    const raw = await invoke("get_sso_backends");
    return zodArray(SsoBackendOptionSchema, raw);
  }

  async getSsoAccounts(): Promise<SsoAccountsView> {
    return SsoAccountsSchema.parse(await invoke("get_sso_accounts"));
  }

  async setSsoToken(token: string): Promise<SsoStatus> {
    return SsoStatusSchema.parse(await invoke("set_sso_token", { token }));
  }

  async clearSsoToken(): Promise<SsoStatus> {
    return SsoStatusSchema.parse(await invoke("clear_sso_token"));
  }

  async setSsoBackend(backend: string, apiUrl?: string): Promise<SsoStatus> {
    return SsoStatusSchema.parse(await invoke("set_sso_backend", { backend, apiUrl }));
  }

  async reconnectSso(): Promise<SsoStatus> {
    return SsoStatusSchema.parse(await invoke("reconnect_sso"));
  }

  async getLocalData(): Promise<LocalDataView> {
    return LocalDataSchema.parse(await invoke("get_local_data"));
  }

  async saveLocalData(
    accounts: LocalAccountInput[],
    characters: LocalCharacterInput[],
    allowEmptyAccounts = false,
  ): Promise<LocalDataView> {
    return LocalDataSchema.parse(
      await invoke("save_local_data", { accounts, characters, allowEmptyAccounts }),
    );
  }

  async reloadLocalData(): Promise<LocalDataView> {
    return LocalDataSchema.parse(await invoke("reload_local_data"));
  }

  async getEqSettings(): Promise<EqSettingsView> {
    return EqSettingsSchema.parse(await invoke("get_eq_settings"));
  }

  async setEqDirectory(path: string): Promise<EqSettingsView> {
    return EqSettingsSchema.parse(await invoke("set_eq_directory", { path }));
  }

  async browseEqExecutable(): Promise<string | null> {
    return (await invoke("browse_eq_executable")) as string | null;
  }

  async resetEqhostBackup(): Promise<EqSettingsView> {
    return EqSettingsSchema.parse(await invoke("reset_eqhost_backup"));
  }

  async restoreEqhostBackup(): Promise<EqSettingsView> {
    return EqSettingsSchema.parse(await invoke("restore_eqhost_backup"));
  }

  async saveEqhostContents(contents: string): Promise<EqSettingsView> {
    return EqSettingsSchema.parse(await invoke("save_eqhost_contents", { contents }));
  }

  async openEqFolder(): Promise<void> {
    await invoke("open_eq_folder");
  }

  async launchEverquest(): Promise<void> {
    await invoke("launch_everquest");
  }

  async getChangelog(): Promise<string> {
    return (await invoke("get_changelog")) as string;
  }

  async fetchGithubChangelog(): Promise<string> {
    return (await invoke("fetch_github_changelog")) as string;
  }

  async getRecentLogs(limit = 200, minLevel = "DEBUG"): Promise<LogSnapshot> {
    return LogSnapshotSchema.parse(
      await invoke("get_recent_logs", { limit, minLevel }),
    );
  }

  async clearLogs(): Promise<void> {
    await invoke("clear_logs");
  }

  async checkForUpdates(notifyNoUpdate = true): Promise<UpdateCheckResult> {
    return (await invoke("check_for_updates", { notifyNoUpdate })) as UpdateCheckResult;
  }

  async showWindow(): Promise<void> {
    await invoke("show_window");
  }

  async hideWindow(): Promise<void> {
    await invoke("hide_window");
  }

  async requestShutdown(): Promise<void> {
    await invoke("request_shutdown");
  }

  async getLaunchAtLogin(): Promise<boolean> {
    return isEnabled();
  }

  async setLaunchAtLogin(enabled: boolean): Promise<boolean> {
    if (enabled) {
      await enable();
    } else if (await isEnabled()) {
      await disable();
    }
    return isEnabled();
  }
}

function zodArray<T>(schema: { parse: (v: unknown) => T }, raw: unknown): T[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((item) => schema.parse(item));
}
