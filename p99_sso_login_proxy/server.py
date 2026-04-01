# Based in large part on the original work by Zaela:
# https://github.com/Zaela/p99-login-middlemand
from __future__ import annotations

import asyncio
import functools
import logging
import time

from p99_sso_login_proxy import config, ui, ws_client
from p99_sso_login_proxy import soe_protocol as soe
from p99_sso_login_proxy.login_protocol import LoginPacket
from p99_sso_login_proxy.session import ProxySessionState

logger = logging.getLogger("server")


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
    session: ProxySessionState
    client_addr: tuple[str, int] | None

    def __init__(self):
        super().__init__()
        self.in_session = False
        self.last_recv_time = 0.0
        self.session = ProxySessionState()
        self._auth_in_flight = False
        self._auth_task: asyncio.Task | None = None
        ui.PROXY_STATS.update_status("Initializing")

    def session_free(self):
        self.session.reset()

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
    def _needs_sso(self, username: str) -> bool:
        """Return True if *username* should go through the SSO API."""
        return (
            not config.PROXY_ONLY
            and username not in config.SKIP_SSO_ACCOUNTS
            and username not in config.LOCAL_ACCOUNT_NAME_MAP
            and username in config.ALL_CACHED_NAMES
            and bool(config.USER_API_TOKEN)
        )

    def _try_sync_rewrite(
        self, buf: bytearray, login: LoginPacket,
    ) -> tuple[bytearray, str | None]:
        """Handle non-SSO credential rewrites synchronously.

        Returns ``(result_buf, method)`` where *method* is a non-None
        string if the packet was handled (forwarding should proceed),
        or ``None`` if the caller should attempt SSO auth instead.
        """
        username = login.username.lower()

        if config.PROXY_ONLY:
            ui.PROXY_STATS.user_login(
                alias=username, account=username,
                method="proxy_only")
            return buf, "proxy_only"

        if username in config.SKIP_SSO_ACCOUNTS:
            ui.PROXY_STATS.user_login(
                alias=username, account=username,
                method="skip_sso")
            return buf, "skip_sso"

        if (username not in config.ALL_CACHED_NAMES
                and username not in config.LOCAL_ACCOUNT_NAME_MAP):
            ui.PROXY_STATS.user_login(
                alias=username, account=username,
                method="passthrough")
            return buf, "passthrough"

        if username in config.LOCAL_ACCOUNT_NAME_MAP:
            new_user = config.LOCAL_ACCOUNT_NAME_MAP[username]
            new_pass = (
                config.LOCAL_ACCOUNTS[new_user]["password"])
            logger.info(
                "Overwriting client supplied password"
                " with local account for %s: %s",
                username, new_user)
            result_buf = login.rewrite_credentials(
                new_user, new_pass,
                config.ENCRYPTION_KEY, config.iv())
            ui.PROXY_STATS.user_login(
                alias=username,
                account=new_user,
                method="local")
            return result_buf, "local"

        return buf, None

    async def _async_auth_and_forward(
        self,
        data: bytearray,
        login: LoginPacket,
        recv_time: float,
    ) -> None:
        """Perform SSO auth over WebSocket and forward."""
        username = login.username.lower()
        try:
            new_user, encrypted, error_detail = (
                await ws_client.request_login_auth(username))

            if error_detail:
                logger.warning(
                    "SSO login rejected for %s: %s",
                    username, error_detail)
                ui.PROXY_STATS.auth_error(
                    username, error_detail)

            if new_user and encrypted:
                logger.info(
                    "Auth rewrite successful for %s -> %s",
                    username, new_user)
                data = login.splice_encrypted_credentials(
                    encrypted)
                ui.PROXY_STATS.user_login(
                    alias=username,
                    account=new_user,
                    method="sso")
        except Exception:
            logger.exception(
                "Failed to check login for %s", username)
        finally:
            self._auth_in_flight = False
            self.last_recv_time = recv_time
            self.send_to_loginserver(data)

    # ------------------------------------------------------------------
    # Client -> Login Server
    # ------------------------------------------------------------------
    def handle_client_packet(
        self, data: bytearray, addr: tuple[str, int],
    ):
        """Called on a packet from the client"""
        recv_time = time.time()
        # debug_write_packet(data, False)

        # logger.debug("Received data from client %s", addr)

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
            self.session_free()
            if not self.in_session:
                logger.debug(
                    "New connection established, updating stats")
                ui.PROXY_STATS.connection_started()

        opcode = soe.get_transport_opcode(data)
        logger.debug(
            "Processing client packet with opcode: %s",
            soe.transport_name(opcode))

        if opcode == soe.TransportOp.Combined:
            logger.debug("Adjusting combined packet sequence")
            self.session.adjust_combined(data)

            login = LoginPacket.parse(
                data, config.ENCRYPTION_KEY, config.iv())
            if login and self._needs_sso(login.username.lower()):
                if self._auth_in_flight:
                    self.last_recv_time = recv_time
                    logger.debug(
                        "Dropping retry login packet"
                        " (auth already in flight)")
                    return
                self._auth_in_flight = True
                self._auth_task = asyncio.ensure_future(
                    self._async_auth_and_forward(
                        data, login, recv_time))
                return

            if login:
                result_buf, _method = self._try_sync_rewrite(
                    data, login)
                if result_buf is not data:
                    data = result_buf
                    logger.debug("Authentication data rewritten")
            # Non-login Combined packets fall through

        elif opcode == soe.TransportOp.SessionDisconnect:
            logger.debug(
                "Session disconnect received, cleaning up")
            self.in_session = False
            self.session_free()
            ui.PROXY_STATS.connection_completed()

        elif opcode == soe.TransportOp.Ack:
            logger.debug("Adjusting ACK sequence values")
            self.session.adjust_ack(data)

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
        addr: tuple[str, int] | None = None,
        start_index: int = 0,
        length: int | None = None,
    ):
        """Handle packets from the login server"""
        if length is None:
            length = len(data)
        # debug_write_packet(data, True)
        data = bytearray(data)
        # logger.debug(
        #     "Received message from login server: %s", data)
        opcode = soe.get_transport_opcode(data[start_index:])

        if opcode != soe.TransportOp.Fragment:
            logger.debug(
                "Processing server packet with opcode: %s",
                soe.transport_name(opcode))

        if opcode == soe.TransportOp.SessionResponse:
            self.in_session = True
            self.session_free()
            logger.debug(
                "Session response received, session established")

        elif opcode == soe.TransportOp.Combined:
            logger.debug(
                "Received combined packet,"
                " splitting into individual packets")
            self.session.recv_combined(
                data,
                functools.partial(self.handle_server_packet),
                start_index, length,
            )
            # Pieces will be forwarded individually
            return

        elif opcode == soe.TransportOp.Packet:
            logger.debug("Processing standard packet")
            maybe_server_list = self.session.recv_packet(
                data, start_index, length)
            if maybe_server_list is not None:
                data = maybe_server_list
                logger.debug(
                    "Server list packet detected and processed")

        elif opcode == soe.TransportOp.Fragment:
            # logger.debug("Processing fragment packet")
            maybe_server_list = self.session.recv_fragment(
                data, start_index, length)
            if maybe_server_list is not None:
                # We're finished with the server list, forward it
                data = maybe_server_list
                logger.debug(
                    "Server list fragments complete,"
                    " forwarding to client")
            else:
                # Don't forward, whole point is to filter this
                # logger.debug(
                #     "Fragment part of server list,"
                #     " not forwarding individually")
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
        # logger.debug(
        #     "Sending data to client %s: %s",
        #     self.client_addr, data)
        self.transport.sendto(data, self.client_addr)

    def send_to_loginserver(self, data: bytearray | bytes):
        if not data:
            logger.debug(
                "Empty data, not sending to loginserver")
            return
        # logger.debug("Sending data to loginserver: %s", data)
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
