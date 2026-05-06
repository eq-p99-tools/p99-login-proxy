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

from p99_sso_login_proxy import login_protocol as lp
from p99_sso_login_proxy import soe_protocol as soe

logger = logging.getLogger(__name__)

P99_SERVER_PREFIXES = (
    "project 1999",
    "an interesting",
)


class ProxySessionState:
    """Manages sequence-number translation and server-list
    reassembly for one login session.

    Sequence translation has two independent counters:

    * ``seq_to_client``   - next OP_Packet/OP_Fragment sequence the proxy
      will hand to the client. Advances every time we forward a server
      packet, but **not** when we suppress one.
    * ``seq_from_server`` - the highest server-side sequence we have seen.
      Used to ACK back to the server. Advances on **every** server packet,
      including ones we suppress.

    A third counter, ``cs_offset``, tracks how many extra C->S OP_Packets
    the proxy has injected on top of what the client sent. This is used by
    the SSO bad-password retry path: when the proxy replays the original
    Login on the existing SOE session, every subsequent client OP_Packet
    sequence has to be shifted by +1 before forwarding to the server, or
    the server will see duplicate / out-of-order sequences.
    """

    def __init__(self):
        self.seq_to_client: int = 0
        self.seq_from_server: int = 0
        self.cs_offset: int = 0
        self._fragment_assembler = soe.FragmentAssembler()
        self._pending_app_opcode: int | None = None

    def reset(self):
        self.seq_to_client = 0
        self.seq_from_server = 0
        self.cs_offset = 0
        self._fragment_assembler.reset()
        self._pending_app_opcode = None

    # ------------------------------------------------------------------
    # Client -> Server  (rewrite ACK sequences, apply cs_offset)
    # ------------------------------------------------------------------
    def adjust_combined(self, buf: bytearray) -> None:
        """Adjust a client-to-server OP_Combined in place.

        Rewrites every ACK sub-packet to the server's sequence space and
        shifts every Packet sub-packet by ``cs_offset``.
        """
        combined = soe.CombinedPacket.parse(buf)
        for sub in combined:
            if sub.transport_op == soe.TransportOp.Ack:
                self._rewrite_ack(buf, sub.offset)
            elif sub.transport_op == soe.TransportOp.Packet and self.cs_offset:
                self._shift_packet_seq(buf, sub.offset, self.cs_offset)

    def adjust_ack(
        self,
        buf: bytearray,
        offset: int = 0,
    ) -> None:
        """Rewrite a standalone client-to-server ACK packet."""
        self._rewrite_ack(buf, offset)

    def adjust_client_packet(
        self,
        buf: bytearray,
        offset: int = 0,
    ) -> None:
        """Apply ``cs_offset`` to a standalone client-to-server OP_Packet."""
        if self.cs_offset:
            self._shift_packet_seq(buf, offset, self.cs_offset)

    def adjust_server_ack(
        self,
        buf: bytearray,
        offset: int = 0,
    ) -> None:
        """Translate a server-to-client ACK back to the client's seq space.

        After the SSO retry has fired, the server's outgoing ACKs reference
        sequences that are ``cs_offset`` ahead of what the client knows it
        sent. Subtract that offset so the client sees ACKs for sequences it
        actually issued.
        """
        if not self.cs_offset:
            return
        cur = soe.get_sequence(buf, offset)
        new_seq = max(cur - self.cs_offset, 0)
        soe.set_sequence(buf, offset, new_seq)

    def _rewrite_ack(
        self,
        buf: bytearray,
        offset: int,
    ) -> None:
        """Translate client-side ACK sequence to the server's
        space."""
        new_seq = max(self.seq_from_server - 1, 0)
        soe.set_sequence(buf, offset, new_seq)

    @staticmethod
    def _shift_packet_seq(buf: bytearray, offset: int, delta: int) -> None:
        """Shift the 2-byte BE sequence field of an OP_Packet/OP_Fragment
        starting at *offset* by *delta*."""
        cur = soe.get_sequence(buf, offset)
        soe.set_sequence(buf, offset, (cur + delta) & 0xFFFF)

    # ------------------------------------------------------------------
    # Retry bookkeeping
    # ------------------------------------------------------------------
    def note_suppressed_server_packet(self, server_seq: int) -> None:
        """Record that the proxy ate a S->C packet without forwarding it.

        Advances ``seq_from_server`` past the suppressed sequence so future
        client ACKs (which the proxy rewrites to ``seq_from_server - 1``)
        correctly reference the suppressed packet, but leaves
        ``seq_to_client`` untouched so the next forwarded server packet
        slots into the sequence the client is already expecting.
        """
        # Be defensive: the suppressed packet's sequence might be ahead of
        # what we've seen if the server skipped one for any reason.
        self.seq_from_server = max(self.seq_from_server, server_seq + 1)

    def note_injected_client_packet(self) -> None:
        """Record that the proxy injected an extra C->S OP_Packet.

        Bumps ``cs_offset`` so all subsequent client-supplied OP_Packet
        sequences are shifted by the same amount before forwarding.
        """
        self.cs_offset += 1

    # ------------------------------------------------------------------
    # Server -> Client  (rewrite sequences, reassemble fragments)
    # ------------------------------------------------------------------
    def recv_combined(
        self,
        buf: bytearray,
        start_index: int = 0,
        length: int | None = None,
    ) -> bytearray | None:
        """Apply S->C rewrites to every sub-packet of an ``OP_Combined``.

        Rewrites are applied in place on *buf*; the (possibly trimmed) buffer
        is returned so the caller can forward it once. Returns ``None`` if
        the Combined contains a sub-packet that should not be forwarded
        (e.g. a non-final ``OP_Fragment``).

        Unlike the previous fan-out callback model, this method emits a
        single output datagram per input Combined. Sending one Combined
        twice (once with raw inner sequences, once with rewrites applied)
        was harmless when server-seq == client-seq but caused the EQ client
        to stall on out-of-order sequences after the SSO retry had shifted
        sequences.
        """
        if length is None:
            length = len(buf) - start_index

        combined = soe.CombinedPacket.parse(buf, start_index, length)
        for sub in combined:
            if sub.transport_op == soe.TransportOp.Ack:
                self.adjust_server_ack(buf, sub.offset)
            elif sub.transport_op == soe.TransportOp.Packet:
                self._rewrite_server_packet_seq(buf, sub.offset)
            elif sub.transport_op == soe.TransportOp.Fragment:
                # Fragments inside Combineds are uncommon in this protocol;
                # the server list is sent as standalone Fragments. If we
                # ever see one here, leave it alone and forward as-is.
                logger.debug("Unexpected Fragment inside server Combined; forwarding raw")

        if start_index == 0 and length == len(buf):
            return buf
        # Return just the relevant slice so we don't leak any leading or
        # trailing bytes from the outer datagram.
        return bytearray(buf[start_index : start_index + length])

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
        self._rewrite_server_packet_seq(buf, start_index)
        return None

    def _rewrite_server_packet_seq(self, buf: bytearray, offset: int) -> None:
        """Translate a S->C OP_Packet sequence to the client's space.

        Always advances ``seq_to_client`` (the client's view of the next
        sequence number, regardless of whether the proxy has consumed any
        server sequences). Advances ``seq_from_server`` only when the
        server's sequence matches what we expected next; out-of-order
        packets are still rewritten so the client sees a coherent stream
        but ``seq_from_server`` is not bumped past a gap.
        """
        server_seq = soe.get_sequence(buf, offset)
        soe.set_sequence(buf, offset, self.seq_to_client)
        self.seq_to_client += 1

        if server_seq != self.seq_from_server:
            logger.debug(
                "Out-of-order OP_Packet seq=%d expected=%d",
                server_seq,
                self.seq_from_server,
            )
            return
        self.seq_from_server += 1

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
