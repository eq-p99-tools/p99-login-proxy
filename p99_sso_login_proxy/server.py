# Based in large part on the original work by Zaela:
# https://github.com/Zaela/p99-login-middlemand
from __future__ import annotations

import asyncio
import functools
import logging
import time

from Cryptodome.Cipher import DES

from p99_sso_login_proxy import config, sequence, sso_api, structs, ui

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
        hex_part = " ".join(f"{x:02x}".upper() for x in buf[i : i + print_chars])
        ascii_part = "".join(chr(x) if 32 <= x < 127 else "." for x in buf[i : i + print_chars])
        lines.append(f"{hex_part}  {ascii_part}")
    logger.debug("\n".join(lines))


class LoginProxy(asyncio.DatagramProtocol):
    transport: asyncio.DatagramTransport
    last_recv_time: time
    in_session: bool
    sequence: sequence.Sequence
    client_addr: tuple[str, int] = None

    def __init__(self):
        super().__init__()
        self.in_session = False
        self.last_recv_time = 0
        self.sequence = sequence.Sequence()
        # Update UI stats
        ui.PROXY_STATS.update_status("Initializing")

    def sequence_free(self):
        if not self.sequence.packets:
            return
        self.sequence.packets.clear()
        self.sequence = sequence.Sequence()

    def connection_made(self, transport):
        self.transport = transport
        # Update UI stats with listening information
        local_addr = transport.get_extra_info("sockname")
        if local_addr:
            host, port = local_addr
            ui.PROXY_STATS.update_listening_info(host, port)
            ui.PROXY_STATS.update_status("Listening")
        logger.info("Proxy listening on %s", local_addr)

    def check_rewrite_auth(self, buf: bytearray):
        """
        struct LoginBaseMessage_Struct {
            int32_t sequence;     // request type/login sequence (2: handshake, 3: login, 4: serverlist, ...)
            bool    compressed;   // true: deflated
            int8_t  encrypt_type; // 1: invert (unused) 2: des (2 for encrypted player logins and order expansions)
                                  // (client uses what it sent, ignores in reply)
            int32_t unk3;         // unused?
        };

        sequence = \x00\x03\x04\x00
        compressed = \x15
        encrypt_type = \x00
        unk3 = \x00\x28\x00\x09
        """
        if len(buf) < 30:
            return buf
        elif buf.startswith(b"\x00\x03\x04\x00\x15\x00"):
            # LOGIN packet
            data = buf[14 + structs.SIZE_OF_LOGIN_BASE_MESSAGE :]
            cipher = DES.new(config.ENCRYPTION_KEY, DES.MODE_CBC, config.iv())
            decrypted_text = cipher.decrypt(data)
            user, password = decrypted_text.rstrip(b"\x00").split(b"\x00")

            # Notify UI about user login
            username = user.decode().lower()
            password = password.decode()
            ui.PROXY_STATS.user_login(username)

            # No SSO at all, just return the packet
            if config.PROXY_ONLY:
                logger.debug("Proxy only mode enabled, skipping SSO API call.")
                return buf

            # First skip processing any explicitly called out account names
            if username in config.SKIP_SSO_ACCOUNTS:
                logger.debug("Skipping SSO check for %s (in skip list)", username)
                return buf

            # Next skip processing any accounts that are not in the cached account list or local account list
            if username not in config.ALL_CACHED_NAMES and username not in config.LOCAL_ACCOUNT_NAME_MAP:
                logger.debug("Skipping SSO check for %s (not in cached account list)", username)
                return buf

            try:
                new_user = None
                new_pass = None

                # If this is a local account, just use that
                if username in config.LOCAL_ACCOUNT_NAME_MAP:
                    new_user = config.LOCAL_ACCOUNT_NAME_MAP[username]
                    new_pass = config.LOCAL_ACCOUNTS[new_user]["password"]
                    logger.info(
                        "Overwriting client supplied password with local account for %s: %s", username, new_user
                    )
                # If a user API token is provided, use it instead of the password
                elif config.USER_API_TOKEN:
                    new_user, new_pass = sso_api.check_sso_login(username, config.USER_API_TOKEN)
                    logger.info("Overwriting client supplied password with SSO password for %s: %s", username, new_user)

                if new_user and new_pass:
                    logger.info("Auth rewrite successful for %s, replacing password.", username)
                    cipher = DES.new(config.ENCRYPTION_KEY, DES.MODE_CBC, config.iv())
                    plaintext = new_user.encode() + b"\x00" + new_pass.encode() + b"\x00"
                    padded_plaintext = plaintext.ljust((int(len(plaintext) / 8) + 1) * 8, b"\x00")
                    encrypted_text = cipher.encrypt(padded_plaintext)
                    new_login = buf[: 14 + structs.SIZE_OF_LOGIN_BASE_MESSAGE] + encrypted_text
                    new_login[7] = len(new_login) - 8
                    ui.PROXY_STATS.user_login(new_user)
                    return new_login
            except Exception:
                logger.exception("Failed to check login for %s", username)

        return buf

    def handle_client_packet(self, data: bytearray, addr: tuple[str, int]):
        """Called on a packet from the client"""
        recv_time = time.time()
        # debug_write_packet(data, False)

        logger.debug("Received data from client %s", addr)

        # Store client address for responses
        self.client_addr = addr

        if not self.in_session or (recv_time - self.last_recv_time) > 60:
            logger.debug(
                "Session reset needed: in_session=%s, time_since_last=%.2fs",
                self.in_session,
                recv_time - self.last_recv_time,
            )
            self.sequence_free()
            if not self.in_session:
                # New connection
                logger.debug("New connection established, updating stats")
                ui.PROXY_STATS.connection_started()

        # From recv_from_local
        opcode = structs.get_protocol_opcode(data)
        logger.debug("Processing client packet with opcode: %s", opcode)

        if opcode == structs.OPCodes.OP_Combined:
            logger.debug("Adjusting combined packet sequence")
            self.sequence.adjust_combined(data)
            original_data = data.copy()
            data = self.check_rewrite_auth(data)
            if data != original_data:
                logger.debug("Authentication data rewritten")
        elif opcode == structs.OPCodes.OP_SessionDisconnect:
            logger.debug("Session disconnect received, cleaning up")
            self.in_session = False
            self.sequence_free()
            # Update UI stats for completed connection
            ui.PROXY_STATS.connection_completed()
        elif opcode == structs.OPCodes.OP_Ack:
            logger.debug("Adjusting ACK sequence values")
            # Rewrite client-to-server ack sequence values, since we will be desynchronizing them
            self.sequence.adjust_ack(data, 0, len(data))
        elif opcode == structs.OPCodes.OP_KeepAlive:
            logger.debug("Keep-alive packet received")

        self.last_recv_time = recv_time
        logger.debug("Forwarding processed packet to login server")
        self.send_to_loginserver(data)

    def send_to_client(self, data: bytearray):
        if not data or not self.client_addr:
            logger.debug("Empty data or no client address, not sending to client")
            return
        logger.debug("Sending data to client %s: %s", self.client_addr, data)
        self.transport.sendto(data, self.client_addr)

    def send_to_loginserver(self, data: bytearray):
        if not data:
            logger.debug("Empty data, not sending to loginserver")
            return
        logger.debug("Sending data to loginserver: %s", data)
        self.transport.sendto(data, config.EQEMU_ADDR)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Called when a datagram is received"""
        if addr == config.EQEMU_ADDR:
            # Packet from login server
            self.handle_server_packet(data, addr)
        else:
            # Packet from client
            self.handle_client_packet(bytearray(data), addr)

    def handle_server_packet(self, data: bytes, addr: tuple[str, int], start_index=0, length=None):
        """Handle packets from the login server"""
        if length is None:
            length = len(data)
        # debug_write_packet(data, True)
        data = bytearray(data)
        logger.debug("Received message from login server: %s", data)
        opcode = structs.get_protocol_opcode(data[start_index:])

        logger.debug("Processing server packet with opcode: %s", opcode)
        if opcode == structs.OPCodes.OP_SessionResponse:
            self.in_session = True
            self.sequence_free()
            logger.debug("Session response received, session established")
        elif opcode == structs.OPCodes.OP_Combined:
            logger.debug("Received combined packet, splitting into individual packets")
            self.sequence.recv_combined(data, functools.partial(self.handle_server_packet), start_index, length)
            # Pieces will be forwarded individually
            return
        elif opcode == structs.OPCodes.OP_Packet:
            logger.debug("Processing standard packet")
            maybe_server_list = self.sequence.recv_packet(data, start_index, length)
            if maybe_server_list is not None:
                # don't double-send packet after server-list?
                data = maybe_server_list
                logger.debug("Server list packet detected and processed")
        elif opcode == structs.OPCodes.OP_Fragment:
            logger.debug("Processing fragment packet")
            # must be one of the server list packets
            maybe_server_list = self.sequence.recv_fragment(data, start_index, length)
            if maybe_server_list is not None:
                # We're finished with the server list, forward it
                data = maybe_server_list
                logger.debug("Server list fragments complete, forwarding to client")
            else:
                # Don't forward, whole point is to filter this
                logger.debug("Fragment part of server list, not forwarding individually")
                return
        elif opcode == structs.OPCodes.OP_Ack:
            logger.debug("Skipping server ACK packet")
            return
        logger.debug("Forwarding processed packet to client")
        self.send_to_client(data)


async def main():
    # Update UI status
    ui.PROXY_STATS.update_status("Starting")
    logger.info("Starting proxy server")

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(LoginProxy, local_addr=(config.LISTEN_HOST, config.LISTEN_PORT))
    logger.info("Started UDP proxy, listening on %s:%s", config.LISTEN_HOST, config.LISTEN_PORT)
    ui.PROXY_STATS.reset_uptime()

    return transport
