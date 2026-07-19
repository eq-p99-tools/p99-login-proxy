import type {
  AppConfig,
  BootstrapState,
  ProxyMode,
  RuntimeState,
} from "./schemas";
import type {
  DesktopClient,
  EqSettingsView,
  LocalAccountInput,
  LocalCharacterInput,
  LocalDataView,
  LogSnapshot,
  ProxySettings,
  SsoAccountsView,
  SsoBackendOption,
  SsoStatus,
  UpdateCheckResult,
} from "./Client";

const MOCK_BOOTSTRAP: BootstrapState = {
  version: "0.1.0-mock",
  platform: "mock",
  has_token: false,
  proxy_lifecycle: "stopped",
  ws_state: "disconnected",
  ws_error: null,
  listen_address: "127.0.0.1",
  listen_port: 6998,
};

const MOCK_SETTINGS: ProxySettings = {
  listen_host: "127.0.0.1",
  listen_port: 6998,
  upstream_host: "login.eqemulator.net",
  upstream_port: 5998,
  proxy_only: false,
  skip_sso_accounts: "",
};

const MOCK_CONFIG: AppConfig = {
  ...MOCK_SETTINGS,
  sso_backend: "Good Guys",
  dark_mode: true,
  theme_mode: "system",
  prerelease_updates: false,
  eq_directory: null,
  eq_directory_secondary: null,
  proxy_enabled: true,
  always_on_top: false,
  launch_startup: false,
  launch_admin: true,
  warn_rustle: false,
  auto_add_local_characters: true,
};

const MOCK_SSO: SsoStatus = {
  backend: "Good Guys",
  api_url: "https://proxy.p99loginproxy.net",
  has_token: false,
  api_token: "",
  ws_state: "disconnected",
  ws_error: null,
  account_count: 0,
};

function mockRuntime(
  bootstrap: BootstrapState,
  mode: ProxyMode = "disabled",
): RuntimeState {
  const running = mode !== "disabled";
  return {
    bootstrap: {
      ...bootstrap,
      proxy_lifecycle: running ? "running" : "stopped",
    },
    proxy: {
      lifecycle: running ? "running" : "stopped",
      client_connected: false,
    },
    stats: {
      total_connections: 0,
      active_connections: 0,
      completed_connections: 0,
      uptime_secs: running ? 42 : 0,
      uptime_display: running ? "42s" : "0s",
      last_username: null,
      last_account: null,
      last_login_method: null,
      last_heartbeat_at_ms: null,
      heartbeat_character: null,
      proxy_mode: mode,
      eq_config_enabled: running,
      eqhost_proxy_enabled: running,
      eqclient_log_enabled: running,
      listen_address: bootstrap.listen_address,
      listen_port: bootstrap.listen_port,
      client_connected: false,
    },
  };
}

export class MockClient implements DesktopClient {
  private bootstrap = { ...MOCK_BOOTSTRAP };
  private settings = { ...MOCK_SETTINGS };
  private config = { ...MOCK_CONFIG };
  private mode: ProxyMode = "disabled";
  private sso = { ...MOCK_SSO };
  private accounts: SsoAccountsView = { account_tree: {}, account_count: 0 };
  private localAccounts: LocalDataView["accounts"] = [];
  private localCharacters: LocalDataView["characters"] = [];
  private eqDir: string | null = null;
  private passwordStore = new Map<string, string>();
  private launchAtLogin = false;

  async getBootstrapState(): Promise<BootstrapState> {
    return { ...this.bootstrap };
  }

  async getRuntimeState(): Promise<RuntimeState> {
    return mockRuntime(this.bootstrap, this.mode);
  }

  async setProxyModeSelection(mode: ProxyMode): Promise<RuntimeState> {
    this.mode = mode;
    this.settings.proxy_only = mode === "enabled_proxy_only";
    this.bootstrap.proxy_lifecycle = mode === "disabled" ? "stopped" : "running";
    return mockRuntime(this.bootstrap, this.mode);
  }

  async updateListenPort(listenPort: number): Promise<RuntimeState> {
    this.bootstrap.listen_port = listenPort;
    this.bootstrap.listen_address = this.settings.listen_host;
    this.settings.listen_port = listenPort;
    this.config.listen_port = listenPort;
    return mockRuntime(this.bootstrap, this.mode);
  }

  async getProxySettings(): Promise<ProxySettings> {
    return { ...this.settings };
  }

  async updateProxySettings(settings: ProxySettings): Promise<ProxySettings> {
    this.settings = { ...settings };
    return { ...this.settings };
  }

  async getAppConfig(): Promise<AppConfig> {
    return { ...this.config, eq_directory: this.eqDir };
  }

  async saveAppConfig(config: AppConfig): Promise<AppConfig> {
    this.config = { ...config };
    this.eqDir = config.eq_directory;
    return { ...this.config };
  }

  async getSsoStatus(): Promise<SsoStatus> {
    return { ...this.sso };
  }

  async getSsoBackends(): Promise<SsoBackendOption[]> {
    return [{ name: "Good Guys", api_url: MOCK_SSO.api_url }];
  }

  async getSsoAccounts(): Promise<SsoAccountsView> {
    return { ...this.accounts, account_tree: { ...this.accounts.account_tree } };
  }

  async setSsoToken(token: string): Promise<SsoStatus> {
    this.sso = {
      ...this.sso,
      has_token: Boolean(token),
      api_token: token,
      ws_state: "connected",
    };
    return { ...this.sso };
  }

  async clearSsoToken(): Promise<SsoStatus> {
    this.sso = { ...MOCK_SSO };
    return { ...this.sso };
  }

  async setSsoBackend(backend: string, apiUrl?: string): Promise<SsoStatus> {
    this.sso = {
      ...this.sso,
      backend,
      api_url: apiUrl ?? this.sso.api_url,
      api_token: "",
      has_token: false,
    };
    return { ...this.sso };
  }

  async reconnectSso(): Promise<SsoStatus> {
    this.sso = { ...this.sso, ws_state: "connected" };
    return { ...this.sso };
  }

  async getLocalData(): Promise<LocalDataView> {
    return { accounts: [...this.localAccounts], characters: [...this.localCharacters] };
  }

  async saveLocalData(
    accounts: LocalAccountInput[],
    characters: LocalCharacterInput[],
  ): Promise<LocalDataView> {
    for (const row of accounts) {
      const password =
        row.password && row.password.length > 0
          ? row.password
          : (this.passwordStore.get(row.name) ?? "");
      if (!password) {
        throw new Error(`password required for new account '${row.name}'`);
      }
      this.passwordStore.set(row.name, password);
    }
    this.localAccounts = accounts.flatMap((a) => {
      const password =
        a.password && a.password.length > 0
          ? a.password
          : (this.passwordStore.get(a.name) ?? "");
      return [
        { alias: a.name, username: a.name, password },
        ...a.aliases.map((alias) => ({ alias, username: a.name, password })),
      ];
    });
    this.localCharacters = characters.map((c) => ({
      name: c.name,
      account_alias: c.account_alias,
      server: c.server ?? "",
      class: c.class ?? null,
      level: c.level ?? null,
      bind: c.bind ?? null,
      park: c.park ?? null,
      items: c.items ?? {},
    }));
    return this.getLocalData();
  }

  async reloadLocalData(): Promise<LocalDataView> {
    return this.getLocalData();
  }

  async getEqSettings(): Promise<EqSettingsView> {
    return {
      eq_directory: this.eqDir,
      eq_directory_secondary: this.config.eq_directory_secondary,
      eqhost_path: this.eqDir ? `${this.eqDir}\\eqhost.txt` : null,
      eqhost_contents: null,
      eqhost_backup_contents: null,
      eqhost_backup_exists: false,
      proxy_enabled_in_eqhost: this.mode !== "disabled",
      eq_directory_valid: Boolean(this.eqDir),
    };
  }

  async setEqDirectory(path: string): Promise<EqSettingsView> {
    this.eqDir = path || null;
    this.config.eq_directory = this.eqDir;
    return this.getEqSettings();
  }

  async browseEqExecutable(): Promise<string | null> {
    return "C:\\Games\\EverQuest";
  }

  async resetEqhostBackup(): Promise<EqSettingsView> {
    const settings = await this.getEqSettings();
    return {
      ...settings,
      eqhost_backup_exists: true,
      eqhost_backup_contents: "[LoginServer]\nHost=login.eqemulator.net:5998\n",
    };
  }

  async restoreEqhostBackup(): Promise<EqSettingsView> {
    return this.getEqSettings();
  }

  async saveEqhostContents(contents: string): Promise<EqSettingsView> {
    const settings = await this.getEqSettings();
    return { ...settings, eqhost_contents: contents };
  }

  async openEqFolder(): Promise<void> {}

  async launchEverquest(): Promise<void> {}

  async getChangelog(): Promise<string> {
    return "<h2>Changelog</h2><p>Mock build.</p>";
  }

  async fetchGithubChangelog(): Promise<string> {
    return this.getChangelog();
  }

  async getRecentLogs(): Promise<LogSnapshot> {
    return {
      lines: [
        {
          timestamp: "2026-07-13 20:00:00",
          level: "INFO",
          target: "mock",
          message: `Proxy ${this.bootstrap.proxy_lifecycle}`,
        },
      ],
      file_path: "C:\\mock\\proxy.log",
    };
  }

  async clearLogs(): Promise<void> {}

  async checkForUpdates(): Promise<UpdateCheckResult> {
    return {
      available: false,
      title: "No Update Available",
      message: "You are on the latest version.",
    };
  }

  async showWindow(): Promise<void> {}
  async hideWindow(): Promise<void> {}
  async requestShutdown(): Promise<void> {}

  async getLaunchAtLogin(): Promise<boolean> {
    return this.launchAtLogin;
  }

  async setLaunchAtLogin(enabled: boolean): Promise<boolean> {
    this.launchAtLogin = enabled;
    return enabled;
  }

  /** Test helper: inject malformed SSO data */
  setMockAccounts(view: SsoAccountsView) {
    this.accounts = view;
  }
}
