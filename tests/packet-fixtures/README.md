# Packet fixture corpus

Sanitized golden fixtures for the native protocol crate. No live passwords, tokens, or account names.

## Sources

- Python `tests/test_sso_retry.py` synthesizers
- `example_data/NoProxy_BadPassword.json` (LoginAccepted classification only; credentials redacted)
- `example_data/NoProxy_ServerListIdle.json` (good login classification)

## Oracle

Run `tools/generate_oracle.py` from the workspace root with the Python venv active to regenerate expected outputs from the legacy implementation.

## Fixture naming

- `combined_ack_login.hex` — Combined ACK + Login
- `bad_password_login_accepted.hex` — synthesized failure LoginAccepted
- `good_login_accepted.hex` — synthesized success LoginAccepted

## Server list capture fixtures

Regenerate from `example_data/Proxy_ServerListIdle.json` when needed:

```powershell
..\.venv\Scripts\python.exe -c "
import json, struct
from pathlib import Path
def hex_payload(obj):
    return bytes.fromhex(obj['_source']['layers']['udp']['udp.payload'].replace(':',''))
data = json.loads(Path('../example_data/Proxy_ServerListIdle.json').read_text())
frags = [hex_payload(pkt) for pkt in data if len(hex_payload(pkt))>=2 and struct.unpack('>H', hex_payload(pkt)[:2])[0]==0x000D]
Path('crates/protocol/tests/fixtures/server_list_fragments.hexlist').write_text(chr(10).join(f.hex() for f in frags), encoding='ascii')
"
```
