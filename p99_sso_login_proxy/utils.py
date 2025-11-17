import csv
import itertools
import os

def hex_to_bytes(hex_str):
    return bytes.fromhex(hex_str.replace('\\x', ''))


def load_local_accounts(file_path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    if not os.path.exists(file_path):
        print(f"No local accounts file found at {file_path}, creating example")
        try:
            with open(file_path, 'w') as f:
                f.write("name,password,aliases\n")
                f.write("exampleaccount1,password_goes_here,examplealias1|examplealias2\n")
        except Exception as e:
            print(f"Failed to create example local accounts file: {e}")
    accounts = {}
    all_names = {}
    try:
        with open(file_path, 'r') as f:
            reader = csv.reader(f)
            row_num = 0
            for row in reader:
                try:
                    if row_num == 0 and "name" in row[0]:
                        # print("Skipping header row")
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
                    # print(f"Loaded account: `{account_name}` with aliases: {accounts[account_name]['aliases']}")
                except IndexError as e:
                    print(f"Invalid row format at row `{row}`: {e}")
                row_num += 1
    except FileNotFoundError:
        print(f"No local accounts file found at {file_path}")
    return accounts, all_names

def save_local_accounts(accounts, file_path):
    """Save local accounts to the CSV file"""
    try:
        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["name", "password", "aliases"])
            
            for account_name, data in accounts.items():
                aliases = "|".join(data.get("aliases", []))
                writer.writerow([account_name, data.get("password", ""), aliases])
        
        print(f"Saved {len(accounts)} local accounts to {file_path}")
        return True
    except Exception as e:
        print(f"Failed to save local accounts: {e}")
        return False


def get_dynamic_tag_list(dt_zones: list[str], dt_classes: list[str]) -> list[str]:
    dt_list = ["{}{}".format(a, b) for a, b in itertools.product(dt_zones, dt_classes)]
    return dt_list
