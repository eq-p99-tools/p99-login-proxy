# Based in large part on the original work by Zaela:
# https://github.com/Zaela/p99-login-middlemand
from __future__ import annotations
import asyncio
import functools
import time

from Cryptodome.Cipher import DES

from p99_sso_login_proxy import config
from p99_sso_login_proxy import sequence
from p99_sso_login_proxy import sso_api
from p99_sso_login_proxy import structs
from p99_sso_login_proxy import ui

# import faulthandler
# faulthandler.enable()


def debug_write_packet(buf: bytes, login_to_client):
    print(f"{time.time()} ", end="")
    length = len(buf)
    if login_to_client:
        print(f"LOGIN to CLIENT (len {length}):")
    else:
        print(f"CLIENT to LOGIN (len {length}):")

    remaining = length
    print_chars = 64
    for i in range(0, length, 64):
        if remaining > 64:
            remaining -= 64
        else:
            print_chars = remaining
        print(" ".join(f"{x:02x}".upper() for x in buf[i:i + print_chars]), end="  ")
        print("".join(chr(x) if 32 <= x < 127 else '.' for x in buf[i:i + print_chars]))


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
        ui.proxy_stats.update_status("Initializing")

    def sequence_free(self):
        if not self.sequence.packets:
            return
        self.sequence.packets.clear()
        self.sequence = sequence.Sequence()

    def connection_made(self, transport):
        self.transport = transport
        # Update UI stats with listening information
        local_addr = transport.get_extra_info('sockname')
        if local_addr:
            host, port = local_addr
            ui.proxy_stats.update_listening_info(host, port)
            ui.proxy_stats.update_status("Listening")
        print(f"Proxy listening on {local_addr}")

    def check_rewrite_auth(self, buf: bytearray):
        """
        struct LoginBaseMessage_Struct {
            int32_t sequence;     // request type/login sequence (2: handshake, 3: login, 4: serverlist, ...)
            bool    compressed;   // true: deflated
            int8_t  encrypt_type; // 1: invert (unused) 2: des (2 for encrypted player logins and order expansions) (client uses what it sent, ignores in reply)
            int32_t unk3;         // unused?
        };

        sequence = \x00\x03\x04\x00
        compressed = \x15
        encrypt_type = \x00
        unk3 = \x00\x28\x00\x09
        """
        if len(buf) < 30:
            return buf
        elif buf.startswith(b'\x00\x03\x04\x00\x15\x00'):
            # LOGIN packet
            data = buf[14 + structs.SIZE_OF_LOGIN_BASE_MESSAGE:]
            cipher = DES.new(config.ENCRYPTION_KEY, DES.MODE_CBC, config.iv())
            decrypted_text = cipher.decrypt(data)
            user, password = decrypted_text.rstrip(b'\x00').split(b'\x00')

            # Notify UI about user login
            username = user.decode().lower()
            password = password.decode()
            ui.proxy_stats.user_login(username)

            # No SSO at all, just return the packet
            if config.PROXY_ONLY:
                print(f"[CHECK REWRITE] Proxy only mode enabled, skipping SSO API call.")
                return buf

            # First skip processing any explicitly called out account names
            if username in config.SKIP_SSO_ACCOUNTS:
                print(f"[CHECK REWRITE] Skipping SSO check for {username} (in skip list)")
                return buf

            # Next skip processing any accounts that are not in the cached account list or local account list
            if username not in config.ALL_CACHED_NAMES and username not in config.LOCAL_ACCOUNT_NAME_MAP:
                print(f"[CHECK REWRITE] Skipping SSO check for {username} (not in cached account list)")
                return buf

            try:
                # If this is a local account, just use that
                if username in config.LOCAL_ACCOUNT_NAME_MAP:
                    new_user = config.LOCAL_ACCOUNT_NAME_MAP[username]
                    new_pass = config.LOCAL_ACCOUNTS[new_user]["password"]
                    print(f"[CHECK REWRITE] Overwriting client supplied password with local account for {username}: {new_user}")
                # If a user API token is provided, use it instead of the password
                elif config.USER_API_TOKEN:
                    new_user, new_pass = sso_api.check_sso_login(username, config.USER_API_TOKEN)
                    print(f"[CHECK REWRITE] Overwriting client supplied password with SSO password for {username}: {new_user}")

                if new_user and new_pass:
                    print(f"[CHECK REWRITE] CHECK SUCCESSFUL: {username} found, replacing password.")
                    cipher = DES.new(config.ENCRYPTION_KEY, DES.MODE_CBC, config.iv())
                    plaintext = new_user.encode() + b'\x00' + new_pass.encode() + b'\x00'
                    padded_plaintext = plaintext.ljust((int(len(plaintext) / 8) + 1) * 8, b'\x00')
                    encrypted_text = cipher.encrypt(padded_plaintext)
                    new_login = buf[:14 + structs.SIZE_OF_LOGIN_BASE_MESSAGE] + encrypted_text
                    new_login[7] = len(new_login) - 8
                    ui.proxy_stats.user_login(new_user)
                    return new_login
            except Exception as e:
                print(f"[CHECK REWRITE] FAILED TO CHECK LOGIN: {username}, error: {str(e)}")

        return buf

    def handle_client_packet(self, data: bytearray, addr: tuple[str, int]):
        """Called on a packet from the client"""
        recv_time = time.time()
        # debug_write_packet(data, False)
        
        print(f"[CLIENT PACKET] Received data from client {addr}")
        
        # Store client address for responses
        self.client_addr = addr
        
        if not self.in_session or (recv_time - self.last_recv_time) > 60:
            print(f"[CLIENT PACKET] Session reset needed: in_session={self.in_session}, time_since_last={recv_time - self.last_recv_time:.2f}s")
            self.sequence_free()
            if not self.in_session:
                # New connection
                print("[CLIENT PACKET] New connection established, updating stats")
                ui.proxy_stats.connection_started()

        # From recv_from_local
        opcode = structs.get_protocol_opcode(data)
        print(f"[CLIENT PACKET] Processing packet with opcode: {opcode}")
        
        if opcode == structs.OPCodes.OP_Combined:
            print("[CLIENT PACKET] Adjusting combined packet sequence")
            self.sequence.adjust_combined(data)
            original_data = data.copy()
            data = self.check_rewrite_auth(data)
            if data != original_data:
                print("[CLIENT PACKET] Authentication data rewritten")
        elif opcode == structs.OPCodes.OP_SessionDisconnect:
            print("[CLIENT PACKET] Session disconnect received, cleaning up")
            self.in_session = False
            self.sequence_free()
            # Update UI stats for completed connection
            ui.proxy_stats.connection_completed()
        elif opcode == structs.OPCodes.OP_Ack:
            print("[CLIENT PACKET] Adjusting ACK sequence values")
            # Rewrite client-to-server ack sequence values, since we will be desynchronizing them
            self.sequence.adjust_ack(data, 0, len(data))
        elif opcode == structs.OPCodes.OP_KeepAlive:
            print("[CLIENT PACKET] Keep-alive packet received")

        self.last_recv_time = recv_time
        print("[CLIENT PACKET] Forwarding processed packet to login server")
        self.send_to_loginserver(data)

    def send_to_client(self, data: bytearray):
        if not data or not self.client_addr:
            print("[SEND TO CLIENT] Empty data or no client address, not sending to client")
            return
        print(f"[SEND TO CLIENT] Sending data to client {self.client_addr}.")
        # print(f"[SEND TO CLIENT] Sending data to client {self.client_addr}: {data}")
        self.transport.sendto(data, self.client_addr)

    def send_to_loginserver(self, data: bytearray):
        if not data:
            print("[SEND TO LOGINSERVER] Empty data, not sending to loginserver")
            return
        print(f"[SEND TO LOGINSERVER] Sending data to loginserver.")
        # print(f"[SEND TO LOGINSERVER] Sending data to loginserver: {data}")
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
        print(f"[SERVER PACKET] Received message from login server.")
        # print(f"[SERVER PACKET] Received message from login server: {data}")
        opcode = structs.get_protocol_opcode(data[start_index:])

        print(f"[SERVER PACKET] Processing packet with opcode: {opcode}")
        if opcode == structs.OPCodes.OP_SessionResponse:
            self.in_session = True
            self.sequence_free()
            print("[SERVER PACKET] Session response received, session established")
        elif opcode == structs.OPCodes.OP_Combined:
            print("[SERVER PACKET] Received combined packet, splitting into individual packets")
            self.sequence.recv_combined(data, functools.partial(self.handle_server_packet), start_index, length)
            # Pieces will be forwarded individually
            return
        elif opcode == structs.OPCodes.OP_Packet:
            print("[SERVER PACKET] Processing standard packet")
            maybe_server_list = self.sequence.recv_packet(data, start_index, length)
            if maybe_server_list is not None:
                # don't double-send packet after server-list?
                data = maybe_server_list
                print("[SERVER PACKET] Server list packet detected and processed")
        elif opcode == structs.OPCodes.OP_Fragment:
            print("[SERVER PACKET] Processing fragment packet")
            # must be one of the server list packets
            maybe_server_list = self.sequence.recv_fragment(data, start_index, length)
            if maybe_server_list is not None:
                # We're finished with the server list, forward it
                data = maybe_server_list
                print("[SERVER PACKET] Server list fragments complete, forwarding to client")
            else:
                # Don't forward, whole point is to filter this
                print("[SERVER PACKET] Fragment part of server list, not forwarding individually")
                return
        elif opcode == structs.OPCodes.OP_Ack:
            print("[SERVER PACKET] Skipping server ACK packet")
            return
        print("[SERVER PACKET] Forwarding processed packet to client")
        self.send_to_client(data)


async def shutdown(transport):
    print("[SERVER SHUTDOWN] Shutting down proxy...")
    ui.proxy_stats.update_status("Shutting down")
    transport.close()
    loop = asyncio.get_running_loop()
    loop.close()


async def main():
    # Update UI status
    ui.proxy_stats.update_status("Starting")
    print("[SERVER] Starting proxy server main function")
    
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        LoginProxy, local_addr=(config.LISTEN_HOST, config.LISTEN_PORT))
    print(f"Started UDP proxy, listening on {config.LISTEN_HOST}:{config.LISTEN_PORT}")
    ui.proxy_stats.reset_uptime()
    
    return transport
