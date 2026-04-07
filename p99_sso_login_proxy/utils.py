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


def get_dynamic_tag_list(dt_zones: list[str], dt_classes: list[str]) -> list[str]:
    dt_list = [f"{a}{b}" for a, b in itertools.product(dt_zones, dt_classes)]
    return dt_list
