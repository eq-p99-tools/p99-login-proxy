# Based in large part on the original work by Zaela:
# https://github.com/Zaela/p99-login-middlemand
"""Sequence translation and server-list filtering for the login proxy.

The proxy sits between the EQ client and the login server and may
collapse multi-fragment responses (the server list) into a single
packet for the client.  This means the two sides' sequence numbers
diverge, so the proxy must rewrite them in both directions:

* **Server -> Client**: every OP_Packet/OP_Fragment sequence is
  rewritten to the client's monotonically-increasing counter.
* **Client -> Server**: every OP_Ack the client sends (referencing the
  client-side sequence space) is rewritten back to the server's space.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from p99_sso_login_proxy import login_protocol as lp
from p99_sso_login_proxy import soe_protocol as soe

logger = logging.getLogger(__name__)

P99_SERVER_PREFIXES = (
    "project 1999",
    "an interesting",
)


class ProxySessionState:
    """Manages sequence-number translation and server-list
    reassembly for one login session."""

    def __init__(self):
        self.seq_to_client: int = 0
        self.seq_from_server: int = 0
        self._fragment_assembler = soe.FragmentAssembler()
        self._pending_app_opcode: int | None = None

    def reset(self):
        self.seq_to_client = 0
        self.seq_from_server = 0
        self._fragment_assembler.reset()
        self._pending_app_opcode = None

    # ------------------------------------------------------------------
    # Client -> Server  (rewrite ACK sequences)
    # ------------------------------------------------------------------
    def adjust_combined(self, buf: bytearray) -> None:
        """Rewrite ACK sub-packets inside a client-to-server
        OP_Combined."""
        combined = soe.CombinedPacket.parse(buf)
        for sub in combined:
            if sub.transport_op == soe.TransportOp.Ack:
                self._rewrite_ack(buf, sub.offset)

    def adjust_ack(
        self,
        buf: bytearray,
        offset: int = 0,
    ) -> None:
        """Rewrite a standalone client-to-server ACK packet."""
        self._rewrite_ack(buf, offset)

    def _rewrite_ack(
        self,
        buf: bytearray,
        offset: int,
    ) -> None:
        """Translate client-side ACK sequence to the server's
        space."""
        new_seq = max(self.seq_from_server - 1, 0)
        soe.set_sequence(buf, offset, new_seq)

    # ------------------------------------------------------------------
    # Server -> Client  (rewrite sequences, reassemble fragments)
    # ------------------------------------------------------------------
    def recv_combined(
        self,
        buf: bytearray,
        recv_func: Callable,
        start_index: int = 0,
        length: int | None = None,
    ) -> None:
        """Split a server-to-client OP_Combined and dispatch each
        sub-packet."""
        combined = soe.CombinedPacket.parse(buf, start_index, length)
        for sub in combined:
            recv_func(
                buf,
                start_index=sub.offset,
                length=sub.length,
                addr=None,
            )

    def recv_packet(
        self,
        buf: bytearray,
        start_index: int = 0,
        length: int | None = None,
    ) -> bytearray | None:
        """Handle an OP_Packet from the server.

        Rewrites the sequence number.  Returns ``None`` (normal
        packets are forwarded as-is by the caller).
        """
        if length is None:
            length = len(buf) - start_index

        server_seq = soe.get_sequence(buf, start_index)
        soe.set_sequence(buf, start_index, self.seq_to_client)
        self.seq_to_client += 1

        if server_seq != self.seq_from_server:
            logger.debug(
                "Out-of-order OP_Packet seq=%d expected=%d",
                server_seq,
                self.seq_from_server,
            )
            return None
        self.seq_from_server += 1
        return None

    def recv_fragment(
        self,
        buf: bytearray,
        start_index: int = 0,
        length: int | None = None,
    ) -> bytearray | None:
        """Handle an OP_Fragment from the server.

        Returns a single assembled + filtered server list packet
        when all fragments have arrived, or ``None`` if still
        accumulating.
        """
        if length is None:
            length = len(buf) - start_index
        raw = bytes(buf[start_index : start_index + length])

        server_seq = soe.get_sequence(raw, 0)
        self.seq_from_server = server_seq + 1

        if not self._fragment_assembler.active:
            header = soe.parse_first_fragment_header(raw)
            self._pending_app_opcode = header["app_opcode"]

        assembled = self._fragment_assembler.add(server_seq, raw)
        if assembled is None:
            return None

        app_opcode = self._pending_app_opcode
        self._fragment_assembler.reset()
        self._pending_app_opcode = None

        if app_opcode != lp.AppOp.ServerListResponse:
            logger.debug("Ignoring non-server-list fragment (app_op=0x%04X)", app_opcode)
            return None

        return self._filter_and_build_server_list(assembled)

    # ------------------------------------------------------------------
    # Server list filtering
    # ------------------------------------------------------------------
    def _filter_and_build_server_list(
        self,
        app_payload: bytes,
    ) -> bytearray:
        """Parse, filter to P99 servers, and rebuild as a single
        OP_Packet.

        *app_payload* already starts with the 2-byte LE app opcode
        (from the first fragment's data after total_len).
        """
        servers, header_bytes = lp.parse_server_list(app_payload)
        logger.debug(
            "Unfiltered server list (%d): %s",
            len(servers),
            [s.name for s in servers],
        )

        filtered = [s for s in servers if any(s.name.lower().startswith(prefix) for prefix in P99_SERVER_PREFIXES)]
        logger.info(
            "Server list: %d total, %d after filter: %s",
            len(servers),
            len(filtered),
            [s.name for s in filtered],
        )

        rebuilt = lp.build_server_list_response(filtered, header_bytes)

        out = bytearray()
        out += soe.TransportOp.Packet.to_bytes(2, "big")
        out += self.seq_to_client.to_bytes(2, "big")
        out += rebuilt
        self.seq_to_client += 1
        return out


# Backward-compat alias
Sequence = ProxySessionState
