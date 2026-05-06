"""EQEmu login-server application-layer protocol.

Builds and parses the application packets that ride inside OP_Packet
transport wrappers: login credentials, server list, play requests, etc.

Opcode values confirmed via real P99 Titanium packet captures.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from enum import IntEnum

from Cryptodome.Cipher import DES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application-layer opcodes  (little-endian on the wire)
# ---------------------------------------------------------------------------
class AppOp(IntEnum):
    # Client -> Server
    SessionReady = 0x0001
    Login = 0x0002
    LoginComplete = 0x0003
    ServerListRequest = 0x0004
    PlayEverquestRequest = 0x000D
    EnterChat = 0x000F

    # Server -> Client
    ChatMessage = 0x0016
    LoginAccepted = 0x0017
    ServerListResponse = 0x0018
    PlayEverquestResponse = 0x0021

    # Bidirectional
    PollResponse = 0x0011
    Poll = 0x0029


APP_OPCODE_NAMES: dict[int, str] = {op.value: op.name for op in AppOp}


def get_app_opcode(app_payload: bytes) -> int:
    """Read the 2-byte little-endian app opcode."""
    return struct.unpack("<H", app_payload[:2])[0]


def app_opcode_name(op: int) -> str:
    return APP_OPCODE_NAMES.get(op, f"0x{op:04X}")


# ---------------------------------------------------------------------------
# DES encryption  (all-zero key / IV, CBC)
# ---------------------------------------------------------------------------
DES_KEY = b"\x00" * 8
DES_IV = b"\x00" * 8


def des_encrypt(
    plaintext: bytes,
    key: bytes = DES_KEY,
    iv: bytes = DES_IV,
) -> bytes:
    """DES-CBC encrypt, null-padding to 8-byte boundary."""
    padded_len = ((len(plaintext) + 7) // 8) * 8
    padded = plaintext.ljust(padded_len, b"\x00")
    cipher = DES.new(key, DES.MODE_CBC, iv)
    return cipher.encrypt(padded)


def des_decrypt(
    ciphertext: bytes,
    key: bytes = DES_KEY,
    iv: bytes = DES_IV,
) -> bytes:
    """DES-CBC decrypt.  Must be a multiple of 8 bytes."""
    cipher = DES.new(key, DES.MODE_CBC, iv)
    return cipher.decrypt(ciphertext)


# ---------------------------------------------------------------------------
# LoginBaseMessage  (10 bytes, little-endian, unencrypted header)
#
#   int32  sequence      (2=handshake, 3=login, 4=serverlist, ...)
#   bool   compressed
#   int8   encrypt_type  (0=none, 2=DES)
#   int32  unk3
# ---------------------------------------------------------------------------
LOGIN_BASE_SIZE = 10


def parse_login_base(data: bytes) -> dict:
    seq, compressed, enc_type, unk3 = struct.unpack("<iBbI", data[:LOGIN_BASE_SIZE])
    return {
        "sequence": seq,
        "compressed": compressed,
        "encrypt_type": enc_type,
        "unk3": unk3,
    }


# ---------------------------------------------------------------------------
# LoginAccepted classification
#
# OP_LoginAccepted carries:
#   2 bytes  app opcode (LE)
#   10 bytes LoginBaseMessage (sequence=3, encrypt_type=2 in P99/Titanium)
#   N bytes  DES-encrypted body (8-byte aligned; some servers append a stray
#            trailing byte that must be stripped before decrypting)
#
# Decrypted body layout:
#   u32 account_id
#   u32 reserved          (always 0 in observed captures)
#   u32 status            (0xFFFFFFFF == "bad password"; otherwise play-token)
#   N bytes tail          (zero on failure; LSKey + flags on success)
# ---------------------------------------------------------------------------
LOGIN_RESULT_HEADER_SIZE = 2 + LOGIN_BASE_SIZE  # 12 bytes
LOGIN_RESULT_FAILURE_STATUS = 0xFFFFFFFF


def is_bad_password_login_result(
    app_payload: bytes,
    key: bytes = DES_KEY,
    iv: bytes = DES_IV,
) -> bool:
    """Return True if *app_payload* is an OP_LoginAccepted indicating a
    rejected password.

    Verified against ``example_data/NoProxy_BadPassword.json`` (true) and
    ``example_data/NoProxy_ServerListIdle.json`` (false).
    """
    if len(app_payload) < LOGIN_RESULT_HEADER_SIZE:
        return False
    if get_app_opcode(app_payload) != AppOp.LoginAccepted:
        return False

    base = parse_login_base(app_payload[2:LOGIN_RESULT_HEADER_SIZE])
    if base["sequence"] != 3 or base["encrypt_type"] != 2:
        return False

    encrypted = app_payload[LOGIN_RESULT_HEADER_SIZE:]
    # Some captures show a trailing byte past the DES block boundary; drop it.
    if encrypted and len(encrypted) % 8 == 1:
        encrypted = encrypted[:-1]
    if not encrypted or len(encrypted) % 8:
        return False

    try:
        decrypted = des_decrypt(encrypted, key, iv)
    except (ValueError, TypeError):
        return False
    if len(decrypted) < 12:
        return False

    _account_id, _reserved, status = struct.unpack("<III", decrypted[:12])
    if status != LOGIN_RESULT_FAILURE_STATUS:
        return False
    # On failure the tail is zero-padding. A non-zero tail (e.g. an LSKey)
    # means this is a successful login that happens to use 0xFFFFFFFF
    # somewhere else, which we treat as not-bad to be safe.
    return all(b == 0 for b in decrypted[12:])


# ---------------------------------------------------------------------------
# LoginPacket  — wraps a Combined(ACK + Login) buffer
#
# Wire layout of Combined(ACK + OP_Packet(Login)):
#   00 03                       OP_Combined
#   04                          ACK sub-packet length (always 4)
#   00 15 XX XX                 OP_Ack + sequence
#   YY                          Login sub-packet length byte
#   00 09 SS SS                 OP_Packet + sequence
#   02 00                       AppOp.Login (LE)
#   <LoginBaseMessage 10 bytes>
#   <DES-encrypted credentials>
# ---------------------------------------------------------------------------
_ACK_END = 2 + 1 + 4  # Combined(2) + len(1) + ACK(4) = 7
_LOGIN_SUB_HEADER = 4 + 2  # OP_Packet(2) + seq(2) + app_op(2) = 6
_ENC_OFFSET = _LOGIN_SUB_HEADER + LOGIN_BASE_SIZE  # 16


@dataclass
class LoginPacket:
    """Parsed view of a Combined(ACK + Login) buffer.

    Use ``LoginPacket.parse(buf)`` to try parsing; returns ``None``
    if *buf* is not a Combined(ACK + Login).
    """

    buf: bytearray
    username: str
    password: str
    _sub2_offset: int
    _sub2_len: int
    _enc_offset: int = _ENC_OFFSET

    @classmethod
    def parse(
        cls,
        buf: bytearray,
        key: bytes = DES_KEY,
        iv: bytes = DES_IV,
    ) -> LoginPacket | None:
        """Try to parse *buf* as a Combined(ACK + Login).

        Returns a ``LoginPacket`` on success, ``None`` otherwise.
        """
        if len(buf) < 30:
            return None
        if not buf.startswith(b"\x00\x03\x04\x00\x15"):
            return None

        if len(buf) <= _ACK_END:
            return None
        sub2_len = buf[_ACK_END]
        sub2_start = _ACK_END + 1

        if sub2_start + sub2_len > len(buf) or sub2_len < _LOGIN_SUB_HEADER:
            return None

        sub2 = buf[sub2_start : sub2_start + sub2_len]

        transport_op = struct.unpack(">H", sub2[:2])[0]
        if transport_op != 0x0009:  # OP_Packet
            return None
        app_op = struct.unpack("<H", sub2[4:6])[0]
        if app_op != AppOp.Login:
            return None

        if len(sub2) <= _ENC_OFFSET:
            return None
        encrypted = sub2[_ENC_OFFSET:]
        username, password = _decrypt_credentials(encrypted, key, iv)

        return cls(
            buf=buf,
            username=username,
            password=password,
            _sub2_offset=sub2_start,
            _sub2_len=sub2_len,
        )

    def rewrite_credentials(
        self,
        new_user: str,
        new_pass: str,
        key: bytes = DES_KEY,
        iv: bytes = DES_IV,
    ) -> bytearray:
        """Return a new buffer with rewritten credentials."""
        new_enc = encrypt_login_credentials(new_user, new_pass, key, iv)
        return self.splice_encrypted_credentials(new_enc)

    def splice_encrypted_credentials(
        self,
        encrypted: bytes,
    ) -> bytearray:
        """Return a new buffer with pre-encrypted credentials spliced in."""
        abs_start = self._sub2_offset + self._enc_offset
        abs_end = self._sub2_offset + self._sub2_len

        out = bytearray(self.buf[:abs_start] + encrypted + self.buf[abs_end:])
        # Update the sub-packet length byte
        new_sub_len = self._enc_offset + len(encrypted)
        out[self._sub2_offset - 1] = new_sub_len
        return out


# ---------------------------------------------------------------------------
# Low-level credential helpers
# ---------------------------------------------------------------------------
def _decrypt_credentials(
    encrypted: bytes,
    key: bytes = DES_KEY,
    iv: bytes = DES_IV,
) -> tuple[str, str]:
    decrypted = des_decrypt(encrypted, key, iv)
    parts = decrypted.rstrip(b"\x00").split(b"\x00")
    username = parts[0].decode("ascii", errors="replace")
    password = parts[1].decode("ascii", errors="replace") if len(parts) > 1 else ""
    return username, password


def encrypt_login_credentials(
    username: str,
    password: str,
    key: bytes = DES_KEY,
    iv: bytes = DES_IV,
) -> bytes:
    """Encrypt ``user\\0pass\\0`` for a Login packet payload."""
    plaintext = username.encode() + b"\x00" + password.encode() + b"\x00"
    return des_encrypt(plaintext, key, iv)


# ---------------------------------------------------------------------------
# Server list parsing
# ---------------------------------------------------------------------------
@dataclass
class ServerEntry:
    """A single server in the OP_ServerListResponse."""

    ip: str
    list_id: int
    runtime_id: int
    name: str
    language: str
    region: str
    status: int
    player_count: int
    raw: bytes  # original wire bytes for passthrough


def parse_server_list(
    app_payload: bytes,
) -> tuple[list[ServerEntry], bytes]:
    """Parse OP_ServerListResponse.

    *app_payload* starts with the 2-byte LE app opcode.

    Returns ``(servers, header_bytes)`` where *header_bytes* is the
    original 16-byte header for passthrough when rebuilding.
    """
    data = app_payload[2:]  # skip app opcode
    header_bytes = bytes(data[:16])
    count = struct.unpack("<I", data[16:20])[0]
    pos = 20

    servers: list[ServerEntry] = []
    while pos < len(data) and len(servers) < count:
        start = pos
        try:
            ip = _read_cstr(data, pos)
            pos += len(ip) + 1
            list_id, runtime_id = struct.unpack("<II", data[pos : pos + 8])
            pos += 8
            name = _read_cstr(data, pos)
            pos += len(name) + 1
            language = _read_cstr(data, pos)
            pos += len(language) + 1
            region = _read_cstr(data, pos)
            pos += len(region) + 1
            status, player_count = struct.unpack("<II", data[pos : pos + 8])
            pos += 8
        except (struct.error, IndexError, ValueError):
            logger.debug("Truncated server entry at offset %d", start)
            break

        servers.append(
            ServerEntry(
                ip=ip,
                list_id=list_id,
                runtime_id=runtime_id,
                name=name,
                language=language,
                region=region,
                status=status,
                player_count=player_count,
                raw=bytes(data[start:pos]),
            )
        )

    return servers, header_bytes


def build_server_list_response(
    servers: list[ServerEntry],
    header_bytes: bytes,
) -> bytes:
    """Rebuild OP_ServerListResponse from a (possibly filtered)
    server list.

    Returns the complete app payload including the 2-byte LE opcode.
    """
    count = struct.pack("<I", len(servers))
    entries = b"".join(srv.raw for srv in servers)
    return struct.pack("<H", AppOp.ServerListResponse) + header_bytes + count + entries


def _read_cstr(data: bytes, offset: int) -> str:
    end = data.index(b"\x00", offset)
    return data[offset:end].decode("utf-8", errors="replace")
