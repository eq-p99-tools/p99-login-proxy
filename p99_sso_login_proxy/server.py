# Based in large part on the original work by Zaela:
# https://github.com/Zaela/p99-login-middlemand
from __future__ import annotations

import asyncio
import functools
import logging
import time

from p99_sso_login_proxy import config, eq_config, sequence, sso_api, ui
from p99_sso_login_proxy import soe_protocol as soe, login_protocol as lp

logger = logging.getLogger(__name__)


def debug_write_packet(buf: bytes, login_to_client):
    length = len(buf)
    direction = "LOGIN to CLIENT" if login_to_client else "CLIENT to LOGIN"
    lines = [f"{time.time()} {direction} (len {length}):"]
    remaining = length
    print_chars = 64
    for i in range(0, length, 64):
        if remaining > 64:
            remaining -= 64
        else:
            print_chars = remaining
        hex_part = " ".join(
            f"{x:02x}".upper()
            for x in buf[i:i + print_chars]
        )
        ascii_part = "".join(
            chr(x) if 32 <= x < 127 else "."
            for x in buf[i:i + print_chars]
        )
        lines.append(f"{hex_part}  {ascii_part}")
    logger.debug("\n".join(lines))


class LoginProxy(asyncio.DatagramProtocol):
    transport: asyncio.DatagramTransport
    last_recv_time: float
    in_session: bool
    sequence: sequence.Sequence
    client_addr: tuple[str, int] | None

    def __init__(self):
        super().__init__()
        self.in_session = False
        self.last_recv_time = 0.0
        self.sequence = sequence.Sequence()
        # Update UI stats
        ui.PROXY_STATS.update_status("Initializing")

    def sequence_free(self):
        self.sequence.reset()

    def connection_made(self, transport):
        self.transport = transport
        # Update UI stats with listening information
        local_addr = transport.get_extra_info("sockname")
        if local_addr:
            host, port = local_addr
            ui.PROXY_STATS.update_listening_info(host, port)
            ui.PROXY_STATS.update_status("Listening")
        logger.info("Proxy listening on %s", local_addr)

    # ------------------------------------------------------------------
    # Auth credential rewrite
    # ------------------------------------------------------------------
    def check_rewrite_auth(self, buf: bytearray) -> bytearray:
        """Detect a login packet, decrypt credentials, optionally
        rewrite with SSO or local-account credentials, and
        re-encrypt."""
        if len(buf) < 30:
            return buf

        if not lp.is_combined_login_packet(buf):
            return buf

        sub2, sub2_offset, sub2_len = (
            lp.extract_login_from_combined(buf)
        )

        # OP_Packet header(4) + app opcode(2) + LoginBaseMessage
        enc_offset = 4 + 2 + lp.LOGIN_BASE_SIZE
        if len(sub2) <= enc_offset:
            return buf
        encrypted = sub2[enc_offset:]

        username, password = lp.decrypt_login_credentials(
            encrypted, config.ENCRYPTION_KEY, config.iv())

        username = username.lower()
        result_buf = buf
        effective_account = username
        method = None

        if config.PROXY_ONLY:
            logger.debug(
                "Proxy only mode enabled, skipping SSO API call.")
            method = "proxy_only"
        elif username in config.SKIP_SSO_ACCOUNTS:
            logger.debug(
                "Skipping SSO check for %s (in skip list)",
                username)
            method = "skip_sso"
        elif (username not in config.ALL_CACHED_NAMES
              and username not in config.LOCAL_ACCOUNT_NAME_MAP):
            logger.debug(
                "Skipping SSO check for %s"
                " (not in cached account list)", username)
            method = "passthrough"
        else:
            try:
                new_user = None
                new_pass = None

                if username in config.LOCAL_ACCOUNT_NAME_MAP:
                    new_user = (
                        config.LOCAL_ACCOUNT_NAME_MAP[username])
                    new_pass = (
                        config.LOCAL_ACCOUNTS[new_user]["password"])
                    logger.info(
                        "Overwriting client supplied password"
                        " with local account for %s: %s",
                        username, new_user)
                elif config.USER_API_TOKEN:
                    new_user, new_pass, error_detail = (
                        sso_api.check_sso_login(
                            username,
                            config.USER_API_TOKEN,
                            client_settings=(
                                eq_config.get_client_settings()),
                        ))
                    if error_detail:
                        logger.warning(
                            "SSO login rejected for %s: %s",
                            username, error_detail)
                        ui.PROXY_STATS.auth_error(
                            username, error_detail)

                if new_user and new_pass:
                    logger.info(
                        "Auth rewrite successful for %s -> %s",
                        username, new_user)
                    new_encrypted = lp.encrypt_login_credentials(
                        new_user, new_pass,
                        config.ENCRYPTION_KEY, config.iv())

                    abs_enc_start = sub2_offset + enc_offset
                    abs_enc_end = sub2_offset + sub2_len
                    result_buf = bytearray(
                        buf[:abs_enc_start]
                        + new_encrypted
                        + buf[abs_enc_end:]
                    )

                    new_sub2_len = (
                        enc_offset + len(new_encrypted))
                    result_buf[sub2_offset - 1] = new_sub2_len

                    effective_account = new_user
                    method = (
                        "local"
                        if username in config.LOCAL_ACCOUNT_NAME_MAP
                        else "sso")
            except Exception:
                logger.exception(
                    "Failed to check login for %s", username)

        if method:
            ui.PROXY_STATS.user_login(
                alias=username,
                account=effective_account,
                method=method)

        return result_buf

    # ------------------------------------------------------------------
    # Client -> Login Server
    # ------------------------------------------------------------------
    def handle_client_packet(
        self, data: bytearray, addr: tuple[str, int],
    ):
        """Called on a packet from the client"""
        recv_time = time.time()
        # debug_write_packet(data, False)

        logger.debug("Received data from client %s", addr)

        # Store client address for responses
        self.client_addr = addr

        if not self.in_session or (
            recv_time - self.last_recv_time
        ) > 60:
            logger.debug(
                "Session reset needed:"
                " in_session=%s, time_since_last=%.2fs",
                self.in_session,
                recv_time - self.last_recv_time,
            )
            self.sequence_free()
            if not self.in_session:
                # New connection
                logger.debug(
                    "New connection established, updating stats")
                ui.PROXY_STATS.connection_started()

        opcode = soe.get_transport_opcode(data)
        logger.debug(
            "Processing client packet with opcode: %s",
            soe.transport_name(opcode))

        if opcode == soe.TransportOp.Combined:
            logger.debug("Adjusting combined packet sequence")
            self.sequence.adjust_combined(data)
            original_data = data.copy()
            data = self.check_rewrite_auth(data)
            if data != original_data:
                logger.debug("Authentication data rewritten")

        elif opcode == soe.TransportOp.SessionDisconnect:
            logger.debug(
                "Session disconnect received, cleaning up")
            self.in_session = False
            self.sequence_free()
            # Update UI stats for completed connection
            ui.PROXY_STATS.connection_completed()

        elif opcode == soe.TransportOp.Ack:
            logger.debug("Adjusting ACK sequence values")
            self.sequence.adjust_ack(data)

        elif opcode == soe.TransportOp.KeepAlive:
            logger.debug("Keep-alive packet received")

        self.last_recv_time = recv_time
        logger.debug("Forwarding processed packet to login server")
        self.send_to_loginserver(data)

    # ------------------------------------------------------------------
    # Login Server -> Client
    # ------------------------------------------------------------------
    def handle_server_packet(
        self,
        data: bytes,
        addr: tuple[str, int],
        start_index: int = 0,
        length: int | None = None,
    ):
        """Handle packets from the login server"""
        if length is None:
            length = len(data)
        # debug_write_packet(data, True)
        data = bytearray(data)
        logger.debug(
            "Received message from login server: %s", data)
        opcode = soe.get_transport_opcode(data[start_index:])

        logger.debug(
            "Processing server packet with opcode: %s",
            soe.transport_name(opcode))

        if opcode == soe.TransportOp.SessionResponse:
            self.in_session = True
            self.sequence_free()
            logger.debug(
                "Session response received, session established")

        elif opcode == soe.TransportOp.Combined:
            logger.debug(
                "Received combined packet,"
                " splitting into individual packets")
            self.sequence.recv_combined(
                data,
                functools.partial(self.handle_server_packet),
                start_index, length,
            )
            # Pieces will be forwarded individually
            return

        elif opcode == soe.TransportOp.Packet:
            logger.debug("Processing standard packet")
            maybe_server_list = self.sequence.recv_packet(
                data, start_index, length)
            if maybe_server_list is not None:
                data = maybe_server_list
                logger.debug(
                    "Server list packet detected and processed")

        elif opcode == soe.TransportOp.Fragment:
            logger.debug("Processing fragment packet")
            maybe_server_list = self.sequence.recv_fragment(
                data, start_index, length)
            if maybe_server_list is not None:
                # We're finished with the server list, forward it
                data = maybe_server_list
                logger.debug(
                    "Server list fragments complete,"
                    " forwarding to client")
            else:
                # Don't forward, whole point is to filter this
                logger.debug(
                    "Fragment part of server list,"
                    " not forwarding individually")
                return

        elif opcode == soe.TransportOp.Ack:
            logger.debug("Skipping server ACK packet")
            return

        logger.debug("Forwarding processed packet to client")
        self.send_to_client(data)

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------
    def datagram_received(
        self, data: bytes, addr: tuple[str, int],
    ) -> None:
        """Called when a datagram is received"""
        if addr == config.EQEMU_ADDR:
            # Packet from login server
            self.handle_server_packet(data, addr)
        else:
            # Packet from client
            self.handle_client_packet(bytearray(data), addr)

    def send_to_client(self, data: bytearray | bytes):
        if not data or not self.client_addr:
            logger.debug(
                "Empty data or no client address,"
                " not sending to client")
            return
        logger.debug(
            "Sending data to client %s: %s",
            self.client_addr, data)
        self.transport.sendto(data, self.client_addr)

    def send_to_loginserver(self, data: bytearray | bytes):
        if not data:
            logger.debug(
                "Empty data, not sending to loginserver")
            return
        logger.debug("Sending data to loginserver: %s", data)
        self.transport.sendto(data, config.EQEMU_ADDR)


async def main():
    # Update UI status
    ui.PROXY_STATS.update_status("Starting")
    logger.info("Starting proxy server")

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        LoginProxy,
        local_addr=(config.LISTEN_HOST, config.LISTEN_PORT),
    )
    logger.info(
        "Started UDP proxy, listening on %s:%s",
        config.LISTEN_HOST, config.LISTEN_PORT)
    ui.PROXY_STATS.reset_uptime()

    return transport
