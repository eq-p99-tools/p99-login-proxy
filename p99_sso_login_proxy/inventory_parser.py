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
    "Lizard Blood Potion": "lizard",
    "Vial of Velium Vapors": "thurg",
}

# Default parse result: all wires False until a matching Name is seen.
_DEFAULT_ITEM_FLAGS = {w: False for w in INVENTORY_TRACKED_ITEMS.values()}


def character_name_from_inventory_path(path: str) -> str:
    """Extract character name from ``Charname-Inventory.txt`` basename."""
    base = os.path.basename(path)
    m = re.match(r"^(.+)-Inventory\.txt$", base, re.IGNORECASE)
    return m.group(1) if m else ""


def find_inventory_files(eq_dir: str) -> list[str]:
    """Return paths to ``*-Inventory.txt`` in the EQ install directory."""
    pattern = os.path.join(eq_dir, "*-Inventory.txt")
    return sorted(glob.glob(pattern))


def parse_inventory_file(path: str) -> dict[str, bool]:
    """Read a tab-delimited inventory dump; return wire flags (``True`` if the item appears in any row)."""
    result = dict(_DEFAULT_ITEM_FLAGS)
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
            for row in reader:
                if len(row) <= name_idx:
                    continue
                cell = row[name_idx].strip()
                wire = INVENTORY_TRACKED_ITEMS.get(cell)
                if wire:
                    result[wire] = True
    except OSError:
        logger.exception("Failed to read inventory file: %s", path)
    return result
