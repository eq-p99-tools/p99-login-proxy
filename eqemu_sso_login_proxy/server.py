from __future__ import annotations
import asyncio
import functools
import time
import socket

from Crypto.Cipher import DES

from eqemu_sso_login_proxy import config
from eqemu_sso_login_proxy import sequence
from eqemu_sso_login_proxy import structs
from eqemu_sso_login_proxy.ui import proxy_stats

import faulthandler
faulthandler.enable()

# Resolve the login server address via DNS
EQEMU_LOGIN_IP = socket.gethostbyname("login.eqemulator.net")
EQEMU_PORT = 5998
EQEMU_ADDR = (EQEMU_LOGIN_IP, EQEMU_PORT)


def debug_write_packet(buf: bytes, login_to_client):
    print(f"{time.time()} ", end="")
    length = len(buf)
    if login_to_client:
        print(f"LOGIN to CLIENT (len {length}):")
    else:
        print(f"CLIENT to LOGIN (len {length}):")

    # self.check_rewrite_auth(buf, start_index, length, login_to_client)
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
        proxy_stats.update_status("Initializing")

    def sequence_free(self):
        if not self.sequence.packets:
            return
        for packet in self.sequence.packets:
            packet.data = None
        self.sequence = sequence.Sequence()

    def connection_made(self, transport):
        self.transport = transport
        # Update UI stats with listening information
        local_addr = transport.get_extra_info('sockname')
        if local_addr:
            host, port = local_addr
            proxy_stats.update_listening_info(host, port)
            proxy_stats.update_status("Listening")
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
        if buf.startswith(b'\x00\x03\x04\x00\x15\x00'):
            # LOGIN packet
            data = buf[14 + structs.SIZE_OF_LOGIN_BASE_MESSAGE:]
            buf_string = " ".join(f"{x:02x}".upper() for x in buf)
            cipher = DES.new(config.ENCRYPTION_KEY, DES.MODE_CBC, config.iv())
            decrypted_text = cipher.decrypt(data)
            user, password = decrypted_text.rstrip(b'\x00').split(b'\x00')
            
            # Notify UI about user login
            username = user.decode()
            proxy_stats.user_login(username)
            
            with open("login_packet.bin", "a") as f:
                f.write(f"{username}|{password.decode()}: {buf_string}\n")
            if username == "test" and password.decode() == "test":
                print("LOGIN:  test/test, replacing...")
                cipher = DES.new(config.ENCRYPTION_KEY, DES.MODE_CBC, config.iv())
                plaintext = config.TEST_USER + b'\x00' + config.TEST_PASSWORD + b'\x00'
                padded_plaintext = plaintext.ljust((int(len(plaintext) / 8) + 1) * 8, b'\x00')
                encrypted_text = cipher.encrypt(padded_plaintext)
                new_login = buf[:14 + structs.SIZE_OF_LOGIN_BASE_MESSAGE] + encrypted_text
                new_login[7] = len(new_login) - 8
                return new_login

        return buf

    def handle_client_packet(self, data: bytearray, addr: tuple[str, int]):
        """Called on a packet from the client"""
        recv_time = time.time()
        debug_write_packet(data, False)
        
        # Store client address for responses
        self.client_addr = addr
        
        if not self.in_session or (recv_time - self.last_recv_time) > 60:
            self.sequence_free()
            if not self.in_session:
                # New connection
                proxy_stats.connection_started()

        # From recv_from_local
        opcode = structs.get_protocol_opcode(data)
        if opcode == structs.OPCodes.OP_Combined:
            self.sequence.adjust_combined(data)
            data = self.check_rewrite_auth(data)
        elif opcode == structs.OPCodes.OP_SessionDisconnect:
            self.in_session = False
            self.sequence_free()
            # Update UI stats for completed connection
            proxy_stats.connection_completed()
        elif opcode == structs.OPCodes.OP_Ack:
            # Rewrite client-to-server ack sequence values, since we will be desynchronizing them
            self.sequence.adjust_ack(data, 0, len(data))
        elif opcode == structs.OPCodes.OP_KeepAlive:
            print("Let's debug here and see about packet state")

        self.last_recv_time = recv_time
        self.send_to_loginserver(data)

    def send_to_client(self, data: bytearray):
        if not data or not self.client_addr:
            print("Empty data or no client address, not sending to client")
            return
        print(f"Sending data to client {self.client_addr}: {data}")
        self.transport.sendto(data, self.client_addr)

    def send_to_loginserver(self, data: bytearray):
        if not data:
            print("Empty data, not sending to loginserver")
            return
        print(f"Sending data to loginserver: {data}")
        self.transport.sendto(data, EQEMU_ADDR)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Called when a datagram is received"""
        if addr == EQEMU_ADDR:
            # Packet from login server
            self.handle_server_packet(data, addr)
        else:
            # Packet from client
            self.handle_client_packet(bytearray(data), addr)

    def handle_server_packet(self, data: bytes, addr: tuple[str, int], start_index=0, length=None):
        """Handle packets from the login server"""
        if length is None:
            length = len(data)
        debug_write_packet(data, True)
        data = bytearray(data)
        print(f"Received message from login server: {data}")
        opcode = structs.get_protocol_opcode(data[start_index:])

        print("Debug1")
        if opcode == structs.OPCodes.OP_SessionResponse:
            self.in_session = True
            self.sequence_free()
            print("Debug2")
        elif opcode == structs.OPCodes.OP_Combined:
            print("Debug4")
            self.sequence.recv_combined(data, functools.partial(self.handle_server_packet), start_index, length)
            # Pieces will be forwarded individually
            return
        elif opcode == structs.OPCodes.OP_Packet:
            print("Debug5")
            maybe_server_list = self.sequence.recv_packet(data, start_index, length)
            if maybe_server_list is not None:
                # don't double-send packet after server-list?
                data = maybe_server_list
        elif opcode == structs.OPCodes.OP_Fragment:
            print("Debug6")
            # must be one of the server list packets
            maybe_server_list = self.sequence.recv_fragment(data, start_index, length)
            if maybe_server_list is not None:
                # We're finished with the server list, forward it
                data = maybe_server_list
            else:
                # Don't forward, whole point is to filter this
                return
        print("Debug7")
        self.send_to_client(data)


async def shutdown(transport):
    print("Shutting down proxy...")
    proxy_stats.update_status("Shutting down")
    transport.close()
    loop = asyncio.get_running_loop()
    loop.close()


async def main():
    # Update UI status
    proxy_stats.update_status("Starting")
    
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        LoginProxy, local_addr=(config.LISTEN_HOST, config.LISTEN_PORT))
    print(f"Started UDP proxy, listening on {config.LISTEN_HOST}:{config.LISTEN_PORT}")
    
    return transport
