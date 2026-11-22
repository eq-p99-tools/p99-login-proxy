# SSO Proxy Backend Protocol (Implementer Guide)

This guide is for people and agents implementing an SSO backend that the P99 Login Proxy can talk to. It covers HTTP and WebSocket endpoints, message shapes, credential crypto, access control outcomes and verification.

## Relationship to the JSON Schema (read first)

**Additive: this guide does not replace the schema.**

| Artifact | Role |
|---|---|
| [`schemas/ws-protocol.schema.json`](../schemas/ws-protocol.schema.json) + [`schemas/fixtures/`](../schemas/fixtures/) | **Normative machine-readable wire contract** for WS message envelopes (`type`, required fields, consts). Owned by this repo. |
| **This document** | **Implementer guide**: flows, MUST/SHOULD, DES crypto, RBAC and username resolution, proxy gating, size caps, checklists, HTTP fallback. |

Rules:
- Message shapes in this guide **MUST NOT diverge** from the schema and fixtures.
- When extending the wire, update **schema + fixtures + this guide in the same change**, here in `p99-login-proxy`.
- Behaviors the schema cannot express (timeouts, crypto, RBAC, size caps, SSO name-set gating) are specified here and in working code.
- Do **not** delete or bypass the schema.

Client: **p99-login-proxy** (this repo, Rust; `crates/runtime/src/websocket.rs`).
Reference backend: **[roboToald](https://github.com/eq-p99-tools/roboToald)** (`roboToald/api/server.py`, `roboToald/api/websocket.py`). The schema and fixtures live only in this repo; roboToald keeps no copy and validates its live server output against them from a checkout of this repo.

Language: **MUST** / **SHOULD** / **MAY**.
Labels: **[proxy-required]** = the proxy breaks or skips SSO without it. **[reference]** = roboToald behavior; not required for a minimal compatible backend unless also marked proxy-required.

---

## 0. Agent brief

### Goal
Implement an HTTP + WebSocket API such that an unmodified P99 Login Proxy can authenticate with an access key, receive an account name cache, request encrypted EQ credentials on login, and push telemetry: heartbeats, locations, inventory and spellbook exports, faction hits, first-to-engage reports and raid mob deaths.

### Non-goals
- Speaking the SOE/EQ UDP login protocol (proxy to EQEmu only).
- Discord admin UX, dashboard cookies, slash commands (**[reference]** management plane).
- Matching roboToald's Discord RBAC storage model exactly. Only the **wire outcomes** matter for proxy compatibility.
- Replacing `schemas/ws-protocol.schema.json` with prose.

### Canonical sources of truth (in order)
1. **`schemas/ws-protocol.schema.json` + `schemas/fixtures/`**: normative WS wire shapes.
2. **This guide**: implementer semantics; must stay aligned with (1).
3. Working code when (1) and (2) are silent: proxy `crates/runtime/src/websocket.rs`, `crates/proxy-core/src/accounts_cache.rs`, `crates/proxy-core/src/decision.rs`; server `roboToald/api/server.py`, `roboToald/api/websocket.py`, `roboToald/db/models/sso.py`.
4. roboToald's `README_API.md` and other narrative docs: reference deployment and operations only.

### Ordered implementation checklist
1. `GET /` health JSON.
2. `WS /ws/accounts`: accept, require `auth` within 15s, validate the key, send `full_state`, send app-level `ping` about every 30s.
3. Handle client `ping` (reply `pong`), `pong`, `login_auth`, `heartbeat`, `update_location`. Ignore unknown `type`.
4. `login_auth_response` with Base64 DES-CBC credentials (test vector in §5.5).
5. Push `delta` on account-tree changes (shape in §5.3).
6. Username resolution and access control, so only authorized names appear in `account_tree` and succeed `login_auth`.
7. Optionally `POST /auth` (HTTP plaintext fallback; **not** used by the proxy).
8. Optionally `update_inventory` and `update_spellbook` (proxy sends; silent drop is OK for login compatibility).
9. Optionally `fte`, `mob_death` and `faction_hits` (proxy sends; silent drop is OK for login compatibility). roboToald ignores `faction_hits`.
9a. Optionally send `show_modal` popups (§5.7).
10. Verify with §12.

---

## 1. Roles and topology

```
EQ Client --UDP SOE--> Login Proxy --WSS JSON--> SSO Backend
                           |
                           +--UDP--> EQEmu login server (rewritten credentials)
```

| Actor | Responsibility |
|---|---|
| Backend | Access-key auth, account tree, credential issue, telemetry ingest |
| Proxy | WS client, name-set SSO gating, DES splice into the SOE Login packet |
| EQ client / login server | Out of scope |

The proxy uses the **WebSocket only** for SSO login (`login_auth`). It never calls `POST /auth`.

---

## 2. Transport

### Endpoints

| Method | Path | Proxy uses? | Notes |
|---|---|---|---|
| `GET` | `/` | No (ops) | Health |
| `POST` | `/auth` | **No** | **[reference]** fallback for older clients |
| `WS` | `/ws/accounts` | **Yes** | Primary |
| `POST` | `/list_accounts`, `/heartbeat`, `/update_location` | No | **[reference]** returns 404; do not revive |

### URL derivation **[proxy-required]**
Proxy config `sso_api` (trailing `/` stripped):
- `https://host` → `wss://host/ws/accounts`
- `http://host` → `ws://host/ws/accounts`
- `wss://host` / `ws://host` → base + `/ws/accounts`
- anything else → `wss://` + base + `/ws/accounts`

### TLS **[proxy-required]**
- Default: verify against the bundled Mozilla (webpki) root set.
- `sso_ca_bundle` selects the trust store: unset or `true` → bundled roots; `system` or `false` → platform trust store; any other value → path to a PEM CA bundle (a missing file is a config validation error).
- `sso_verify_tls=false` disables verification entirely (emergency; overrides `sso_ca_bundle`).
- Plain `ws://` is allowed (no TLS).

### Timeouts and reconnect **[proxy-required]**
| Constant | Value | Effect |
|---|---|---|
| Auth first-message wait | **15s** server-side | Else close 4001 |
| WS connect timeout | 5s (proxy) | Counts as a failed attempt; backoff applies |
| `login_auth` wait | `sso_timeout` default **10s** | Proxy treats it as a failure and forwards the original login |
| App ping interval | **30s** **[reference]**, random initial jitter | Proxy replies `pong` |
| Reconnect backoff | 1s → 60s exponential | On drop or connect failure |
| Server rejection (`error` message or close code 4000–4099) | Parked | No reconnect until the user reconnects or changes token/URL |
| Missing `sso_api` or token | Parked | Rechecked every 30s |

The proxy also answers WebSocket-level ping frames with pong frames.

On any disconnect the proxy marks itself disconnected, fails pending `login_auth` requests, clears its export dedup state, and **clears the account cache**. SSO rewriting stops until a new `full_state`.

---

## 3. Connection sequence **[proxy-required]**

```
Client                         Server
|-- WS upgrade --------------->|
|-- auth (JSON text) --------->|   MUST arrive within 15s
|                              |-- validate --|
|<-- error {detail} + close ---|   on failure
|<-- full_state ---------------|   on success; proxy sets connected=true
|   ... bidirectional ...      |
|<-- ping ---------------------|
|-- pong --------------------->|
|-- login_auth / heartbeat / update_location / update_inventory / update_spellbook / fte / mob_death / faction_hits / ping -->|
|<-- login_auth_response / delta / ping / pong / show_modal -------|
```

Invariants:
- The first message MUST be `auth` with a non-empty `access_key`.
- The proxy marks itself connected **only** after `full_state` (not after WS open, not after sending `auth`).
- Until then, `login_auth` fails client-side with `"WebSocket not connected"` and telemetry is not sent.

---

## 4. Message catalog

Schema: `schemas/ws-protocol.schema.json` (draft 2020-12).
Every message is a JSON object with discriminator `type`. Unknown properties MAY appear; receivers SHOULD ignore them. Unknown `type` after auth: MUST ignore (no close). Undecodable JSON after auth: **[reference]** ignored.

### 4.1 Direction summary

| `type` | Dir | Required fields (schema) |
|---|---|---|
| `auth` | C→S | `type`, `access_key`, `client_version` |
| `full_state` | S→C | `type`, `account_tree`, `count`, `dynamic_tag_zones`, `dynamic_tag_classes` |
| `delta` | S→C | `type`, `changes` |
| `login_auth` | C→S | `type`, `request_id`, `username` |
| `login_auth_response` | S→C | `type`, `request_id` (+ success or error fields; optional `notes` on success) |
| `heartbeat` | C→S | `type`, `character_name` |
| `update_location` | C→S | `type`, `character_name` (optional: `park_location`, `bind_location`, `level`, `items`, legacy `keys`) |
| `update_inventory` | C→S | `type`, `character_name`, `inventory` |
| `update_spellbook` | C→S | `type`, `character_name`, `spellbook` |
| `fte` | C→S | `type`, `mob`, `player`, `character_name`, `eq_log_time` |
| `mob_death` | C→S | `type`, `mob`, `eq_log_time`, `character_name` |
| `faction_hits` | C→S | `type`, `character_name`, `eq_log_time`, `hits` (1–50 × `faction`, `direction`) |
| `ping` | either | `type` |
| `pong` | either | `type` |
| `error` | S→C | `type`, `detail` |
| `show_modal` | S→C | `type`, `title`, `message` (optional: `level`, `always_on_top`, `id`) |

### 4.2 Store-only messages

Only these change what other clients see through `full_state` and `delta`: a successful `login_auth`, `heartbeat`, `update_location`, `update_inventory`, and admin changes on the server. `update_spellbook` is store-only when a backend keeps it (spells are not in the account tree). `faction_hits` is optional telemetry: a backend MAY store it or ignore it, and it is not part of `full_state` or `delta`. roboToald ignores `faction_hits`. `fte` and `mob_death` are relayed elsewhere (roboToald posts to a Discord channel) and never affect the account tree. None of the C→S telemetry messages gets a reply.

### 4.3 Required vs optional (what the Rust proxy tolerates)

The schema's `required` arrays are the wire contract for producers and for schema checks. The Rust proxy (`crates/runtime/src/websocket.rs`, `crates/proxy-core/src/accounts_cache.rs`) is looser: unknown `type` values are ignored, unknown extra keys are ignored, and every inbound field except `login_auth_response.request_id` has `#[serde(default)]` or is `Option`. A **missing** key is filled in. A **present** key of the wrong JSON type fails decoding of that whole message, and the proxy skips it (debug log, connection stays up). This section is what a backend can rely on for an unmodified current proxy. Where it disagrees with the schema, the schema is left unchanged on purpose; see the divergence list below.

#### Messages a backend MAY ignore

The proxy sends these and never waits for a reply. Dropping them (no error, no close) leaves login working:

| Message | If ignored |
|---|---|
| `update_inventory` | Tracked items stay as they were. Login and the name cache are unaffected. |
| `update_spellbook` | No spell list is stored. Spells are never in `full_state` or `delta`. |
| `faction_hits` | Nothing is stored. roboToald does this: the type is not handled, same as any unknown type. Another backend MAY store the hits. |
| `fte`, `mob_death` | No raid relay. roboToald posts them to Discord; that is optional. |
| `heartbeat`, `update_location` | MUST be tolerated (do not close). Persisting them is what keeps `last_login`, sessions, `active_character` and locations live. A backend MAY ignore the contents. |
| `pong` | The proxy does not send application-level `ping` (it answers a server `ping` with `pong`). A server `pong` is ignored. |

Any other `type` after auth MUST be ignored the same way.

#### Messages a backend MAY never send

| Message | If omitted |
|---|---|
| `show_modal` | No server popup. Login notes, rejected logins and connection errors still use their existing messages. roboToald does not send `show_modal`. |
| `ping` | The proxy does not disconnect for a missing application ping. A ping loop is recommended, not required. |
| `delta` | The cache stays at the last `full_state` until the next one. Live UI and newly added names wait for a `full_state`. |
| `login_auth_response.notes` | Login proceeds with no notes popup. |
| `POST /auth` | The proxy never calls it. |

`full_state` is what marks the proxy connected. `login_auth_response` is what completes a gated login. An `error` message (or a close code 4000–4099) is what parks the proxy instead of reconnecting.

#### Optional keys inside messages

**`login_auth_response`.** `request_id` is required to decode the message: missing, null or non-string drops the whole response, and the pending login times out (`sso_timeout`, default 10s) and the original packet is forwarded. `real_user`, `encrypted_credentials`, `error` and `notes` may be omitted. The proxy splices only when `error` is absent and both `real_user` and a decodable, non-empty `encrypted_credentials` are present. `status` is ignored. When `notes` is present, `account` and `characters` may be omitted (they default to null and `{}`); a malformed `notes` value is ignored and the login still succeeds.

**`full_state`.** `account_tree`, `dynamic_tag_zones` and `dynamic_tag_classes` may be omitted (empty tree, no dynamic tags). `count` is not read; the UI count is the number of keys in `account_tree`. Inside an account entry, every field is optional for decoding and for the SSO name cache: the cache uses the account key, string entries of `aliases` and `tags`, character names, and the `dynamic_tag_zones` × `dynamic_tag_classes` concatenations. Missing lists contribute no names. `group_roles`, account and character `notes`, `owned`, `shared`, `last_login`, `last_login_by`, `active_character`, and character `class` / `bind` / `park` / `level` / `items` / `keys` are display data; omitting them does not affect gating.

**`delta.changes`.** May be omitted (no-op). A change is applied only when `action` and `account` are strings. `add` without `data` is skipped. `update` applies `aliases`, `tags` and `group_roles` (`add` / `remove` of strings), `characters` (`add` / `remove` / `update` of whole character objects), and the scalars `last_login`, `last_login_by`, `active_character`, `notes`. Other keys inside `fields`, including `owned` and `shared`, are ignored. `entity` is ignored.

**`show_modal`.** Every field is optional. Both `title` and `message` empty or missing → the popup is dropped. A missing title gets a default for the level (`info` when `level` is missing or unknown). `always_on_top` defaults to false. `id` is only a dedupe key.

**`error`.** `detail` may be omitted (the proxy shows "authentication failed") and may be sent as `message`, `reason` or `error`. The type may be `error`, `auth_failed` or `close`. The schema still requires `detail` on `error`.

**`auth` (proxy → server).** The proxy always sends `client_version` and a `client_settings` object. `client_settings` may be `{}`. Keys the proxy sends are `log_enabled` and, after it has checked the EQ UI files, `rustle_present`. A backend MAY ignore the object or either key. Extra keys are fine.

**`update_location` (proxy → server).** `park_location`, `bind_location`, `level` and `items` are each omitted when the proxy has nothing to send. A backend MAY ignore the message or any of those keys. The current proxy does not send legacy `keys`.

#### Where the schema is stricter than the proxy

These are known divergences. The schema is **not** changed to match the proxy until that is decided; a backend whose output is schema-checked (roboToald's CI is) should keep satisfying the schema.

| Schema `required` | Rust proxy |
|---|---|
| `full_state`: `account_tree`, `count`, `dynamic_tag_zones`, `dynamic_tag_classes` | `account_tree` and the two tag lists default when absent (`count` is not a field the proxy deserializes). A wrong type on a tag list fails the whole `full_state`. |
| `delta`: `changes` | Defaults when absent; a non-array is a no-op. |
| `show_modal`: `title`, `message` | Both optional. Empty or missing title and message → dropped. |
| `error`: `detail` | Optional, with the aliases above. |
| `login_notes`: `account`, `characters` (when `notes` is present) | Both default. A value that does not decode as notes is ignored. |

The other direction (schema optional, proxy will not decode the message without it) does not occur. The only inbound field without a default is `login_auth_response.request_id`, which the schema already requires.

---

## 5. Wire shapes and semantics

### 5.1 `auth` (C→S)

```json
{
  "type": "auth",
  "access_key": "ConcentrateRedundantCollar",
  "client_version": "2.0.0",
  "client_settings": {
    "log_enabled": true,
    "rustle_present": false
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `access_key` | string, required | User's access key (stored in the OS keyring by the proxy) |
| `client_version` | string, required by schema; proxy always sends | Compared to the guild minimum **[reference]**; a missing value compares as `0.0.0` |
| `client_settings` | object, optional | If **omitted**, **[reference]** skips the `require_log` / `block_rustle` policies. If present, failing values reject (close 4011). The proxy sends `log_enabled` (bool, from `eqclient.ini`; `{}` when no EQ folder is configured) and `rustle_present` (bool) only after it has checked the EQ UI files. Extra keys are ignored. |

**[reference]** version compare: split on `.`, compare as integers (non-numeric segments count as 0). A pre-release suffix (`1.2.0-rc1`) sorts below the release it is attached to.

### 5.2 `full_state` (S→C) **[proxy-required]**

The schema requires `type`, `account_tree`, `count`, `dynamic_tag_zones`, `dynamic_tag_classes`. Example:

```json
{
  "type": "full_state",
  "account_tree": {
    "realbot01": {
      "aliases": ["myalias"],
      "tags": ["clr"],
      "characters": {
        "Zzzz": {
          "class": "Cleric",
          "bind": "tox",
          "park": "veeshan",
          "level": 60,
          "items": {
            "seb": true, "vp": false, "st": null,
            "void": null, "neck": null, "thurg": null,
            "reaper": null, "brass_idol": null,
            "lizard": null, "pearl": null, "peridot": null,
            "mb3": null, "mb4": null, "mb5": null
          },
          "keys": { "seb": true, "vp": false, "st": null },
          "notes": "Kael factioned"
        }
      },
      "last_login": "2025-01-15T03:22:00+00:00",
      "last_login_by": "DisplayName",
      "active_character": null,
      "owned": true,
      "shared": false,
      "group_roles": ["Member"],
      "notes": null
    }
  },
  "count": 1,
  "dynamic_tag_zones": ["seb", "vp", "st", "tov", "dn", "kael", "pog", "thurg", "ss", "fear", "vox", "naggy", "dain", "yeli", "zlandi", "trak"],
  "dynamic_tag_classes": ["bar", "brd", "bard", "clr", "cle", "cleric", "dru", "druid", "enc", "enchanter", "mag", "mage", "magician", "mnk", "mon", "monk", "nec", "necro", "necromancer", "pal", "pld", "paladin", "ran", "rng", "ranger", "rog", "rogue", "sk", "shadowknight", "sha", "shm", "sham", "shaman", "war", "warrior", "wiz", "wizard"]
}
```

`account_tree` MUST contain only accounts the access key may use (§7). `count` is the number of accounts in it. The proxy does not read `count`; it counts account-tree keys. §4.3 lists every place the schema's `required` list is stricter than what this proxy decodes.

#### Account tree entry fields

| Field | Type | Proxy use |
|---|---|---|
| map key (`real_user`) | string | **SSO gate**: added to the name cache (lowercased by the proxy) |
| `aliases[]` | string | **SSO gate** (lowercased) |
| `tags[]` | string | **SSO gate** (lowercased) |
| `characters` keys | string | **SSO gate** (lowercased); also decides which characters get telemetry |
| `characters.*.class` | string enum | UI |
| `characters.*.bind` / `park` | zone key string \| null | UI (null = unknown) |
| `characters.*.level` | int \| null | UI |
| `characters.*.items` | object | UI (see below) |
| `characters.*.keys` | object | Legacy duplicate of `seb` / `vp` / `st` for old clients; **[reference]** still emitted. New clients read `items`. |
| `characters.*.notes` | string \| null | Character login notes (plain text) |
| `last_login` | ISO-8601 UTC string \| null | UI; **[reference]** null if never logged in (year ≤ 1) |
| `last_login_by` | string \| null | UI (display name of whoever last logged in) |
| `active_character` | string \| null | UI (character of the most recent active session) |
| `owned` / `shared` | bool | UI: viewer owns the account / has a direct share and is not the owner |
| `group_roles[]` | string | UI only: role names on the account's groups, sorted and deduplicated. Access control stays server-side. |
| `notes` | string \| null | Account login notes (plain text) |

**Login notes** (`notes` on accounts and characters) are free text, at most 500 characters **[reference]**, trimmed, blank stored as null, editable by admins and account owners. They are visible to everyone with access to the account and **MUST** be rendered as plain text, never markup. Clients that predate notes ignore the field.

**CharacterClass enum values (exact strings):**
`Bard`, `Cleric`, `Druid`, `Enchanter`, `Magician`, `Monk`, `Necromancer`, `Paladin`, `Ranger`, `Rogue`, `ShadowKnight`, `Shaman`, `Warrior`, `Wizard`

#### `items` wire keys **[proxy-required]** for the UI

The server fills these from `update_inventory` exports and from partial `update_location` updates. The UI reads these names from `full_state` / `delta`.

| Key | Value | Meaning |
|---|---|---|
| `seb`, `vp`, `st` | bool \| null | Zone keys (Trakanon Idol, Key of Veeshan, Sleeper's Key) |
| `void`, `neck`, `thurg`, `reaper`, `brass_idol` | bool \| null | Box of the Void, Necklace of Resolution, Vial of Velium Vapors, Reaper of the Dead, Shiny Brass Idol |
| `lizard`, `pearl`, `peridot`, `mb3`, `mb4`, `mb5` | int ≥ 0 \| null | Stack counts: Lizard Blood Potion, Pearl, Peridot, Mana Battery - Class Three/Four/Five |

`null` = unknown. **[reference]** per-field "last updated" timestamps exist only in the database and are never sent.

### 5.3 `delta` (S→C) **[proxy-required]** for live updates

```json
{
  "type": "delta",
  "changes": [
    {
      "action": "add",
      "entity": "account",
      "account": "newacct",
      "data": { "aliases": [], "tags": [], "characters": {}, "last_login": null, "last_login_by": null, "active_character": null, "owned": false, "shared": false, "group_roles": [], "notes": null }
    },
    {
      "action": "remove",
      "entity": "account",
      "account": "oldacct"
    },
    {
      "action": "update",
      "entity": "account",
      "account": "realbot01",
      "fields": {
        "aliases": { "add": ["x"], "remove": ["y"] },
        "tags": { "add": [], "remove": [] },
        "group_roles": { "add": ["Officer"], "remove": [] },
        "characters": {
          "add": { "New": { "class": "Wizard", "bind": null, "park": null, "level": null, "items": { "seb": null, "vp": null, "st": null, "void": null, "neck": null, "lizard": null, "thurg": null, "reaper": null, "brass_idol": null, "pearl": null, "peridot": null, "mb3": null, "mb4": null, "mb5": null }, "notes": null, "keys": { "seb": null, "vp": null, "st": null } } },
          "remove": ["Gone"],
          "update": { "Zzzz": { "class": "Cleric", "bind": "tox", "park": "veeshan", "level": 60, "items": { "seb": true, "vp": true, "st": null, "void": null, "neck": null, "lizard": 2, "thurg": null, "reaper": null, "brass_idol": null, "pearl": 40, "peridot": 0, "mb3": null, "mb4": null, "mb5": null }, "notes": "Kael factioned", "keys": { "seb": true, "vp": true, "st": null } } }
        },
        "last_login": "2025-01-15T03:22:00+00:00",
        "last_login_by": "Name",
        "active_character": "Zzzz",
        "notes": "Shared with the raid team"
      }
    }
  ]
}
```

`entity` is always `"account"`. `add.data` is a full account entry (as in `full_state`). `fields` contains only changed fields; each `characters` sub-key appears only when it has entries.

| Diff field | Shape | Proxy applies on delta? |
|---|---|---|
| `aliases`, `tags`, `group_roles` | `{add:[], remove:[]}` | **Yes** |
| `characters` | `add` map / `remove` list / `update` map of **full** character objects (not partial diffs) | **Yes** |
| `last_login`, `last_login_by`, `active_character` | scalar (incl. null) | **Yes** |
| `notes` (account) | string \| null (null = cleared) | **Yes** |
| `owned`, `shared` | none | **[reference]** not field-diffed; only present in `add` and `full_state` |

**[reference]** pushes are filtered per connection (the server keeps the last tree it sent each connection and diffs against it; no message when nothing changed), debounced per guild for about 3s for heartbeat bursts, and immediate on successful login and admin RBAC changes.

### 5.4 `login_auth` / `login_auth_response` **[proxy-required]**

Request:
```json
{"type": "login_auth", "request_id": "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f", "username": "mytag"}
```

- `request_id`: opaque string, echoed back. The proxy uses a UUIDv4 in simple (32 hex) form.
- `username`: the proxy sends it **already lowercased**. It is an account name, alias, tag, character name or dynamic tag.

Success:
```json
{
  "type": "login_auth_response",
  "request_id": "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f",
  "real_user": "realbot01",
  "encrypted_credentials": "qqIv/3uQ7ssYIp1Nv6kGw5uiXJoY4ou/",
  "notes": {
    "account": "Shared with the raid team; log out after use.",
    "characters": { "Zzzz": "Kael factioned" }
  }
}
```

`notes` (optional, success only): login notes for the account the server **resolved** the username to. Tags and dynamic tags resolve only on the server, so this is the authoritative source; the proxy cannot reliably map a tag to an account from its cache.
- **[reference]** present only when the account or at least one of its characters has notes; omitted otherwise.
- `account`: string \| null. `characters`: map of character name → notes, only for that account's characters that have notes.
- Proxy behavior: the notes never hold or delay the login. The proxy forwards the rewritten packet first, then shows the notes in its always-on-top popup window (the same one `show_modal` uses with `always_on_top`) until the user acknowledges it, on every login with notes. EQ login is per account and the character is picked later on the world server, so the proxy shows the account note plus all character notes, highlighting the typed name when it is a character. A malformed `notes` value is ignored and the login proceeds.
- Older proxies ignore the field.

Failure:
```json
{
  "type": "login_auth_response",
  "request_id": "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f",
  "error": "Authentication failed",
  "status": 401
}
```

A request without a non-empty string `request_id` gets **no reply**: a response must carry one (schema) and could not be matched without it. **[reference]** logs a warning and drops the request. The proxy always sends a UUID, so it never hits this.

Proxy resolution: the response is matched to the pending request by `request_id` (an unknown `request_id` is dropped). If `error` is present, the login fails with that string; otherwise the proxy Base64-decodes `encrypted_credentials` (empty or invalid → no credentials) and takes `real_user`. **`status` is ignored by the proxy** but SHOULD be set for other clients.

| `status` **[reference]** | `error` string | When |
|---|---|---|
| 400 | `Character not found` | Username does not resolve to any account |
| 400 | `Missing request_id or username` | `username` missing or empty |
| 401 | `Authentication failed` | Resolved account not accessible to the key, or SSO disabled for the guild since connect. Deliberately generic. |
| 410 | `Tag is empty (possibly temporarily, due to inactivity requirements)` | Tag or dynamic tag matched only active accounts (or none, for dynamic tags) |
| 500 | `Internal server error` | Unexpected server error |

**[reference]** on success: `last_login` / `last_login_by` updated, an audit row written, and an immediate `delta` pushed to all clients of the guild. Failures other than "not found" and empty tags are audited.

### 5.5 Credential crypto **[proxy-required]**

| Param | Value |
|---|---|
| Plaintext | `real_user + "\0" + real_pass + "\0"` (UTF-8 bytes) |
| Padding | Append `\0` up to a multiple of 8 |
| Cipher | DES-CBC |
| Key | 8 zero bytes |
| IV | 8 zero bytes |
| Encoding | Standard Base64 of the ciphertext |

**Test vector:**
`real_user=realbot01`, `real_pass=secret` →
`encrypted_credentials = "qqIv/3uQ7ssYIp1Nv6kGw5uiXJoY4ou/"`

The proxy **splices** the decoded bytes into the SOE Login packet; it does not re-encrypt. Wrong crypto means the EQ login server rejects the password. **[reference]** encrypts with `cryptography` `TripleDES` using the 8-byte zero key, which is equivalent to single DES.

**MUST NOT** put plaintext `real_pass` on the WebSocket.

### 5.6 Telemetry (C→S)

General rules for every telemetry message:
- No reply, ever. Bad input MUST NOT close the connection.
- **[reference]** refuses a WebSocket frame larger than **1114112** bytes (about 1.06 MiB) before parsing. That fits an `update_inventory` whose 512 KiB export can double when tabs and newlines are JSON-escaped, plus the envelope. The proxy itself never sends an inventory file over 524288 bytes or a spellbook file over 131072 bytes.
- A missing, unknown or inaccessible `character_name` MUST be ignored silently (no error, no close). The proxy sends `heartbeat`, `update_location`, `update_inventory`, `update_spellbook` and `faction_hits` only for characters in its SSO cache, but the cache can be stale.
- **[reference]** access: the connected user must be able to use the character's account (same check as `login_auth`).

#### `heartbeat`

```json
{"type": "heartbeat", "character_name": "Zzzz"}
```

- Proxy: every **20s** for the SSO character of the newest EQ log, only while that log was modified within the last **30s** and belongs to one of the backend's own servers (`proxy_core::sso_report_servers`).
- **[reference]** updates `last_login` / `last_login_by`, creates or extends a session (which drives `active_character`), expires the same user's sessions on other accounts, and schedules a debounced `delta`.

#### `update_location`

```json
{
  "type": "update_location",
  "character_name": "Zzzz",
  "park_location": "veeshan",
  "bind_location": "tox",
  "level": 60,
  "items": { "seb": true, "vp": false }
}
```

| Field | Type | Notes |
|---|---|---|
| `park_location` / `bind_location` | zone key string, optional | The proxy maps EQ zone names to short keys (`veeshan`, `tox`, `kael`, ...), falling back to the lowercased zone name |
| `level` | int, optional | |
| `items` | object, optional | Partial update of the `items` wire keys (§5.2), for example a key looted from a log line. Older clients sent their whole parsed inventory here. |
| `keys` | object, optional | Legacy `seb` / `vp` / `st`. **[reference]** merges with `items`; `items` wins on conflict. |

- Proxy: sends only fields it has, never blank strings or empty `items`, and skips a message that would not change what it last sent for that character on this connection.
- **[reference]** counts as a heartbeat (same side effects), then updates only valid fields that are present. A missing field, `null`, or an invalid value leaves the stored value unchanged: a location must be a non-blank string of at most 64 characters, `level` an integer 1–255 (a boolean is not a level), key and flag items booleans, and count items integers 0–100000. A boolean sent for a count key becomes 1 or 0. Parking in a key zone can also mark the matching key. A `delta` is scheduled whenever the character was found and accessible.

#### `update_inventory`

```json
{
  "type": "update_inventory",
  "character_name": "Zzzz",
  "inventory": "Location\tName\tID\tCount\tSlots\nPrimary\tTrakanon Idol\t1\t1\t5\n"
}
```

- `inventory` is the raw `<Char>-Inventory.txt` export (`/outputfile inventory`): tab-separated, with a header row that has a `Name` column (`Count` is summed for stackable items).
- Proxy: sends the whole file whenever it changes, for SSO characters only, and skips an identical resend on the same connection. It does not send blank files or files over 524288 bytes. Files saved under a custom name are ignored.
- **[reference]** parses it into the `items` wire keys (§5.2) as a **full snapshot**: tracked items missing from the file become `false` / `0`. The server decides which items it tracks, so recognition can change without a client release.
- **[reference]** size cap and rejection: blank text, text over **524288 bytes** (UTF-8), or text with no `Name` column is ignored and stored items stay unchanged.
- **[reference]** does **not** count as a heartbeat. Schedules a `delta` only when a stored column changed.

#### `update_spellbook`

```json
{
  "type": "update_spellbook",
  "character_name": "Zzzz",
  "spellbook": "44\tShock of Swords\n4\tGate\n12\tBind Affinity\n"
}
```

- `spellbook` is the raw `<Char>-Spellbook.txt` export (`/outputfile spellbook`): one `<level><TAB><spell name>` line per scribed spell, unsorted, no header, no spell IDs. Accept any whitespace in place of the tab.
- Proxy: sends the whole file whenever it changes, for SSO characters only, and skips an identical resend on the same connection. It does not send blank files or files over 131072 bytes, and never parses spellbooks locally.
- **[reference]** size caps and rejection: the whole message is ignored, keeping the stored spellbook, when the text is blank, over **131072 bytes** (UTF-8), has any non-blank line that is not `<level> <name>` with a level of 1–255 (at most 3 digits), has a spell name over **255** characters, or has more than **1000** distinct spells.
- **[reference]** replaces the character's stored spells with the parsed set (a repeated name keeps its first level) and records when the spellbook was updated.
- **Store-only**: spells are not in `account_tree`, so no `delta`. Does not count as a heartbeat.

#### `fte` and `mob_death`

```json
{"type": "fte", "mob": "Cekenar", "player": "Toald", "character_name": "Zzzz", "eq_log_time": "Fri Jan 31 22:04:02 2025"}
{"type": "mob_death", "mob": "King Tormax", "eq_log_time": "Sat Feb 15 20:52:45 2025", "character_name": "Zzzz"}
```

- `eq_log_time`: EQ log bracket form `Wed Jul 15 22:14:05 2026`.
- `fte` comes from `<mob> engages <player>!` lines; `mob_death` from `You have slain <mob>!` / `<mob> has been slain by ...` lines for mobs on the proxy's raid target list. The proxy may send these for local-only characters.
- **[reference]** all string fields are trimmed and must be non-empty. `character_name` is logged but **not** access-checked, so local-only characters can report; instead the connected user must have access to at least one SSO character in the guild.
- **[reference]** `mob`, `player` and `character_name` are cleaned before the Discord post: control and invisible characters are dropped, whitespace (including newlines) collapses to single spaces, and a name longer than 64 characters, or a value that is not a string, drops the message. The post is sent with mentions disabled, so a name cannot ping `@everyone`, a role or a user.
- **[reference]** clock skew: reject when the parsed log time is more than 24h from the server clock; otherwise ignore date and hour (client timezone is unknown) and require minute+second within 60s of the server's, measured around the hour.
- **[reference]** duplicates per mob are dropped, then the report goes to the guild's Discord TOD channel. Never in `full_state` or `delta`.

#### `faction_hits`

```json
{"type": "faction_hits", "character_name": "Zzzz", "eq_log_time": "Sat Nov 21 09:55:01 2026",
 "hits": [{"faction": "Coldain", "direction": "better"}, {"faction": "Claws of Veeshan", "direction": "max"}]}
```

| Field | Type | Notes |
|---|---|---|
| `character_name` | string | Character whose log produced the lines |
| `eq_log_time` | string | Bracket timestamp shared by the lines |
| `hits` | array, 1–50 items | `{faction, direction}`. `faction` is the log text verbatim. `direction`: `better` / `worse` (`Your faction standing with <faction> got better|worse.`) or `max` / `min` (`... could not possibly get any better|worse.`, the faction is capped). P99 logs no amount. |

- Proxy: one message per character per EQ log second (a kill or turn-in logs all its lines in one second), sent 1s after the last line or as soon as a line from another second or character arrives; at most 50 hits, larger bursts split. Newest log only, SSO characters on the backend's own servers only, nothing queued while disconnected.
- **Optional.** A backend MAY store the hits or ignore the message. Ignoring it does not affect login, the account tree or `delta`, and the proxy does not retry or expect a reply. roboToald ignores `faction_hits` (same as any unknown `type`) and stores no faction data.
- The schema still describes a server that reads at most 50 hits and skips an empty or over-255-character `faction`. That text describes an earlier roboToald handler. It is not current roboToald behavior, and this guide does not require it of a backend that chooses to store hits.

### 5.7 `show_modal` (S→C)

A generic popup the server can send at any time after `full_state`, independent of any request. Use it for anything the user should see: maintenance notices, warnings, policy messages.

```json
{
  "type": "show_modal",
  "id": "maintenance-2026-11-22",
  "title": "Server maintenance",
  "message": "The SSO server restarts at 9pm Eastern for about 5 minutes.",
  "level": "warning",
  "always_on_top": true
}
```

| Field | Type | Notes |
|---|---|---|
| `title` | string | Popup title |
| `message` | string | Plain text; line breaks are kept. Clients MUST NOT render markup. |
| `level` | `info` \| `warning` \| `error`, optional | Icon and styling. Default `info`; unknown values are treated as `info`. |
| `always_on_top` | bool, optional | `true`: a separate window that stays above other windows (including EQ in windowed mode) until acknowledged, queued with other topmost popups. `false` (default): a dialog inside the proxy window. |
| `id` | string, optional | A popup whose `id` matches one the client still has pending is dropped, so a repeated send does not stack. |

- Proxy behavior: every popup goes through one handler (`present_modal` in `src-tauri/src/modals.rs`): `show_modal`, login notes, and the proxy's own popups (rejected login, connection error, Rustle UI warning). A message with neither title nor message is ignored; a missing title gets a default for its level. The schema lists `title` and `message` as required; the proxy accepts either or both missing (§4.3). Older proxies ignore the message type.
- Existing responses are unchanged: login notes still come in `login_auth_response.notes`, and rejections still use `login_auth_response.error` and the `error` message. A backend does not need to send `show_modal` for those; the proxy already shows them.
- **[reference]** roboToald does not send `show_modal` yet.

### 5.8 Keepalive and error

```json
{"type": "ping"}
{"type": "pong"}
{"type": "error", "detail": "Access revoked"}
```

- Server `ping` every ~30s; the proxy replies `pong`. A client `ping` gets a server `pong`.
- `error` is sent immediately before an auth-phase close. The proxy reads `detail` (also accepting `message`, `reason` or `error`, and the `auth_failed` / `close` type names). A missing `detail` still parks the proxy, with the text "authentication failed". The schema requires `detail` on `error` (§4.3), so a schema-checked backend MUST set it. If the close frame wins the race, the proxy shows the close reason instead.

### 5.9 HTTP `POST /auth` **[reference]** / older clients

```
POST /auth
Content-Type: application/json
X-Client-Version: 1.4.5
```

```json
{"username": "mytag", "password": "<access_key>", "client_settings": {"log_enabled": true}}
```

`password` is the access key, not an EQ password. `X-Client-Version` (optional; missing compares as `0.0.0`) and `client_settings` have the same semantics as the WS `auth` message.

Processing order **[reference]**: IP rate limit → access key lookup → SSO enabled for the guild → revocation → client version → client settings → username resolution (§7) → access check → success.

| Status | Body |
|---|---|
| 200 | `{"real_user":"...","real_pass":"..."}` plaintext |
| 400 | `{"detail":"Character not found"}` |
| 401 | `{"detail":"Authentication failed"}` for a bad key, rate limit, revocation, SSO disabled or no access; identical body for all |
| 410 | `{"detail":"Tag is empty (possibly temporarily, due to inactivity requirements)"}` |
| 422 | `{"detail":"<reason>"}` client version too old or client settings rejected |

Side effects on success match `login_auth`.

### 5.10 `GET /`

```json
{"status": "ok", "service": "RoboToald API", "message": "API server is running"}
```

**[reference]** returns `"status": "warning"` while the Discord client is not ready.

---

## 6. Auth model

### Access key
Opaque secret. The proxy sends it as WS `auth.access_key`; older clients send it as HTTP `password`. Not a cookie or JWT. **[reference]** keys are random multi-word passphrases bound to one Discord user in one guild.

### WS session
After `auth`, the connection is bound to the key's identity. Later messages do not resend the key. **[reference]** re-checks guild `enable_sso` on each `login_auth`.

### Close codes **[reference]** (send `error` with the same `detail`, then close)

| Code | `detail` | Meaning |
|---|---|---|
| 4001 | `Auth timeout or bad payload` | No message within 15s, or the first message is not JSON |
| 4002 | `Expected auth message` | First message not `auth` with a non-empty `access_key` |
| 4003 | `Invalid access key` | Unknown key, or the IP is rate limited (same text on purpose) |
| 4003 | `Access revoked` | User's access revoked |
| 4003 | `Authentication failed` | SSO disabled for the guild |
| 4004 | `Server still initializing, try again shortly` | Discord not ready after ~30s |
| 4010 | guild `client_update_message` or `Client update required (minimum version: X)` | Client version below the guild minimum |
| 4011 | policy text | `client_settings` rejected (`require_log`, `block_rustle`) |

The proxy treats any `error` message or close code 4000–4099 as a terminal rejection and parks (§2).

### Rate limit **[reference]**
- Failed auth attempts per IP within a rolling window (defaults: 10 attempts per 30 minutes). Response is the normal auth failure (WS 4003 / HTTP 401), **not** 429.
- HTTP uses the first `X-Forwarded-For` hop when present; WS uses the TCP peer only.

---

## 7. Username resolution **[reference]** (required for tag UX)

Order (case-insensitive):

1. Account `real_user`
2. Character name
3. Alias
4. Static tag: on the login path only inactive accounts qualify; if none, 410
5. Dynamic tag `<zone_prefix><class_suffix>` (§7.1); if no inactive match, 410

No match → 400 `Character not found`.

**Inactivity:** an account is inactive when its `last_login` is older than `inactivity_seconds` (default **62**). Heartbeats every 20s keep an in-use account active.

**Tag pick order:** among inactive candidates, compute `bucket = age_seconds // 30` if the last login was under 20 minutes ago, else a constant (all equal). Sort by `(-bucket, -max_character_level)` and pick the first: oldest recent login first, highest level as tiebreaker.

### 7.1 Dynamic tags

Dynamic tags are not stored. They are every zone prefix × class suffix, matched against characters of that class whose `park` or `bind` is in the prefix's zone keys, on inactive accounts.

| Prefix | Zone keys |
|---|---|
| `seb`, `trak` | `sebilis`, `trakanon` |
| `vp` | `veeshan`, `skyfire` |
| `st` | `sleeper`, `eastwastes` |
| `tov` | `templeveeshan`, `westwastes` |
| `dn`, `zlandi` | `necropolis`, `westwastes` |
| `kael` | `kael`, `wakening` |
| `pog` | `growthplane`, `wakening` |
| `thurg`, `dain` | `thurgadina`, `thurgadinb` |
| `ss`, `yeli` | `skyshrine` |
| `fear` | `fearplane`, `feerrott` |
| `vox` | `everfrost`, `permafrost` |
| `naggy` | `lavastorm`, `soldungb` |

| Suffixes | Class |
|---|---|
| `bar`, `brd`, `bard` | Bard |
| `clr`, `cle`, `cleric` | Cleric |
| `dru`, `druid` | Druid |
| `enc`, `enchanter` | Enchanter |
| `mag`, `mage`, `magician` | Magician |
| `mnk`, `mon`, `monk` | Monk |
| `nec`, `necro`, `necromancer` | Necromancer |
| `pal`, `pld`, `paladin` | Paladin |
| `ran`, `rng`, `ranger` | Ranger |
| `rog`, `rogue` | Rogue |
| `sk`, `shadowknight` | ShadowKnight |
| `sha`, `shm`, `sham`, `shaman` | Shaman |
| `war`, `warrior` | Warrior |
| `wiz`, `wizard` | Wizard |

Example: `vpclr` = a Cleric parked or bound in Veeshan's Peak or Skyfire Mountains. Send the prefixes and suffixes as `dynamic_tag_zones` / `dynamic_tag_classes` in `full_state` so the proxy can gate them.

Optional **[reference]** `require_keys_for_dynamic_tags`: `seb`/`trak`, `vp` and `st` additionally require the matching key item to be `true`.

### RBAC outcome **[proxy-required]**
`account_tree` and deltas **MUST** only include accounts the access key may use, and `login_auth` MUST refuse other accounts (401, generic text).
**[reference]** access comes from a Discord role mapped to one of the account's groups, ownership, a direct share, or an admin role.

---

## 8. Proxy SSO gating (failure modes implementers miss)

The proxy lowercases the EQ login username, then decides (`crates/proxy-core/src/decision.rs`):

1. `proxy_only` set → pass through.
2. Username in `skip_sso_accounts` → pass through.
3. Username is a local account or alias, or a local character whose account is known → rewrite with the **local** credentials (no backend call).
4. Username not in the SSO name cache → pass through.
5. Token set and username in the SSO name cache → `login_auth`.

The SSO name cache is built from `full_state` and kept current by `delta`:
- account map keys, aliases, tags and character names, all lowercased;
- every `dynamic_tag_zones` × `dynamic_tag_classes` concatenation (kept across deltas; rebuilt only on the next `full_state`).

### Hard facts
1. Names the backend cannot resolve case-insensitively will gate but fail. **[reference]** stores `real_user` lowercased; backends SHOULD do the same, because the legacy Python proxy matched account keys as-is.
2. A dynamic tag only gates if both lists are sent in `full_state`. The legacy Python proxy dropped dynamic tags from its cache after the first `delta`; this proxy does not.
3. Before `full_state`, or after a disconnect, the cache is empty: no SSO rewrite (pass through).
4. On `login_auth` failure or timeout (`sso_timeout`, default 10s) the proxy forwards the **original, unmodified** Login packet. It splices only when the response carries both `real_user` and decodable, non-empty `encrypted_credentials`; there is no partial rewrite.
5. After a spliced login, if the login server rejects the password, the proxy may retry once with the client's original credentials (the backend is not involved).

---

## 9. Happy paths (minimal)

### A. Connect
1. Proxy opens the WS and sends `auth`.
2. Server validates and sends `full_state`.
3. Proxy marks itself connected and builds the name cache.

### B. Login
1. EQ Login packet reaches the proxy.
2. If gated: `login_auth{username}`.
3. Server resolves and authorizes, then replies `login_auth_response` with ciphertext (and `notes` when the account has any).
4. Proxy splices the ciphertext and forwards to EQEmu, then shows any notes.

### C. Play telemetry
1. `heartbeat` / `update_location` while playing; `update_inventory` / `update_spellbook` when the player runs `/outputfile inventory` / `/outputfile spellbook`; `faction_hits`, `fte`, `mob_death` from log lines.
2. Server updates state; heartbeat, location and inventory changes reach clients as `delta`.

---

## 10. Security MUST / MUST NOT

**MUST**
- Send only ciphertext credentials on the WS.
- Use generic denial text for key, RBAC and rate-limit failures.
- Filter trees and deltas to authorized accounts.
- Set `error.detail` before an auth close.
- Treat notes as plain text.

**MUST NOT**
- Require the EQ client password for resolution.
- Send a plaintext password on the WS.
- Change DES key, IV or padding without a coordinated proxy release.
- Close the WS on bad telemetry or an unknown `type`.
- Depend on cookies for the proxy API.

---

## 11. Compatibility matrix

| Capability | Proxy-required | Reference-only |
|---|---|---|
| `WS /ws/accounts` + `auth` + `full_state` | ✓ | |
| DES `login_auth_response` | ✓ | |
| `delta` add/remove/update | ✓ for live UI and names | |
| App `ping`/`pong` | ✓ (proxy replies; server ping recommended) | 30s loop |
| `heartbeat` / `update_location` | ✓ tolerate | persist + delta |
| `login_auth_response.notes` | ignore OK | notes window |
| `update_inventory` | ignore OK | parse + persist + delta |
| `update_spellbook` | ignore OK | parse + replace stored spells (no delta) |
| `faction_hits` | ignore OK | optional to store (no delta); roboToald ignores it |
| `fte` / `mob_death` | ignore OK | Discord TOD channel |
| `show_modal` | optional to send | not sent yet |
| `POST /auth` | | ✓ |
| Discord RBAC / revocation / audit | | ✓ (wire outcomes still required) |
| Legacy character `keys` | ignore OK | emitted for old clients |
| Close codes 4001–4011 | | ✓ (proxy only needs `error` + close) |

---

## 12. Verification (how to prove compatibility)

1. **Schema:** every fixture under `schemas/fixtures/**` validates against `schemas/ws-protocol.schema.json`. In this repo, `cargo test -p runtime --test ws_contract` also checks that each inbound fixture deserializes and each outbound message serializes to its fixture. A backend SHOULD validate its own live `full_state` / `delta` output against the schema (roboToald: `tests/test_ws_protocol_schema.py`).
2. **Crypto unit:** encrypt `realbot01` / `secret` → Base64 MUST equal `qqIv/3uQ7ssYIp1Nv6kGw5uiXJoY4ou/`. Decrypt with DES-CBC zeros → same plaintext.
3. **WS smoke:**
   - Connect, send nothing for 15s → `error` + close 4001.
   - Bad key → `error.detail` + close 4003.
   - Good key → `full_state` with lowercase account keys and both dynamic tag lists.
   - `login_auth` → success ciphertext is spliceable; unknown user → `error` + 400; denied → 401; empty tag → 410.
   - Server `ping` → client `pong`; client `ping` → server `pong`.
   - Unknown `type`, malformed telemetry and oversized exports → connection stays open.
4. **Proxy smoke:** point the proxy's `sso_api` at the backend, set the token, confirm the UI shows connected with the account count, log in with an alias or tag, and confirm the `SSO auth rewrite` log line.
5. **Delta:** add or remove an account via the backend's admin path; the proxy cache and UI update without reconnecting.
6. **Negative:** stop the backend → proxy cache clears → SSO stops until reconnect.

---

## 13. Open questions (unresolved from code alone)

| ID | Fact |
|---|---|
| Q1 | No protocol version field. Compatibility is additive JSON plus `client_version` / guild minimum version only. |
| Q2 | `owned`/`shared` are not field-diffed; ownership flips may not reach clients until another field changes or they reconnect. |
| Q3 | The proxy does not validate messages against the schema at runtime; CI in this repo checks its typed messages against the fixtures and schema, and roboToald checks its live output against them from a checkout of this repo (`rust` branch in its CI). |
| Q4 | Rate-limit defaults (10 per 30 min) are deployment config and may be overridden. |
| Q5 | HTTP `X-Forwarded-For` trust depends on the deployment's reverse proxy configuration. |
| Q6 | Guild multi-tenancy, Discord readiness (4004) and audit retention are reference architecture; a single-tenant backend MAY stub them (for example, never send 4004) if it still speaks the wire. |
| Q7 | Non-ASCII usernames and passwords in the DES plaintext are encoded as UTF-8; stick to ASCII for EQ accounts. |

---

## 14. Source map

| Topic | Path |
|---|---|
| Schema (normative wire) | `schemas/ws-protocol.schema.json` (this repo) |
| Fixtures | `schemas/fixtures/` (this repo) |
| Schema index | `schemas/README.md` (this repo) |
| This guide | `docs/backend-protocol.md` (this repo) |
| Contract tests | `crates/runtime/tests/ws_contract.rs` |
| Proxy WS client, message types | `crates/runtime/src/websocket.rs` |
| Popup handling (`show_modal`, login notes, local errors) | `src-tauri/src/modals.rs`, `src/app/SystemDialogs.tsx`, `src/features/modals/` |
| Name cache, delta apply | `crates/proxy-core/src/accounts_cache.rs` |
| SSO gate | `crates/proxy-core/src/decision.rs` |
| Splice, retry | `crates/runtime/src/proxy.rs`, `crates/protocol/src/retry.rs` |
| Log-driven telemetry, faction batching | `crates/runtime/src/log_watcher.rs`, `crates/proxy-core/src/logs.rs` |
| Inventory / spellbook export sends | `crates/runtime/src/inventory_watcher.rs`, `crates/proxy-core/src/spellbook_export.rs` |
| Reference WS + HTTP handlers | roboToald `roboToald/api/server.py` |
| Reference account tree / deltas | roboToald `roboToald/api/websocket.py` |
| Reference resolution / items map / storage | roboToald `roboToald/db/models/sso.py` |
| Reference export parsers | roboToald `roboToald/inventory_parser.py`, `roboToald/spellbook_parser.py` |
| Reference deployment and operations | roboToald `README_API.md` |
