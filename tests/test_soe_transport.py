from __future__ import annotations

import struct
from unittest import mock

from p99_sso_login_proxy import soe_protocol as soe


def test_crc_matches_eqemu_keyed_vectors():
    assert soe.soe_crc32(b"123456789", 0) == 0x22896B0A
    assert soe.soe_crc32(b"123456789", 0x12345678) == 0xAAD05244


def test_duplicate_fragments_do_not_complete_with_gap():
    payload = bytes(range(40))
    fragments = soe.build_fragments(payload, 10, 16)
    assembler = soe.FragmentAssembler()

    assert assembler.add(10, fragments[0]) is None
    for _ in range(10):
        assert assembler.add(12, fragments[2]) is None
    assert assembler.add(11, fragments[1]) is None
    assert assembler.add(13, fragments[3]) == payload


def test_duplicate_first_fragment_does_not_copy_total_length():
    payload = bytes(range(40))
    fragments = soe.build_fragments(payload, 20, 16)
    assembler = soe.FragmentAssembler()

    assert assembler.add(20, fragments[0]) is None
    assert assembler.add(20, fragments[0]) is None
    assert assembler.add(21, fragments[1]) is None
    assert assembler.add(22, fragments[2]) is None
    assert assembler.add(23, fragments[3]) == payload


def test_fragments_reassemble_across_sequence_wrap():
    payload = bytes(range(40))
    fragments = soe.build_fragments(payload, 0xFFFE, 16)
    assembler = soe.FragmentAssembler()

    assert assembler.add(0xFFFE, fragments[0]) is None
    assert assembler.add(0xFFFF, fragments[1]) is None
    assert assembler.add(0, fragments[2]) is None
    assert assembler.add(1, fragments[3]) == payload


def test_proxy_applies_negotiated_crc_to_server_packets():
    with mock.patch("p99_sso_login_proxy.ui.PROXY_STATS", new=mock.MagicMock()):
        from p99_sso_login_proxy import server as server_mod

        proxy = server_mod.LoginProxy()

    proxy.transport = mock.MagicMock()
    proxy.client_addr = ("127.0.0.1", 4321)
    key = 0x12345678
    session_response = (
        struct.pack(">HII", soe.TransportOp.SessionResponse, 1, key) + bytes([2, 0, 0]) + struct.pack("<I", 512)
    )
    proxy.handle_server_packet(session_response)

    clean_packet = struct.pack(">HH", soe.TransportOp.Packet, 0) + b"\x17\x00payload"
    wire_packet = soe.append_crc(clean_packet, key, 2)
    proxy.handle_server_packet(wire_packet)

    sent = [bytes(call.args[0]) for call in proxy.transport.sendto.call_args_list]
    assert sent == [session_response, wire_packet]
