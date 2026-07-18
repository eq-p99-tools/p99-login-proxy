import { useEffect, useId, useMemo, useState } from "react";

import { Button, ModalDialog } from "../../components";
import { tooltipProps } from "../../components/tooltip";
import type { LocalCharacter, LocalCharacterInput } from "../../ipc/schemas";

import { CLASS_CHOICES } from "./classes";
import { zoneKeyToDisplay, zoneSuggestionValues, zoneToZonekey } from "./zoneTranslate";

const BOOL_ITEM_LABELS: Record<string, string> = {
  seb: "Trakanon Idol (Seb key)",
  vp: "Key of Veeshan",
  st: "Sleeper's Key",
  void: "Box of the Void",
  neck: "Necklace of Resolution",
  thurg: "Vial of Velium Vapors",
  reaper: "Reaper of the Dead",
  brass_idol: "Shiny Brass Idol",
};

const COUNT_ITEM_LABELS: Record<string, string> = {
  lizard: "Lizard Blood Potion",
  pearl: "Pearl",
  peridot: "Peridot",
  mb3: "Mana Battery III",
  mb4: "Mana Battery IV",
  mb5: "Mana Battery V",
};

const BOOL_ITEM_KEYS = Object.keys(BOOL_ITEM_LABELS);
const COUNT_ITEM_KEYS = Object.keys(COUNT_ITEM_LABELS);

type Tristate = "yes" | "no" | "unknown";

function itemToTristate(value: unknown): Tristate {
  if (value === true) return "yes";
  if (value === false) return "no";
  return "unknown";
}

function tristateNext(current: Tristate): Tristate {
  if (current === "unknown") return "yes";
  if (current === "yes") return "no";
  return "unknown";
}

function tristateToValue(state: Tristate): boolean | null {
  if (state === "yes") return true;
  if (state === "no") return false;
  return null;
}

interface TristateCheckboxProps {
  id: string;
  label: string;
  value: Tristate;
  onChange: (next: Tristate) => void;
}

function TristateCheckbox({ id, label, value, onChange }: TristateCheckboxProps) {
  const checked = value === "yes";
  const indeterminate = value === "unknown";

  return (
    <label className="tristate-check" htmlFor={id} {...tooltipProps("Tri-state: checked = yes, unchecked = no, partial = unknown")}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        ref={(el) => {
          if (el) {
            el.indeterminate = indeterminate;
          }
        }}
        onChange={() => onChange(tristateNext(value))}
      />
      {label}
    </label>
  );
}

export interface LocalCharacterDialogProps {
  mode: "add" | "edit";
  open: boolean;
  busy?: boolean;
  initial?: LocalCharacter | null;
  accountNames: string[];
  onClose: () => void;
  onSave: (input: LocalCharacterInput) => void;
}

function emptyItems(): Record<string, boolean | number | null> {
  const items: Record<string, boolean | number | null> = {};
  for (const key of [...BOOL_ITEM_KEYS, ...COUNT_ITEM_KEYS]) {
    items[key] = null;
  }
  return items;
}

function itemsFromCharacter(ch: LocalCharacter | null | undefined): Record<string, boolean | number | null> {
  const items = emptyItems();
  if (!ch?.items) {
    return items;
  }
  for (const [key, value] of Object.entries(ch.items)) {
    if (value === null || value === undefined) {
      items[key] = null;
    } else if (typeof value === "boolean" || typeof value === "number") {
      items[key] = value;
    }
  }
  return items;
}

export function LocalCharacterDialog({
  mode,
  open,
  busy = false,
  initial,
  accountNames,
  onClose,
  onSave,
}: LocalCharacterDialogProps) {
  const accountListId = useId();
  const zoneListId = useId();
  const zoneSuggestions = useMemo(() => zoneSuggestionValues(), []);
  const [name, setName] = useState("");
  const [account, setAccount] = useState("");
  const [klass, setKlass] = useState("");
  const [level, setLevel] = useState("");
  const [bind, setBind] = useState("");
  const [park, setPark] = useState("");
  const [itemsOpen, setItemsOpen] = useState(false);
  const [boolItems, setBoolItems] = useState<Record<string, Tristate>>({});
  const [countItems, setCountItems] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) {
      return;
    }
    setName(initial?.name ?? "");
    setAccount(initial?.account_alias ?? "");
    setKlass(initial?.class ?? "");
    setLevel(initial?.level != null ? String(initial.level) : "");
    setBind(initial?.bind ? zoneKeyToDisplay(initial.bind) : "");
    setPark(initial?.park ? zoneKeyToDisplay(initial.park) : "");
    setItemsOpen(false);
    const parsed = itemsFromCharacter(initial);
    const bools: Record<string, Tristate> = {};
    for (const key of BOOL_ITEM_KEYS) {
      bools[key] = itemToTristate(parsed[key]);
    }
    setBoolItems(bools);
    const counts: Record<string, string> = {};
    for (const key of COUNT_ITEM_KEYS) {
      const val = parsed[key];
      counts[key] = typeof val === "number" ? String(val) : "";
    }
    setCountItems(counts);
  }, [open, initial]);

  const handleSave = () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      return;
    }
    const levelNum = level.trim() ? Number.parseInt(level, 10) : null;
    const items: Record<string, boolean | number | null> = {};
    for (const key of BOOL_ITEM_KEYS) {
      items[key] = tristateToValue(boolItems[key] ?? "unknown");
    }
    for (const key of COUNT_ITEM_KEYS) {
      const text = countItems[key]?.trim() ?? "";
      if (!text) {
        items[key] = null;
      } else {
        const n = Number.parseInt(text, 10);
        items[key] = Number.isFinite(n) ? n : null;
      }
    }
    onSave({
      name: mode === "edit" ? (initial?.name ?? trimmedName) : trimmedName,
      account_alias: account.trim().toLowerCase(),
      server: initial?.server ?? "",
      class: klass.trim() || null,
      level: levelNum != null && levelNum > 0 ? levelNum : null,
      bind: bind.trim() ? zoneToZonekey(bind) || null : null,
      park: park.trim() ? zoneToZonekey(park) || null : null,
      items,
    });
  };

  return (
    <ModalDialog
      title={mode === "add" ? "Add Local Character" : "Edit Local Character"}
      open={open}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="secondary" busy={busy} onClick={handleSave}>
            Save
          </Button>
        </>
      }
    >
      <label className="form-field">
        <span>Character Name</span>
        <input
          type="text"
          value={name}
          disabled={mode === "edit"}
          className={mode === "edit" ? "field-locked" : undefined}
          placeholder="CharName"
          {...tooltipProps(mode === "edit" ? "Character name cannot be changed when editing." : undefined)}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label className="form-field">
        <span>Account</span>
        <input
          type="text"
          list={accountListId}
          value={account}
          onChange={(e) => setAccount(e.target.value)}
        />
        <datalist id={accountListId}>
          {accountNames.map((acc) => (
            <option key={acc} value={acc} />
          ))}
        </datalist>
      </label>
      <label className="form-field">
        <span>Class</span>
        <select className="field-select" value={klass} onChange={(e) => setKlass(e.target.value)}>
          <option value=""> </option>
          {CLASS_CHOICES.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      </label>
      <label className="form-field">
        <span>Level</span>
        <input
          type="number"
          min={0}
          max={65}
          value={level}
          placeholder=" "
          onChange={(e) => setLevel(e.target.value)}
        />
      </label>
      <label className="form-field">
        <span>Bind Location</span>
        <input
          type="text"
          list={zoneListId}
          value={bind}
          placeholder="e.g. North Karana or nro"
          onChange={(e) => setBind(e.target.value)}
        />
      </label>
      <label className="form-field">
        <span>Park Location</span>
        <input
          type="text"
          list={zoneListId}
          value={park}
          placeholder="e.g. North Karana or nro"
          onChange={(e) => setPark(e.target.value)}
        />
        <datalist id={zoneListId}>
          {zoneSuggestions.map((zone) => (
            <option key={zone} value={zone} />
          ))}
        </datalist>
      </label>

      <fieldset className="items-fieldset">
        <legend>
          <label className="items-fieldset-toggle">
            <input type="checkbox" checked={itemsOpen} onChange={(e) => setItemsOpen(e.target.checked)} />
            Items (optional — usually populated automatically)
          </label>
        </legend>
        {itemsOpen ? (
          <div className="items-fieldset-body">
            <p className="items-section-label">Keys / Flags</p>
            {BOOL_ITEM_KEYS.map((key) => (
              <TristateCheckbox
                key={key}
                id={`local-item-bool-${key}`}
                label={BOOL_ITEM_LABELS[key] ?? key}
                value={boolItems[key] ?? "unknown"}
                onChange={(next) => setBoolItems((prev) => ({ ...prev, [key]: next }))}
              />
            ))}
            <p className="items-section-label">Stack Counts</p>
            {COUNT_ITEM_KEYS.map((key) => (
              <label key={key} className="form-field count-item-field">
                <span>{COUNT_ITEM_LABELS[key] ?? key}</span>
                <input
                  type="number"
                  min={0}
                  max={999}
                  value={countItems[key] ?? ""}
                  placeholder="unknown"
                  onChange={(e) => setCountItems((prev) => ({ ...prev, [key]: e.target.value }))}
                />
              </label>
            ))}
          </div>
        ) : null}
      </fieldset>
    </ModalDialog>
  );
}
