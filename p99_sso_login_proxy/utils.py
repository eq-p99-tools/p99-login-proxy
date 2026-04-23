import csv
import itertools
import logging
import os
import sys
import time

logger = logging.getLogger("utils")


def find_resource_path(filename):
    """Find a resource file by checking common locations (source dir, PyInstaller bundle, cwd)."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, filename))
    candidates.extend(
        [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", filename),
            os.path.join(os.path.dirname(sys.executable), filename),
            filename,
        ]
    )
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def retry_file_io(func, *, attempts: int = 3, delay_s: float = 0.05):
    """Run *func* and retry on failure (transient locks, slow AV scans). Re-raises the last error."""
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if i < attempts - 1:
                time.sleep(delay_s)
    if last_exc is None:
        raise RuntimeError("retry_file_io: exhausted attempts with no exception")
    raise last_exc


def hex_to_bytes(hex_str):
    return bytes.fromhex(hex_str.replace("\\x", ""))


def load_local_accounts(file_path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    if not os.path.exists(file_path):
        logger.info("No local accounts file found at %s, creating example", file_path)
        try:
            with open(file_path, "w") as f:
                f.write("name,password,aliases\n")
                f.write("exampleaccount1,password_goes_here,examplealias1|examplealias2\n")
        except Exception:
            logger.exception("Failed to create example local accounts file")
    accounts = {}
    all_names = {}
    try:
        with open(file_path) as f:
            reader = csv.reader(f)
            row_num = 0
            for row in reader:
                try:
                    if row_num == 0 and "name" in row[0]:
                        logger.debug("Skipping header row")
                        row_num += 1
                        continue
                    account_name = row[0].strip().lower()
                    accounts[account_name] = {
                        "password": row[1],
                    }
                    all_names[account_name] = account_name
                    if len(row) > 2:
                        accounts[account_name]["aliases"] = [alias.strip().lower() for alias in row[2].split("|")]
                        for alias in accounts[account_name]["aliases"]:
                            all_names[alias] = account_name
                    else:
                        accounts[account_name]["aliases"] = []
                    logger.debug(
                        "Loaded account: `%s` with aliases: %s", account_name, accounts[account_name]["aliases"]
                    )
                except IndexError:
                    logger.exception("Invalid row format at row `%s`", row)
                row_num += 1
    except FileNotFoundError:
        logger.warning("No local accounts file found at %s", file_path)
    return accounts, all_names


def save_local_accounts(accounts, file_path):
    """Save local accounts to the CSV file"""
    try:
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "password", "aliases"])

            for account_name, data in accounts.items():
                aliases = "|".join(data.get("aliases", []))
                writer.writerow([account_name, data.get("password", ""), aliases])

        logger.info("Saved %d local accounts to %s", len(accounts), file_path)
        return True
    except Exception:
        logger.exception("Failed to save local accounts")
        return False


# Local character CSV schema. Bool items store "true"/"false"/blank (blank = unknown).
# Count items store integers/blank (blank = unknown).
LOCAL_CHARACTER_BOOL_ITEMS: tuple[str, ...] = (
    "seb",
    "vp",
    "st",
    "void",
    "neck",
    "thurg",
    "reaper",
    "brass_idol",
)
LOCAL_CHARACTER_COUNT_ITEMS: tuple[str, ...] = (
    "lizard",
    "pearl",
    "peridot",
    "mb3",
    "mb4",
    "mb5",
)
LOCAL_CHARACTER_FIELDS: tuple[str, ...] = (
    "account",
    "name",
    "class",
    "level",
    "bind",
    "park",
    *(f"item_{k}" for k in LOCAL_CHARACTER_BOOL_ITEMS),
    *(f"item_{k}" for k in LOCAL_CHARACTER_COUNT_ITEMS),
)

_BOOL_TRUE = {"true", "1", "yes", "y", "t"}
_BOOL_FALSE = {"false", "0", "no", "n", "f"}


def _parse_optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    v = value.strip().lower()
    if not v:
        return None
    if v in _BOOL_TRUE:
        return True
    if v in _BOOL_FALSE:
        return False
    return None


def _parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _format_optional_bool(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return ""


def _format_optional_int(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""


def load_local_characters(file_path: str) -> dict[str, dict]:
    """Load local characters from a flat CSV.

    Returns a dict keyed by lowercase character name. Each value mirrors the SSO
    character dict shape: ``{"name", "account", "class", "level", "bind", "park", "items"}``
    where ``items`` is a dict of wire keys to bool/int/None.
    """
    if not os.path.exists(file_path):
        logger.info("No local characters file found at %s, creating example", file_path)
        try:
            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(LOCAL_CHARACTER_FIELDS)
        except Exception:
            logger.exception("Failed to create example local characters file")
        return {}

    characters: dict[str, dict] = {}
    try:
        with open(file_path, newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return characters
            for row in reader:
                try:
                    name = (row.get("name") or "").strip()
                    if not name:
                        continue
                    key = name.lower()
                    account = (row.get("account") or "").strip().lower()
                    klass = (row.get("class") or "").strip() or None
                    level = _parse_optional_int(row.get("level"))
                    bind = (row.get("bind") or "").strip() or None
                    park = (row.get("park") or "").strip() or None
                    items: dict[str, bool | int | None] = {}
                    for wk in LOCAL_CHARACTER_BOOL_ITEMS:
                        items[wk] = _parse_optional_bool(row.get(f"item_{wk}"))
                    for wk in LOCAL_CHARACTER_COUNT_ITEMS:
                        items[wk] = _parse_optional_int(row.get(f"item_{wk}"))
                    characters[key] = {
                        "name": name,
                        "account": account,
                        "class": klass,
                        "level": level,
                        "bind": bind,
                        "park": park,
                        "items": items,
                    }
                except Exception:
                    logger.exception("Invalid row in local characters CSV: %s", row)
    except FileNotFoundError:
        logger.warning("No local characters file found at %s", file_path)
    except Exception:
        logger.exception("Failed to read local characters file: %s", file_path)
    return characters


def save_local_characters(characters: dict[str, dict], file_path: str) -> bool:
    """Save local characters to ``file_path`` in the flat CSV schema."""
    try:
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(LOCAL_CHARACTER_FIELDS)
            for key in sorted(characters):
                entry = characters[key]
                items = entry.get("items") or {}
                row = [
                    (entry.get("account") or "").strip().lower(),
                    entry.get("name") or key,
                    entry.get("class") or "",
                    _format_optional_int(entry.get("level")),
                    entry.get("bind") or "",
                    entry.get("park") or "",
                ]
                for wk in LOCAL_CHARACTER_BOOL_ITEMS:
                    row.append(_format_optional_bool(items.get(wk)))
                for wk in LOCAL_CHARACTER_COUNT_ITEMS:
                    row.append(_format_optional_int(items.get(wk)))
                writer.writerow(row)
        logger.info("Saved %d local characters to %s", len(characters), file_path)
        return True
    except Exception:
        logger.exception("Failed to save local characters")
        return False


def get_dynamic_tag_list(dt_zones: list[str], dt_classes: list[str]) -> list[str]:
    dt_list = [f"{a}{b}" for a, b in itertools.product(dt_zones, dt_classes)]
    return dt_list
