#!/usr/bin/env python3
"""Generate canonical hex fixtures from the legacy Python protocol implementation."""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_PROJECT = ROOT.parent / "p99-login-proxy"
FIXTURES = ROOT / "crates" / "protocol" / "tests" / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)


def load_module(name: str, rel_path: str):
    path = PY_PROJECT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lp = load_module("login_protocol", "p99_sso_login_proxy/login_protocol.py")
soe = load_module("soe_protocol", "p99_sso_login_proxy/soe_protocol.py")
sys.modules["p99_sso_login_proxy"] = type(sys)("p99_sso_login_proxy")
sys.modules["p99_sso_login_proxy.login_protocol"] = lp
sys.modules["p99_sso_login_proxy.soe_protocol"] = soe
session_mod = load_module("session", "p99_sso_login_proxy/session.py")


def write_hex(name: str, data: bytes) -> None:
    path = FIXTURES / name
    path.write_text(data.hex() + "\n", encoding="ascii")
    print(f"wrote {path.relative_to(ROOT)} ({len(data)} bytes)")


def main() -> None:
    login = lp.encrypt_login_credentials("user", "pass")
    base = struct.pack("<iBbI", 3, 0, 2, 0)
    app = struct.pack("<H", lp.AppOp.Login) + base + login
    packet_sub = struct.pack(">HH", soe.TransportOp.Packet, 1) + app
    ack_sub = struct.pack(">HH", soe.TransportOp.Ack, 0)
    combined = soe.build_combined([ack_sub, packet_sub])
    write_hex("combined_ack_login.hex", combined)

    state = session_mod.ProxySessionState()
    state.note_injected_client_packet()
    buf = bytearray(combined)
    state.adjust_combined(buf)
    write_hex("combined_ack_login_cs_offset.hex", bytes(buf))

    plaintext = struct.pack("<III", 12345, 0, lp.LOGIN_RESULT_FAILURE_STATUS) + b"\x00" * 20
    enc = lp.des_encrypt(plaintext)
    bad_payload = struct.pack("<H", lp.AppOp.LoginAccepted) + base + enc
    write_hex("bad_password_login_accepted.hex", bad_payload)

    print("oracle complete")


if __name__ == "__main__":
    main()
