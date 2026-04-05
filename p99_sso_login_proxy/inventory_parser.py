"""Parse EQ ``*-Inventory.txt`` tab dumps for zone key items."""

from __future__ import annotations

import csv
import glob
import logging
import os
import re

logger = logging.getLogger(__name__)

# Item display names in the Name column -> SSOAccountCharacter key columns
INVENTORY_KEY_ITEMS = {
    "Trakanon Idol": "key_seb",
    "Key of Veeshan": "key_vp",
    "Sleeper's Key": "key_st",
}


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
    """Read a tab-delimited inventory dump; return whether each zone key item is present.

    Keys are ``key_seb``, ``key_vp``, ``key_st`` (``True`` if the item appears in any row).
    """
    result = {"key_seb": False, "key_vp": False, "key_st": False}
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
                col = INVENTORY_KEY_ITEMS.get(cell)
                if col:
                    result[col] = True
    except OSError:
        logger.exception("Failed to read inventory file: %s", path)
    return result
