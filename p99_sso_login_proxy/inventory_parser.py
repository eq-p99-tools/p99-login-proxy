"""Parse EQ ``*-Inventory.txt`` tab dumps for zone keys and tracked inventory items."""

from __future__ import annotations

import csv
import glob
import logging
import os
import re

logger = logging.getLogger(__name__)

# EQ item Name column -> WebSocket ``items`` wire key (matches server WIRE_KEY_TO_ATTR)
INVENTORY_TRACKED_ITEMS = {
    "Trakanon Idol": "seb",
    "Key of Veeshan": "vp",
    "Sleeper's Key": "st",
    "Box of the Void": "void",
    "Necklace of Resolution": "neck",
    "Vial of Velium Vapors": "thurg",
    "Reaper of the Dead": "reaper",
    "Shiny Brass Idol": "brass_idol",
}

# Stackable items: sum ``Count`` for every row with this Name -> wire key (integer on the wire).
INVENTORY_COUNTED_ITEMS = {
    "Lizard Blood Potion": "lizard",
    "Pearl": "pearl",
    "Peridot": "peridot",
    "Mana Battery - Class Three": "mb3",
    "Mana Battery - Class Four": "mb4",
    "Mana Battery - Class Five": "mb5",
}

ALL_INVENTORY_WIRE_KEYS: tuple[str, ...] = tuple(
    sorted(set(INVENTORY_TRACKED_ITEMS.values()) | set(INVENTORY_COUNTED_ITEMS.values()))
)


def _default_inventory_result() -> dict[str, bool | int]:
    result: dict[str, bool | int] = {w: False for w in INVENTORY_TRACKED_ITEMS.values()}
    result.update({w: 0 for w in INVENTORY_COUNTED_ITEMS.values()})
    return result


def character_name_from_inventory_path(path: str) -> str:
    """Extract character name from ``Charname-Inventory.txt`` basename."""
    base = os.path.basename(path)
    m = re.match(r"^(.+)-Inventory\.txt$", base, re.IGNORECASE)
    return m.group(1) if m else ""


def find_inventory_files(eq_dir: str) -> list[str]:
    """Return paths to ``*-Inventory.txt`` in the EQ install directory."""
    pattern = os.path.join(eq_dir, "*-Inventory.txt")
    return sorted(glob.glob(pattern))


def parse_inventory_file(path: str) -> dict[str, bool | int]:
    """Read a tab-delimited inventory dump.

    Returns a map of wire keys: booleans (``True`` if the item appears in any row) and
    integers (total ``Count`` summed across rows for stack-tracked names).
    """
    result = _default_inventory_result()
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter="\t")
            header = next(reader, None)
            if not header:
                return result
            try:
                name_idx = header.index("Name")
            except ValueError:
                logger.warning("Inventory file missing Name column: %s", path)
                return result
            try:
                count_idx = header.index("Count")
            except ValueError:
                count_idx = None
                logger.warning("Inventory file missing Count column (stack totals will be 0): %s", path)
            for row in reader:
                if len(row) <= name_idx:
                    continue
                cell = row[name_idx].strip()
                wire_bool = INVENTORY_TRACKED_ITEMS.get(cell)
                if wire_bool:
                    result[wire_bool] = True
                wire_count = INVENTORY_COUNTED_ITEMS.get(cell)
                if wire_count is not None and count_idx is not None and len(row) > count_idx:
                    raw = row[count_idx].strip()
                    try:
                        add = int(raw) if raw else 0
                    except ValueError:
                        add = 0
                    result[wire_count] = int(result[wire_count]) + add
    except OSError:
        logger.exception("Failed to read inventory file: %s", path)
    return result
