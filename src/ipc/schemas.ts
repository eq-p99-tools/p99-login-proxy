import { z } from "zod";

export const ProxyLifecycleSchema = z.enum([
  "stopped",
  "starting",
  "running",
  "stopping",
]);

export const WsConnectionStateSchema = z.enum([
  "disconnected",
  "connecting",
  "connected",
  "auth_failed",
  "parked",
]);

export const ProxyModeSchema = z.enum([
  "enabled_sso",
  "enabled_proxy_only",
  "disabled",
]);

export const ThemeModeSchema = z.enum([
  "dark",
  "light",
  "system",
  "gnomish",
  "iceclad",
  "kelethin",
  "lavastorm",
  "erudin",
  "paineel",
]);

export const BootstrapStateSchema = z.object({
  version: z.string(),
  platform: z.string(),
  has_token: z.boolean(),
  proxy_lifecycle: ProxyLifecycleSchema,
  ws_state: WsConnectionStateSchema,
  ws_error: z.string().nullable().optional().transform((v) => v ?? null),
  listen_address: z.string(),
  listen_port: z.number(),
});

export const ProxyStatsSchema = z.object({
  total_connections: z.number(),
  active_connections: z.number(),
  completed_connections: z.number(),
  uptime_secs: z.number(),
  uptime_display: z.string(),
  last_username: z.string().nullable().optional().transform((v) => v ?? null),
  last_account: z.string().nullable().optional().transform((v) => v ?? null),
  last_login_method: z.string().nullable().optional().transform((v) => v ?? null),
  last_heartbeat_at_ms: z.number().nullable().optional().transform((v) => v ?? null),
  heartbeat_character: z.string().nullable().optional().transform((v) => v ?? null),
  proxy_mode: ProxyModeSchema,
  eq_config_enabled: z.boolean(),
  eqhost_proxy_enabled: z.boolean().default(false),
  eqclient_log_enabled: z.boolean().default(false),
  listen_address: z.string(),
  listen_port: z.number(),
  client_connected: z.boolean(),
});

export const ProxyStatusSchema = z.object({
  lifecycle: ProxyLifecycleSchema,
  client_connected: z.boolean(),
});

export const RuntimeStateSchema = z.object({
  bootstrap: BootstrapStateSchema,
  proxy: ProxyStatusSchema,
  stats: ProxyStatsSchema,
});

export const ProxySettingsSchema = z.object({
  listen_host: z.string(),
  listen_port: z.number(),
  upstream_host: z.string(),
  upstream_port: z.number(),
  proxy_only: z.boolean(),
  skip_sso_accounts: z.string(),
});

export const AppConfigSchema = z.object({
  listen_host: z.string(),
  listen_port: z.number(),
  upstream_host: z.string(),
  upstream_port: z.number(),
  proxy_only: z.boolean(),
  skip_sso_accounts: z.string(),
  sso_backend: z.string(),
  dark_mode: z.boolean(),
  theme_mode: ThemeModeSchema.optional().default("system"),
  prerelease_updates: z.boolean(),
  eq_directory: z.string().nullable().optional().transform((v) => v ?? null),
  eq_directory_secondary: z.string().nullable().optional().transform((v) => v ?? null),
  proxy_enabled: z.boolean().optional().default(true),
  always_on_top: z.boolean().optional().default(false),
  launch_startup: z.boolean().optional().default(false),
  launch_admin: z.boolean().optional().default(true),
  warn_rustle: z.boolean().optional().default(false),
  auto_add_local_characters: z.boolean().optional().default(false),
});

export const SsoStatusSchema = z.object({
  backend: z.string(),
  api_url: z.string(),
  has_token: z.boolean(),
  api_token: z.string(),
  ws_state: WsConnectionStateSchema,
  ws_error: z.string().nullable().optional().transform((v) => v ?? null),
  account_count: z.number(),
});

export const SsoBackendOptionSchema = z.object({
  name: z.string(),
  api_url: z.string(),
});

export const SsoAccountsSchema = z.object({
  account_tree: z
    .unknown()
    .nullable()
    .optional()
    .transform((v) => (v != null && typeof v === "object" && !Array.isArray(v) ? v : {})),
  account_count: z.number().default(0),
  stale: z.boolean().default(false),
});

export const LocalAccountSchema = z.object({
  alias: z.string(),
  username: z.string(),
  password: z.string().default(""),
});

export const LocalCharacterItemValueSchema = z.union([z.boolean(), z.number(), z.null()]);

export const LocalCharacterSchema = z.object({
  name: z.string(),
  account_alias: z.string(),
  server: z.string().default(""),
  class: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? null),
  level: z
    .number()
    .nullable()
    .optional()
    .transform((v) => v ?? null),
  bind: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? null),
  park: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? null),
  items: z.record(z.string(), LocalCharacterItemValueSchema).default({}),
});

export const LocalDataSchema = z.object({
  accounts: z.array(LocalAccountSchema).default([]),
  characters: z.array(LocalCharacterSchema).default([]),
});

export const EqSettingsSchema = z.object({
  eq_directory: z.string().nullable().optional().transform((v) => v ?? null),
  eq_directory_secondary: z.string().nullable().optional().transform((v) => v ?? null),
  eqhost_path: z.string().nullable().optional().transform((v) => v ?? null),
  eqhost_contents: z.string().nullable().optional().transform((v) => v ?? null),
  eqhost_backup_contents: z.string().nullable().optional().transform((v) => v ?? null),
  eqhost_backup_exists: z.boolean().default(false),
  proxy_enabled_in_eqhost: z.boolean().default(false),
  eq_directory_valid: z.boolean().default(false),
});

export const LogLineSchema = z.object({
  timestamp: z.string(),
  level: z.string(),
  target: z.string(),
  message: z.string(),
});

export const LogSnapshotSchema = z.object({
  lines: z.array(LogLineSchema),
  file_path: z.string().nullable().optional().transform((v) => v ?? null),
});

export type BootstrapState = z.infer<typeof BootstrapStateSchema>;
export type ProxyLifecycle = z.infer<typeof ProxyLifecycleSchema>;
export type WsConnectionState = z.infer<typeof WsConnectionStateSchema>;
export type ProxyMode = z.infer<typeof ProxyModeSchema>;
export type ThemeMode = z.infer<typeof ThemeModeSchema>;
export type ProxyStats = z.infer<typeof ProxyStatsSchema>;
export type RuntimeState = z.infer<typeof RuntimeStateSchema>;
export type ProxySettings = z.infer<typeof ProxySettingsSchema>;
export type AppConfig = z.infer<typeof AppConfigSchema>;
export type SsoStatus = z.infer<typeof SsoStatusSchema>;
export type SsoBackendOption = z.infer<typeof SsoBackendOptionSchema>;
export type SsoAccountsView = z.infer<typeof SsoAccountsSchema>;
export type LocalAccount = z.infer<typeof LocalAccountSchema>;
export type LocalCharacter = z.infer<typeof LocalCharacterSchema>;
export type LocalCharacterInput = {
  name: string;
  account_alias: string;
  server?: string;
  class?: string | null;
  level?: number | null;
  bind?: string | null;
  park?: string | null;
  items?: Record<string, boolean | number | null>;
};
export type LocalDataView = z.infer<typeof LocalDataSchema>;
export type EqSettingsView = z.infer<typeof EqSettingsSchema>;
export type LogLine = z.infer<typeof LogLineSchema>;
export type LogSnapshot = z.infer<typeof LogSnapshotSchema>;

export function parseRuntimeState(raw: unknown): RuntimeState {
  return RuntimeStateSchema.parse(raw);
}

export function parseBootstrap(raw: unknown): BootstrapState {
  return BootstrapStateSchema.parse(raw);
}

export function parseSsoAccounts(raw: unknown): SsoAccountsView {
  return SsoAccountsSchema.parse(raw);
}
