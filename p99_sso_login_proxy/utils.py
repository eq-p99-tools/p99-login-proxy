import csv

def hex_to_bytes(hex_str):
    return bytes.fromhex(hex_str.replace('\\x', ''))


def load_local_accounts(file_path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    accounts = {}
    all_names = {}
    try:
        with open(file_path, 'r') as f:
            reader = csv.reader(f)
            row = 0
            for row in reader:
                try:
                    if row == 0 and "name" in row[0]:
                        print("Skipping header row")
                        continue
                    accounts[row[0]] = {
                        "password": row[1],
                    }
                    all_names[row[0]] = row[0]
                    if len(row) > 2:
                        accounts[row[0]]["aliases"] = [alias.strip() for alias in row[2].split("|")]
                        for alias in accounts[row[0]]["aliases"]:
                            all_names[alias] = row[0]
                    else:
                        accounts[row[0]]["aliases"] = []
                    print(f"Loaded account: `{row[0]}` with aliases: {accounts[row[0]]["aliases"]}")
                except IndexError as e:
                    print(f"Invalid row format at row `{row}`: {e}")
    except FileNotFoundError:
        print(f"No local accounts file found at {file_path}")
    return accounts, all_names
