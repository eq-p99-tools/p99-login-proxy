import { useEffect, useMemo, useState } from "react";

import {
  Button,
  ConfirmDialog,
  DataTable,
  ErrorAlert,
  FormValue,
  LoadingState,
  ModalDialog,
  PasswordField,
  SearchField,
} from "../../components";
import { useDesktopClient } from "../../app/AppProviders";
import { SSO_SUB_TABS, type SsoSubTab } from "../../app/navigation";
import type { LocalCharacter, LocalCharacterInput } from "../../ipc/schemas";
import { LocalCharacterDialog } from "./LocalCharacterDialog";
import {
  flattenLocalCharacters,
  searchLocalCharacters,
  sortLocalCharacters,
  type LocalCharacterRow,
  type LocalCharacterSortKey,
} from "./localCharacterRoster";
import {
  flattenCharacters,
  normalizeAccountTree,
  searchCharacters,
  sortCharacters,
  sortLocalAccounts,
  ssoAccountsSummary,
  type AccountTree,
  type CharacterRow,
  type CharacterSortKey,
  type LocalAccountSortKey,
} from "./roster";
import {
  CHARACTER_HEADER_TOOLTIPS,
  LOCAL_ACCOUNT_WIDTHS,
  LOCAL_CHARACTER_GROUP_HEADER,
  LOCAL_CHARACTER_WIDTHS,
  SSO_ACCOUNT_WIDTHS,
  SSO_ALIAS_WIDTHS,
  SSO_CHARACTER_GROUP_HEADER,
  SSO_CHARACTER_HEADER_TOOLTIPS,
  SSO_CHARACTER_WIDTHS,
  SSO_TAG_WIDTHS,
} from "./tableConfig";

function localCharacterKey(ch: LocalCharacter): string {
  return ch.server ? `${ch.server}:${ch.name}` : ch.name;
}

function filterRows<T>(rows: T[], search: string, pick: (row: T) => string): T[] {
  const q = search.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((row) => pick(row).toLowerCase().includes(q));
}

function characterRowClass(row: CharacterRow): string | undefined {
  if (row.isBlocked) return "row-blocked";
  if (row.lastLogin) return "row-login";
  return undefined;
}

type SsoAccountSortKey = "name" | "aliases" | "tags" | "roles";
type AliasSortKey = "alias" | "account";
type TagSortKey = "tag" | "accounts";

export function SsoPanel() {
  const client = useDesktopClient();
  const [subTab, setSubTab] = useState<SsoSubTab>("characters");
  const [status, setStatus] = useState<Awaited<ReturnType<typeof client.getSsoStatus>> | null>(null);
  const [tree, setTree] = useState<AccountTree>({});
  const [localData, setLocalData] = useState<Awaited<ReturnType<typeof client.getLocalData>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<CharacterSortKey>("loggedInBy");
  const [sortAsc, setSortAsc] = useState(true);
  const [accountSortKey, setAccountSortKey] = useState<SsoAccountSortKey>("name");
  const [accountSortAsc, setAccountSortAsc] = useState(true);
  const [aliasSortKey, setAliasSortKey] = useState<AliasSortKey>("alias");
  const [aliasSortAsc, setAliasSortAsc] = useState(true);
  const [tagSortKey, setTagSortKey] = useState<TagSortKey>("tag");
  const [tagSortAsc, setTagSortAsc] = useState(true);
  const [localSortKey, setLocalSortKey] = useState<LocalCharacterSortKey>("class");
  const [localSortAsc, setLocalSortAsc] = useState(true);
  const [localAccountSortKey, setLocalAccountSortKey] = useState<LocalAccountSortKey>("name");
  const [localAccountSortAsc, setLocalAccountSortAsc] = useState(true);
  const [selectedLocalAccount, setSelectedLocalAccount] = useState<string | null>(null);
  const [selectedLocalChar, setSelectedLocalChar] = useState<string | null>(null);

  const [accountDialog, setAccountDialog] = useState<"add" | "edit" | null>(null);
  const [editAccountName, setEditAccountName] = useState("");
  const [accountPassword, setAccountPassword] = useState("");
  const [accountAliases, setAccountAliases] = useState("");
  const [deleteAccount, setDeleteAccount] = useState<string | null>(null);

  const [accountsStale, setAccountsStale] = useState(false);

  const [charDialog, setCharDialog] = useState<"add" | "edit" | null>(null);
  const [editingChar, setEditingChar] = useState<LocalCharacter | null>(null);
  const [deleteChar, setDeleteChar] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [s, accounts, local] = await Promise.all([
        client.getSsoStatus(),
        client.getSsoAccounts(),
        client.getLocalData(),
      ]);
      setStatus(s);
      setTree(normalizeAccountTree(accounts.account_tree));
      setAccountsStale(accounts.stale);
      setLocalData(local);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(id);
  }, [client]);

  const characters = useMemo(() => {
    const rows = flattenCharacters(tree);
    const filtered = search ? searchCharacters(rows, search) : rows;
    return sortCharacters(filtered, { key: sortKey, ascending: sortAsc });
  }, [tree, search, sortKey, sortAsc]);

  const accountRows = useMemo(() => {
    const rows = Object.entries(tree).map(([name, entry]) => ({
      name,
      aliases: (entry.aliases ?? []).join(", "),
      tags: (entry.tags ?? []).join(", "),
      roles: (entry.group_roles ?? []).join(", "),
    }));
    const filtered = filterRows(rows, search, (r) => `${r.name} ${r.aliases} ${r.tags} ${r.roles}`);
    return filtered.sort((a, b) => {
      const comparison =
        a[accountSortKey].localeCompare(b[accountSortKey], undefined, { sensitivity: "base" }) ||
        a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
      return accountSortAsc ? comparison : -comparison;
    });
  }, [tree, search, accountSortKey, accountSortAsc]);

  const aliasRows = useMemo(() => {
    const out: { alias: string; account: string }[] = [];
    for (const [acct, entry] of Object.entries(tree)) {
      for (const alias of entry.aliases ?? []) {
        out.push({ alias, account: acct });
      }
    }
    const filtered = filterRows(out, search, (r) => `${r.alias} ${r.account}`);
    return filtered.sort((a, b) => {
      const comparison =
        a[aliasSortKey].localeCompare(b[aliasSortKey], undefined, { sensitivity: "base" }) ||
        a.alias.localeCompare(b.alias, undefined, { sensitivity: "base" });
      return aliasSortAsc ? comparison : -comparison;
    });
  }, [tree, search, aliasSortKey, aliasSortAsc]);

  const tagRows = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const [acct, entry] of Object.entries(tree)) {
      for (const tag of entry.tags ?? []) {
        const list = map.get(tag) ?? [];
        list.push(acct);
        map.set(tag, list);
      }
    }
    const rows = [...map.entries()].map(([tag, accounts]) => ({ tag, accounts: accounts.join(", ") }));
    const filtered = filterRows(rows, search, (r) => `${r.tag} ${r.accounts}`);
    return filtered.sort((a, b) => {
      const comparison =
        a[tagSortKey].localeCompare(b[tagSortKey], undefined, { sensitivity: "base" }) ||
        a.tag.localeCompare(b.tag, undefined, { sensitivity: "base" });
      return tagSortAsc ? comparison : -comparison;
    });
  }, [tree, search, tagSortKey, tagSortAsc]);

  const allLocalAccountRows = useMemo(() => {
    if (!localData) return [];
    const byUser = new Map<string, { aliases: string[]; password: string }>();
    for (const row of localData.accounts) {
      const entry = byUser.get(row.username) ?? { aliases: [], password: row.password };
      if (row.alias !== row.username) {
        entry.aliases.push(row.alias);
      }
      byUser.set(row.username, entry);
    }
    const rows = [...byUser.entries()].map(([name, { aliases, password }]) => ({
      name,
      password,
      aliases: aliases.join(", "),
    }));
    return rows;
  }, [localData]);

  const localAccountRows = useMemo(() => {
    const filtered = filterRows(allLocalAccountRows, search, (r) => `${r.name} ${r.aliases}`);
    return sortLocalAccounts(filtered, { key: localAccountSortKey, ascending: localAccountSortAsc });
  }, [allLocalAccountRows, search, localAccountSortKey, localAccountSortAsc]);

  const localCharRows = useMemo(() => {
    const rows = flattenLocalCharacters(localData?.characters ?? []);
    const filtered = search ? searchLocalCharacters(rows, search) : rows;
    return sortLocalCharacters(filtered, { key: localSortKey, ascending: localSortAsc });
  }, [localData, search, localSortKey, localSortAsc]);

  const ssoSummary = useMemo(() => ssoAccountsSummary(tree), [tree]);

  const localAccountNames = useMemo(
    () => allLocalAccountRows.map((r) => r.name).sort((a, b) => a.localeCompare(b)),
    [allLocalAccountRows],
  );

  const reconnect = async () => {
    setBusy(true);
    try {
      await client.reloadLocalData();
      await client.reconnectSso();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const openAddAccount = () => {
    setEditAccountName("");
    setAccountPassword("");
    setAccountAliases("");
    setAccountDialog("add");
  };

  const openEditAccount = (name: string) => {
    const row = allLocalAccountRows.find((r) => r.name === name);
    setEditAccountName(name);
    setAccountPassword(row?.password ?? "");
    setAccountAliases(row?.aliases ?? "");
    setAccountDialog("edit");
  };

  const saveLocalAccount = async () => {
    if (!localData) return;
    const name = editAccountName.trim();
    if (!name) {
      setError("Account name is required");
      return;
    }
    if (!accountPassword) {
      setError("Password is required");
      return;
    }
    const aliases = accountAliases
      .split(",")
      .map((a) => a.trim())
      .filter(Boolean);
    const accounts = allLocalAccountRows
      .filter((r) => r.name !== name)
      .map((r) => ({
        name: r.name,
        password: r.password,
        aliases: r.aliases.split(",").map((a) => a.trim()).filter(Boolean),
      }));
    accounts.push({
      name,
      password: accountPassword,
      aliases,
    });
    setBusy(true);
    try {
      await client.saveLocalData(accounts, localData.characters);
      setAccountDialog(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const confirmDeleteAccount = async () => {
    if (!localData || !deleteAccount) return;
    const accounts = allLocalAccountRows
      .filter((r) => r.name !== deleteAccount)
      .map((r) => ({
        name: r.name,
        password: r.password,
        aliases: r.aliases.split(",").map((a) => a.trim()).filter(Boolean),
      }));
    setBusy(true);
    try {
      await client.saveLocalData(accounts, localData.characters, accounts.length === 0);
      setDeleteAccount(null);
      setSelectedLocalAccount(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const openAddCharacter = () => {
    setEditingChar(null);
    setCharDialog("add");
  };

  const openEditCharacter = (key: string) => {
    const row = localData?.characters.find((c) => localCharacterKey(c) === key);
    if (!row) return;
    setEditingChar(row);
    setCharDialog("edit");
  };

  const saveLocalCharacterFromDialog = async (input: LocalCharacterInput) => {
    if (!localData) return;
    const name = input.name.trim();
    if (!name) {
      setError("Character name is required");
      return;
    }
    if (charDialog === "add") {
      const duplicate = localData.characters.some(
        (c) => c.name.toLowerCase() === name.toLowerCase(),
      );
      if (duplicate) {
        setError(`Character "${name}" already exists`);
        return;
      }
    }
    const editKey = editingChar ? localCharacterKey(editingChar) : null;
    const characters = localData.characters
      .filter((c) => (charDialog === "edit" ? localCharacterKey(c) !== editKey : true))
      .map((c) => ({
        name: c.name,
        account_alias: c.account_alias,
        server: c.server,
        class: c.class,
        level: c.level,
        bind: c.bind,
        park: c.park,
        items: c.items ?? {},
      }));
    characters.push({
      name: input.name,
      account_alias: input.account_alias,
      server: input.server ?? "",
      class: input.class ?? null,
      level: input.level ?? null,
      bind: input.bind ?? null,
      park: input.park ?? null,
      items: input.items ?? {},
    });
    setBusy(true);
    try {
      const accounts = allLocalAccountRows.map((r) => ({
        name: r.name,
        password: r.password,
        aliases: r.aliases.split(",").map((a) => a.trim()).filter(Boolean),
      }));
      await client.saveLocalData(accounts, characters);
      setCharDialog(null);
      setEditingChar(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const confirmDeleteCharacter = async () => {
    if (!localData || !deleteChar) return;
    const characters = localData.characters
      .filter((c) => localCharacterKey(c) !== deleteChar)
      .map((c) => ({
        name: c.name,
        account_alias: c.account_alias,
        server: c.server,
        class: c.class,
        level: c.level,
        bind: c.bind,
        park: c.park,
        items: c.items ?? {},
      }));
    setBusy(true);
    try {
      const accounts = allLocalAccountRows.map((r) => ({
        name: r.name,
        password: r.password,
        aliases: r.aliases.split(",").map((a) => a.trim()).filter(Boolean),
      }));
      await client.saveLocalData(accounts, characters);
      setDeleteChar(null);
      setSelectedLocalChar(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleLocalSort = (key: LocalCharacterSortKey) => {
    if (localSortKey === key) {
      setLocalSortAsc((v) => !v);
    } else {
      setLocalSortKey(key);
      setLocalSortAsc(true);
    }
  };

  const toggleLocalAccountSort = (key: LocalAccountSortKey) => {
    if (localAccountSortKey === key) {
      setLocalAccountSortAsc((v) => !v);
    } else {
      setLocalAccountSortKey(key);
      setLocalAccountSortAsc(true);
    }
  };

  const localCharacterColumns = [
    { key: "readiness", header: "✓", headerTitle: CHARACTER_HEADER_TOOLTIPS[0], width: LOCAL_CHARACTER_WIDTHS.readiness, align: "center" as const, sortable: true, render: (r: LocalCharacterRow) => r.readiness, cellTitle: (r: LocalCharacterRow) => r.readinessTooltip },
    { key: "name", header: "Character", headerTitle: CHARACTER_HEADER_TOOLTIPS[1], width: LOCAL_CHARACTER_WIDTHS.name, sortable: true, render: (r: LocalCharacterRow) => r.name },
    { key: "class", header: "Class", headerTitle: CHARACTER_HEADER_TOOLTIPS[2], width: LOCAL_CHARACTER_WIDTHS.class, sortable: true, render: (r: LocalCharacterRow) => r.class },
    { key: "level", header: "Lvl", headerTitle: CHARACTER_HEADER_TOOLTIPS[3], width: LOCAL_CHARACTER_WIDTHS.level, align: "center" as const, sortable: true, render: (r: LocalCharacterRow) => r.level || "" },
    { key: "st", header: "ST", headerTitle: CHARACTER_HEADER_TOOLTIPS[4], width: LOCAL_CHARACTER_WIDTHS.st, align: "center" as const, sortable: true, render: (r: LocalCharacterRow) => r.st },
    { key: "vp", header: "VP", headerTitle: CHARACTER_HEADER_TOOLTIPS[5], width: LOCAL_CHARACTER_WIDTHS.vp, align: "center" as const, sortable: true, render: (r: LocalCharacterRow) => r.vp },
    { key: "seb", header: "Sb", headerTitle: CHARACTER_HEADER_TOOLTIPS[6], width: LOCAL_CHARACTER_WIDTHS.seb, align: "center" as const, sortable: true, render: (r: LocalCharacterRow) => r.seb },
    { key: "ct", header: "CT", headerTitle: CHARACTER_HEADER_TOOLTIPS[7], width: LOCAL_CHARACTER_WIDTHS.ct, align: "center" as const, sortable: true, render: (r: LocalCharacterRow) => r.ct, cellTitle: (r: LocalCharacterRow) => r.ctTooltip },
    { key: "th", header: "Th", headerTitle: CHARACTER_HEADER_TOOLTIPS[8], width: LOCAL_CHARACTER_WIDTHS.th, align: "center" as const, sortable: true, render: (r: LocalCharacterRow) => r.th },
    { key: "ch", header: "CH", headerTitle: CHARACTER_HEADER_TOOLTIPS[9], width: LOCAL_CHARACTER_WIDTHS.ch, align: "center" as const, sortable: true, render: (r: LocalCharacterRow) => r.ch, cellTitle: (r: LocalCharacterRow) => r.chTooltip },
    { key: "park", header: "Park Location", headerTitle: CHARACTER_HEADER_TOOLTIPS[10], width: LOCAL_CHARACTER_WIDTHS.park, sortable: true, render: (r: LocalCharacterRow) => r.park },
    { key: "bind", header: "Bind Location", headerTitle: CHARACTER_HEADER_TOOLTIPS[11], width: LOCAL_CHARACTER_WIDTHS.bind, sortable: true, render: (r: LocalCharacterRow) => r.bind },
    { key: "account", header: "Account Name", headerTitle: CHARACTER_HEADER_TOOLTIPS[12], width: LOCAL_CHARACTER_WIDTHS.account, sortable: true, render: (r: LocalCharacterRow) => r.account },
  ];

  const toggleSort = (key: CharacterSortKey) => {
    if (sortKey === key) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const toggleAccountSort = (key: SsoAccountSortKey) => {
    if (accountSortKey === key) {
      setAccountSortAsc((value) => !value);
    } else {
      setAccountSortKey(key);
      setAccountSortAsc(true);
    }
  };

  const toggleAliasSort = (key: AliasSortKey) => {
    if (aliasSortKey === key) {
      setAliasSortAsc((value) => !value);
    } else {
      setAliasSortKey(key);
      setAliasSortAsc(true);
    }
  };

  const toggleTagSort = (key: TagSortKey) => {
    if (tagSortKey === key) {
      setTagSortAsc((value) => !value);
    } else {
      setTagSortKey(key);
      setTagSortAsc(true);
    }
  };

  const characterColumns = [
    { key: "readiness", header: "✓", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[0], width: SSO_CHARACTER_WIDTHS.readiness, align: "center" as const, sortable: true, render: (r: CharacterRow) => r.readiness, cellTitle: (r: CharacterRow) => r.readinessTooltip },
    { key: "name", header: "Character", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[1], width: SSO_CHARACTER_WIDTHS.name, sortable: true, render: (r: CharacterRow) => r.name },
    { key: "class", header: "Class", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[2], width: SSO_CHARACTER_WIDTHS.class, sortable: true, render: (r: CharacterRow) => r.class },
    { key: "level", header: "Lvl", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[3], width: SSO_CHARACTER_WIDTHS.level, align: "center" as const, sortable: true, render: (r: CharacterRow) => r.level || "" },
    { key: "st", header: "ST", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[4], width: SSO_CHARACTER_WIDTHS.st, align: "center" as const, sortable: true, render: (r: CharacterRow) => r.st },
    { key: "vp", header: "VP", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[5], width: SSO_CHARACTER_WIDTHS.vp, align: "center" as const, sortable: true, render: (r: CharacterRow) => r.vp },
    { key: "seb", header: "Sb", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[6], width: SSO_CHARACTER_WIDTHS.seb, align: "center" as const, sortable: true, render: (r: CharacterRow) => r.seb },
    { key: "ct", header: "CT", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[7], width: SSO_CHARACTER_WIDTHS.ct, align: "center" as const, sortable: true, render: (r: CharacterRow) => r.ct, cellTitle: (r: CharacterRow) => r.ctTooltip },
    { key: "th", header: "Th", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[8], width: SSO_CHARACTER_WIDTHS.th, align: "center" as const, sortable: true, render: (r: CharacterRow) => r.th },
    { key: "ch", header: "CH", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[9], width: SSO_CHARACTER_WIDTHS.ch, align: "center" as const, sortable: true, render: (r: CharacterRow) => r.ch, cellTitle: (r: CharacterRow) => r.chTooltip },
    { key: "park", header: "Park Location", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[10], width: SSO_CHARACTER_WIDTHS.park, sortable: true, render: (r: CharacterRow) => r.park },
    { key: "bind", header: "Bind Location", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[11], width: SSO_CHARACTER_WIDTHS.bind, sortable: true, render: (r: CharacterRow) => r.bind },
    { key: "loggedInBy", header: "Logged In By", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[12], width: SSO_CHARACTER_WIDTHS.loggedInBy, sortable: true, render: (r: CharacterRow) => r.loggedInBy },
    { key: "account", header: "Account Name", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[13], width: SSO_CHARACTER_WIDTHS.account, sortable: true, render: (r: CharacterRow) => r.account },
    { key: "roles", header: "Access Roles", headerTitle: SSO_CHARACTER_HEADER_TOOLTIPS[14], width: SSO_CHARACTER_WIDTHS.roles, sortable: true, render: (r: CharacterRow) => r.roles },
  ];

  const needsSearch =
    subTab === "characters" ||
    subTab === "accounts" ||
    subTab === "aliases" ||
    subTab === "tags" ||
    subTab === "local-accounts" ||
    subTab === "local-characters";

  return (
    <section className="panel sso-panel">
      <nav className="sub-tabs" aria-label="SSO views">
        {SSO_SUB_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={subTab === t.id ? "active" : ""}
            onClick={() => {
              setSubTab(t.id);
              setSearch("");
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="panel-body">
        {accountsStale && !subTab.startsWith("local-") ? (
          <p className="stale-notice" role="status">
            Not connected to the SSO service. Showing the last data received.
          </p>
        ) : null}
        {needsSearch && subTab === "characters" ? (
          <div className="characters-search-row">
            <SearchField value={search} onChange={(e) => setSearch(e.target.value)} />
            <span className="legend-item">
              <span className="legend-swatch login" /> Logged In
            </span>
            <span className="legend-item">
              <span className="legend-swatch blocked" /> Blocked
            </span>
          </div>
        ) : null}
        {needsSearch && subTab !== "characters" ? (
          <SearchField value={search} onChange={(e) => setSearch(e.target.value)} />
        ) : null}

        {subTab === "characters" ? (
          <DataTable<CharacterRow>
            fill
            groupHeader={[...SSO_CHARACTER_GROUP_HEADER]}
            columns={characterColumns}
            rows={characters}
            rowKey={(r) => `${r.account}:${r.name}`}
            rowClassName={characterRowClass}
            sortKey={sortKey}
            sortAsc={sortAsc}
            onSort={(k) => toggleSort(k as CharacterSortKey)}
            emptyMessage="No characters in cache"
          />
        ) : null}

        {subTab === "accounts" ? (
          <DataTable
            fill
            columns={[
              { key: "name", header: "Account Name", width: SSO_ACCOUNT_WIDTHS.name, sortable: true, render: (r) => r.name },
              { key: "aliases", header: "Aliases", width: SSO_ACCOUNT_WIDTHS.aliases, sortable: true, render: (r) => r.aliases },
              { key: "tags", header: "Tags", width: SSO_ACCOUNT_WIDTHS.tags, sortable: true, render: (r) => r.tags },
              {
                key: "roles",
                header: "Access Roles",
                headerTitle: "Discord roles whose SSO groups grant access to this account.",
                width: SSO_ACCOUNT_WIDTHS.roles,
                sortable: true,
                render: (r) => r.roles,
              },
            ]}
            rows={accountRows}
            rowKey={(r) => r.name}
            sortKey={accountSortKey}
            sortAsc={accountSortAsc}
            onSort={(key) => toggleAccountSort(key as SsoAccountSortKey)}
            emptyMessage="No SSO accounts cached"
          />
        ) : null}

        {subTab === "aliases" ? (
          <DataTable
            fill
            columns={[
              { key: "alias", header: "Alias", width: SSO_ALIAS_WIDTHS.alias, sortable: true, render: (r) => r.alias },
              { key: "account", header: "Account Name", width: SSO_ALIAS_WIDTHS.account, sortable: true, render: (r) => r.account },
            ]}
            rows={aliasRows}
            rowKey={(r) => `${r.account}:${r.alias}`}
            sortKey={aliasSortKey}
            sortAsc={aliasSortAsc}
            onSort={(key) => toggleAliasSort(key as AliasSortKey)}
            emptyMessage="No aliases"
          />
        ) : null}

        {subTab === "tags" ? (
          <DataTable
            fill
            columns={[
              { key: "tag", header: "Tag", width: SSO_TAG_WIDTHS.tag, sortable: true, render: (r) => r.tag },
              { key: "accounts", header: "Account Names", width: SSO_TAG_WIDTHS.accounts, sortable: true, render: (r) => r.accounts },
            ]}
            rows={tagRows}
            rowKey={(r) => r.tag}
            sortKey={tagSortKey}
            sortAsc={tagSortAsc}
            onSort={(key) => toggleTagSort(key as TagSortKey)}
            emptyMessage="No tags"
          />
        ) : null}

        {subTab === "local-accounts" ? (
          <>
            <DataTable
              fill
              columns={[
                {
                  key: "name",
                  header: "Account Name",
                  width: LOCAL_ACCOUNT_WIDTHS.name,
                  sortable: true,
                  render: (r) => r.name,
                },
                {
                  key: "aliases",
                  header: "Aliases",
                  width: LOCAL_ACCOUNT_WIDTHS.aliases,
                  sortable: true,
                  render: (r) => r.aliases,
                },
              ]}
              rows={localAccountRows}
              rowKey={(r) => r.name}
              selectedKey={selectedLocalAccount}
              onSelect={(key) => setSelectedLocalAccount(key)}
              sortKey={localAccountSortKey}
              sortAsc={localAccountSortAsc}
              onSort={(k) => toggleLocalAccountSort(k as LocalAccountSortKey)}
              emptyMessage="No local accounts"
            />
            <div className="button-row">
              <Button variant="secondary" onClick={openAddAccount}>
                Add Account
              </Button>
              <Button
                variant="secondary"
                disabled={!selectedLocalAccount}
                onClick={() => selectedLocalAccount && openEditAccount(selectedLocalAccount)}
              >
                Edit Account
              </Button>
              <Button
                variant="secondary"
                disabled={!selectedLocalAccount}
                onClick={() => setDeleteAccount(selectedLocalAccount)}
              >
                Delete Account
              </Button>
            </div>
          </>
        ) : null}

        {subTab === "local-characters" ? (
          <>
            <DataTable<LocalCharacterRow>
              fill
              groupHeader={[...LOCAL_CHARACTER_GROUP_HEADER]}
              columns={localCharacterColumns}
              rows={localCharRows}
              rowKey={(r) => r.rowKey}
              selectedKey={selectedLocalChar}
              onSelect={(key) => setSelectedLocalChar(key)}
              sortKey={localSortKey}
              sortAsc={localSortAsc}
              onSort={(k) => toggleLocalSort(k as LocalCharacterSortKey)}
              emptyMessage="No local characters"
            />
            <div className="button-row">
              <Button variant="secondary" onClick={openAddCharacter}>
                Add Character
              </Button>
              <Button
                variant="secondary"
                disabled={!selectedLocalChar}
                onClick={() => selectedLocalChar && openEditCharacter(selectedLocalChar)}
              >
                Edit Character
              </Button>
              <Button
                variant="secondary"
                disabled={!selectedLocalChar}
                onClick={() => setDeleteChar(selectedLocalChar)}
              >
                Delete Character
              </Button>
            </div>
          </>
        ) : null}

        {error ? <ErrorAlert message={error} /> : null}
        {!status && !error ? <LoadingState /> : null}
      </div>

      <footer className="sso-footer">
        <span className="sso-count">
          <strong>SSO Accounts:</strong>{" "}
          <FormValue tone={ssoSummary.tone}>{ssoSummary.text}</FormValue>
        </span>
        <Button variant="secondary" busy={busy} onClick={() => void reconnect()}>
          Force Reconnect
        </Button>
      </footer>

      <ModalDialog
        title={accountDialog === "add" ? "Add Local Account" : "Edit Local Account"}
        open={accountDialog != null}
        onClose={() => setAccountDialog(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setAccountDialog(null)}>
              Cancel
            </Button>
            <Button variant="secondary" busy={busy} onClick={() => void saveLocalAccount()}>
              Save
            </Button>
          </>
        }
      >
        <label className="form-field">
          <span>Account Name</span>
          <input
            type="text"
            value={editAccountName}
            disabled={accountDialog === "edit"}
            className={accountDialog === "edit" ? "field-locked" : undefined}
            placeholder="myaccount1"
            title={accountDialog === "edit" ? "Account name cannot be changed when editing." : undefined}
            onChange={(e) => setEditAccountName(e.target.value)}
          />
        </label>
        <PasswordField
          label="Password"
          value={accountPassword}
          placeholder="myPassword1"
          onChange={(e) => setAccountPassword(e.target.value)}
        />
        <label className="form-field">
          <span>Aliases (comma-separated)</span>
          <input
            type="text"
            value={accountAliases}
            placeholder="alias1, alias2"
            onChange={(e) => setAccountAliases(e.target.value)}
          />
        </label>
      </ModalDialog>

      <LocalCharacterDialog
        mode={charDialog === "edit" ? "edit" : "add"}
        open={charDialog != null}
        busy={busy}
        initial={editingChar}
        accountNames={localAccountNames}
        onClose={() => {
          setCharDialog(null);
          setEditingChar(null);
        }}
        onSave={(input) => void saveLocalCharacterFromDialog(input)}
      />

      <ConfirmDialog
        open={deleteAccount != null}
        title="Delete local account"
        message={`Delete account "${deleteAccount}"?`}
        confirmLabel="Delete"
        busy={busy}
        onConfirm={() => void confirmDeleteAccount()}
        onCancel={() => setDeleteAccount(null)}
      />

      <ConfirmDialog
        open={deleteChar != null}
        title="Delete local character"
        message={`Delete character "${localData?.characters.find((c) => localCharacterKey(c) === deleteChar)?.name ?? ""}"?`}
        confirmLabel="Delete"
        busy={busy}
        onConfirm={() => void confirmDeleteCharacter()}
        onCancel={() => setDeleteChar(null)}
      />
    </section>
  );
}
