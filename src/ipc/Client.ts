import type {
  AppConfig,
  BootstrapState,
  EqSettingsView,
  LocalCharacterInput,
  LocalDataView,
  LogSnapshot,
  ProxyMode,
  ProxySettings,
  RuntimeState,
  SsoAccountsView,
  SsoBackendOption,
  SsoStatus,
} from "./schemas";

export type {
  AppConfig,
  BootstrapState,
  EqSettingsView,
  LocalAccount,
  LocalCharacter,
  LocalCharacterInput,
  LocalDataView,
  LogLine,
  LogSnapshot,
  ProxyMode,
  ProxySettings,
  ProxyStats,
  RuntimeState,
  SsoAccountsView,
  SsoBackendOption,
  SsoStatus,
} from "./schemas";

export interface LocalAccountInput {
  name: string;
  password?: string;
  aliases: string[];
}

export interface UpdateCheckResult {
  available: boolean;
  version?: string;
  title: string;
  message: string;
}

export interface DesktopClient {
  getBootstrapState(): Promise<BootstrapState>;
  getRuntimeState(): Promise<RuntimeState>;
  setProxyModeSelection(mode: ProxyMode): Promise<RuntimeState>;
  updateListenPort(listenPort: number): Promise<RuntimeState>;
  getProxySettings(): Promise<ProxySettings>;
  updateProxySettings(settings: ProxySettings): Promise<ProxySettings>;
  getAppConfig(): Promise<AppConfig>;
  saveAppConfig(config: AppConfig): Promise<AppConfig>;
  getSsoStatus(): Promise<SsoStatus>;
  getSsoBackends(): Promise<SsoBackendOption[]>;
  getSsoAccounts(): Promise<SsoAccountsView>;
  setSsoToken(token: string): Promise<SsoStatus>;
  clearSsoToken(): Promise<SsoStatus>;
  setSsoBackend(backend: string, apiUrl?: string): Promise<SsoStatus>;
  reconnectSso(): Promise<SsoStatus>;
  getLocalData(): Promise<LocalDataView>;
  saveLocalData(accounts: LocalAccountInput[], characters: LocalCharacterInput[]): Promise<LocalDataView>;
  reloadLocalData(): Promise<LocalDataView>;
  getEqSettings(): Promise<EqSettingsView>;
  setEqDirectory(path: string): Promise<EqSettingsView>;
  browseEqExecutable(): Promise<string | null>;
  resetEqhostBackup(): Promise<EqSettingsView>;
  restoreEqhostBackup(): Promise<EqSettingsView>;
  saveEqhostContents(contents: string): Promise<EqSettingsView>;
  openEqFolder(): Promise<void>;
  launchEverquest(): Promise<void>;
  getChangelog(): Promise<string>;
  fetchGithubChangelog(): Promise<string>;
  getRecentLogs(limit?: number): Promise<LogSnapshot>;
  clearLogs(): Promise<void>;
  checkForUpdates(): Promise<UpdateCheckResult>;
  showWindow(): Promise<void>;
  hideWindow(): Promise<void>;
  requestShutdown(): Promise<void>;
}
