"""SOE/Daybreak UDP transport protocol.

Handles session establishment, packet wrapping, acknowledgements,
combined packet splitting, and fragment reassembly for the EverQuest
login server protocol.

P99's login server uses crc_bytes=0 and encode_key=0, so CRC is
effectively a no-op.  The logic is retained for completeness.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transport-layer opcodes  (big-endian on the wire, high byte always 0x00)
# ---------------------------------------------------------------------------
class TransportOp(IntEnum):
    SessionRequest = 0x0001
    SessionResponse = 0x0002
    Combined = 0x0003
    SessionDisconnect = 0x0005
    KeepAlive = 0x0006
    SessionStatRequest = 0x0007
    SessionStatResponse = 0x0008
    Packet = 0x0009
    Fragment = 0x000D
    OutOfOrder = 0x0011
    Ack = 0x0015
    AppCombined = 0x0019
    OutOfSession = 0x001D


TRANSPORT_NAMES: dict[int, str] = {op.value: op.name for op in TransportOp}


def get_transport_opcode(data: bytes) -> int:
    """Read the 2-byte big-endian transport opcode from raw packet data."""
    return struct.unpack(">H", data[:2])[0]


def transport_name(op: int) -> str:
    return TRANSPORT_NAMES.get(op, f"0x{op:04X}")


# ---------------------------------------------------------------------------
# CRC-32  (SOE variant: init=0, final XOR with encode_key)
# ---------------------------------------------------------------------------
def _generate_crc_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
        table.append(crc)
    return table


_CRC_TABLE = _generate_crc_table()


def soe_crc32(data: bytes, key: int) -> int:
    crc = 0
    for byte in data:
        crc = _CRC_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return (crc ^ key) & 0xFFFFFFFF


def append_crc(packet: bytes, key: int, crc_bytes: int) -> bytes:
    if crc_bytes == 0:
        return packet
    crc = soe_crc32(packet, key)
    if crc_bytes == 2:
        return packet + struct.pack(">H", crc & 0xFFFF)
    return packet + struct.pack(">I", crc)


def strip_crc(packet: bytes, crc_bytes: int) -> bytes:
    if crc_bytes == 0:
        return packet
    return packet[:-crc_bytes]


# ---------------------------------------------------------------------------
# Packet builders
# ---------------------------------------------------------------------------
def build_ack(sequence: int) -> bytes:
    return struct.pack(">HH", TransportOp.Ack, sequence)


def build_keepalive() -> bytes:
    return struct.pack(">H", TransportOp.KeepAlive)


def build_disconnect() -> bytes:
    return struct.pack(">H", TransportOp.SessionDisconnect)


def build_combined(sub_packets: list[bytes]) -> bytes:
    """Build OP_Combined from raw sub-packet datagrams.

    Each sub-packet is length-prefixed: 1 byte if <255, else 0xFF + 2-byte BE.
    """
    body = b""
    for sub in sub_packets:
        slen = len(sub)
        if slen >= 0xFF:
            body += b"\xFF" + struct.pack(">H", slen) + sub
        else:
            body += struct.pack("B", slen) + sub
    return struct.pack(">H", TransportOp.Combined) + body


def wrap_app_packet(sequence: int, app_payload: bytes) -> bytes:
    """Wrap an application payload in OP_Packet.

    *app_payload* must include the 2-byte LE app opcode.
    """
    return struct.pack(">HH", TransportOp.Packet, sequence) + app_payload


# ---------------------------------------------------------------------------
# Packet parsers
# ---------------------------------------------------------------------------
def parse_session_response(data: bytes) -> dict:
    """Parse OP_SessionResponse (21 bytes).

    Wire layout::

        opcode(2 BE) + session(4 BE) + key(4 BE)
        + crc_length(1) + format(1) + unknownB(1)
        + max_length(4 LE) + unknownD(4)
    """
    if len(data) < 17:
        raise ValueError(f"SessionResponse too short ({len(data)} bytes)")
    connect_code, encode_key = struct.unpack(">II", data[2:10])
    return {
        "connect_code": connect_code,
        "encode_key": encode_key,
        "crc_bytes": data[10],
        "encode_pass1": data[11],
        "encode_pass2": data[12],
        "max_packet_size": struct.unpack("<I", data[13:17])[0],
    }


def parse_combined(data: bytes) -> list[bytes]:
    """Split an OP_Combined packet into its sub-packets.

    *data* starts with the 2-byte Combined opcode.
    """
    subs: list[bytes] = []
    pos = 2
    length = len(data)
    while pos < length:
        sublen = data[pos]
        pos += 1
        if sublen == 0xFF and pos + 2 <= length:
            sublen = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
        if sublen == 0 or pos + sublen > length:
            break
        subs.append(bytes(data[pos:pos + sublen]))
        pos += sublen
    return subs


@dataclass
class CombinedPacket:
    """Parsed view of an OP_Combined packet.

    Provides iteration over sub-packets with their offsets into
    the original buffer, supporting both read-only splitting and
    in-place mutation (e.g. ACK sequence rewriting).

    Can be constructed from raw bytes via ``CombinedPacket.parse()``
    or from a mutable bytearray with an optional ``start_index``
    for packets that arrived inside an outer Combined.
    """

    @dataclass
    class SubPacket:
        """One sub-packet inside a Combined."""
        offset: int         # absolute offset in the buffer
        length: int
        transport_op: int   # the 2-byte BE opcode of this sub

    buf: bytearray | bytes
    start: int = 0
    end: int = 0
    subs: list[SubPacket] = field(default_factory=list)

    @classmethod
    def parse(
        cls,
        buf: bytearray | bytes,
        start_index: int = 0,
        length: int | None = None,
    ) -> CombinedPacket:
        """Walk the combined structure and index all sub-packets."""
        if length is None:
            length = len(buf) - start_index
        end = start_index + length
        pos = start_index + 2  # skip Combined opcode
        subs: list[CombinedPacket.SubPacket] = []
        while pos < end:
            sublen = buf[pos]
            pos += 1
            if sublen == 0xFF and pos + 2 <= end:
                sublen = int.from_bytes(
                    buf[pos:pos + 2], "big")
                pos += 2
            if sublen == 0 or pos + sublen > end:
                break
            op = struct.unpack(">H", buf[pos:pos + 2])[0]
            subs.append(cls.SubPacket(
                offset=pos, length=sublen,
                transport_op=op))
            pos += sublen
        return cls(
            buf=buf, start=start_index,
            end=end, subs=subs)

    def __iter__(self):
        return iter(self.subs)

    def __len__(self):
        return len(self.subs)

    def sub_bytes(self, sub: SubPacket) -> bytes:
        """Return the raw bytes of a sub-packet."""
        return bytes(
            self.buf[sub.offset:sub.offset + sub.length])


def get_app_payload(packet: bytes) -> tuple[int, bytes]:
    """Extract *(sequence, app_payload)* from OP_Packet / OP_Fragment."""
    seq = struct.unpack(">H", packet[2:4])[0]
    return seq, bytes(packet[4:])


def get_sequence(data: bytes, offset: int = 0) -> int:
    """Read the 2-byte big-endian sequence from an OP_Packet or OP_Fragment."""
    return struct.unpack(">H", data[offset + 2:offset + 4])[0]


def set_sequence(data: bytearray, offset: int, seq: int) -> None:
    """Write a 2-byte big-endian sequence into a mutable buffer."""
    struct.pack_into(">H", data, offset + 2, seq)


# ---------------------------------------------------------------------------
# Fragment constants
# ---------------------------------------------------------------------------
FIRST_FRAG_OVERHEAD = 8   # opcode(2) + seq(2) + total_len(4)
SUBSEQUENT_FRAG_OVERHEAD = 4  # opcode(2) + seq(2)
FIRST_FRAG_HEADER = 10   # opcode(2) + seq(2) + total_len(4) + app_opcode(2)


def parse_first_fragment_header(data: bytes) -> dict:
    """Parse the header of a first fragment.

    Returns dict with opcode, sequence, total_len, app_opcode.
    Transport fields are big-endian; app_opcode is little-endian.
    """
    op, seq, total_len = struct.unpack(">HHI", data[:8])
    app_op = struct.unpack("<H", data[8:10])[0]
    return {
        "transport_op": op,
        "sequence": seq,
        "total_len": total_len,
        "app_opcode": app_op,
    }


def build_fragments(
    app_payload: bytes,
    start_seq: int,
    max_packet: int = 512,
) -> list[bytes]:
    """Split *app_payload* into OP_Fragment datagrams.

    *app_payload* must include the 2-byte LE app opcode.
    Returns a list of raw fragment packets (before CRC).
    """
    total_len = len(app_payload)
    first_capacity = max_packet - FIRST_FRAG_OVERHEAD
    subsequent_capacity = max_packet - SUBSEQUENT_FRAG_OVERHEAD

    frags: list[bytes] = []

    chunk = app_payload[:first_capacity]
    hdr = struct.pack(">HHI", TransportOp.Fragment, start_seq, total_len)
    frags.append(hdr + chunk)

    pos = first_capacity
    seq = start_seq + 1
    while pos < total_len:
        chunk = app_payload[pos:pos + subsequent_capacity]
        hdr = struct.pack(">HH", TransportOp.Fragment, seq)
        frags.append(hdr + chunk)
        pos += subsequent_capacity
        seq += 1

    return frags


# ---------------------------------------------------------------------------
# Fragment reassembler
# ---------------------------------------------------------------------------
class FragmentAssembler:
    """Reassembles fragmented responses (e.g. large server lists).

    Uses accumulated byte length rather than a predicted fragment count
    to decide when reassembly is complete.
    """

    def __init__(self):
        self.fragments: dict[int, bytes] = {}
        self.total_len: int | None = None
        self.first_seq: int | None = None
        self._accumulated: int = 0

    @property
    def active(self) -> bool:
        return self.first_seq is not None

    def add(self, seq: int, raw_frag: bytes) -> bytes | None:
        """Feed a raw OP_Fragment datagram (after CRC strip).

        Returns reassembled app payload when all fragments arrive.
        """
        frag_data = raw_frag[4:]  # strip opcode(2) + seq(2)

        if self.first_seq is None or seq < self.first_seq:
            if self.first_seq is not None and seq < self.first_seq:
                self.fragments.clear()
                self._accumulated = 0
            self.first_seq = seq
            self.total_len = struct.unpack(">I", frag_data[:4])[0]
            payload = frag_data[4:]
            self.fragments[seq] = payload
            self._accumulated += len(payload)
        else:
            self.fragments[seq] = frag_data
            self._accumulated += len(frag_data)

        if (self.total_len is not None
                and self._accumulated >= self.total_len):
            return self._reassemble()
        return None

    def _reassemble(self) -> bytes:
        ordered = sorted(self.fragments.items())
        return b"".join(d for _, d in ordered)[:self.total_len]

    def reset(self):
        self.fragments.clear()
        self.total_len = None
        self.first_seq = None
        self._accumulated = 0
