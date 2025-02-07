from __future__ import annotations
import asyncio
import functools
import time
import socket

from Crypto.Cipher import DES

from eqemu_sso_login_proxy import config
from eqemu_sso_login_proxy import sequence
from eqemu_sso_login_proxy import structs

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


class LoginSessionManager(asyncio.DatagramProtocol):
    client_addr: tuple[str, int]
    proxy: EQEMULoginProxy
    transport: asyncio.DatagramTransport
    last_recv_time: time
    in_session: bool
    connection_made_event: asyncio.Event
    receiving_combined_event: asyncio.Event
    sequence: sequence.Sequence

    def __init__(self, proxy: EQEMULoginProxy, client_addr: tuple[str, int],
                 local_addr: tuple[str, int]):
        self.proxy = proxy
        self.client_addr = client_addr
        self.local_addr = local_addr
        self.in_session = False
        self.last_recv_time = 0

        self.connection_made_event = asyncio.Event()
        self.receiving_combined_event = asyncio.Event()

        self.sequence = sequence.Sequence()

        print(f"Additional UDP listener started for {self.client_addr}")

    def sequence_free(self):
        if not self.sequence.packets:
            return
        # self.packets.clear()
        for packet in self.sequence.packets:
            packet.data = None
        self.sequence = sequence.Sequence()

    def connection_made(self, transport):
        self.transport = transport
        self.connection_made_event.set()
        print(f"Connection made to {self.transport.get_extra_info('sockname')}")

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
            return
        if buf.startswith(b'\x00\x03\x04\x00\x15\x00'):
            # LOGIN packet
            # lm = LoginBaseMessage.from_buffer_copy(buf, 0)
            # lm_dict = {}
            # for field_name, _ in lm._fields_:
            #     lm_dict[field_name] = getattr(lm, field_name)
            # print(f"LOGIN MESSAGE:  {lm_dict}")
            #self.debug_write_packet(buf, start_index, length, login_to_client)

            data = buf[14 + structs.SIZE_OF_LOGIN_BASE_MESSAGE:]
            # data_len = len(data)
            # padded_data = data.ljust((int(data_len / 8) + 1) * 8, b'\x00')
            # data_string = " ".join(f"{x:02x}".upper() for x in padded_data)
            buf_string = " ".join(f"{x:02x}".upper() for x in buf)
            # hex_string = "\\x".join(f"{x:02x}".upper() for x in padded_data)
            # print(f"LOGIN DATA (len: {data_len}): {data_string}")
            # print(f"LOGIN HEX:  {hex_string}")
            cipher = DES.new(config.ENCRYPTION_KEY, DES.MODE_CBC, config.iv())
            decrypted_text = cipher.decrypt(data)
            user, password = decrypted_text.rstrip(b'\x00').split(b'\x00')
            # print(f'user: `{user.decode()}`, password: `{password.decode()}`')
            with open("login_packet.bin", "a") as f:
                f.write(f"{user.decode()}|{password.decode()}: {buf_string}\n")
                # f.write(f"{hex_string}\n")
            if user.decode() == "test" and password.decode() == "test":
                print("LOGIN:  test/test, replacing...")
                cipher = DES.new(config.ENCRYPTION_KEY, DES.MODE_CBC, config.iv())
                plaintext = config.TEST_USER + b'\x00' + config.TEST_PASSWORD + b'\x00'
                padded_plaintext = plaintext.ljust((int(len(plaintext) / 8) + 1) * 8, b'\x00')
                encrypted_text = cipher.encrypt(padded_plaintext)
                new_login = buf[:14 + structs.SIZE_OF_LOGIN_BASE_MESSAGE] + encrypted_text
                new_login[7] = len(new_login) - 8
                #self.debug_write_packet(new_login, start_index, len(new_login), login_to_client)
                return new_login

        return buf

    def handle_client_packet(self, data: bytearray):
        """Called on a packet from the client"""
        recv_time = time.time()
        debug_write_packet(data, False)
        if not self.in_session or (recv_time - self.last_recv_time) > 60:
            self.sequence_free()

        # From recv_from_local
        opcode = structs.get_protocol_opcode(data)
        if opcode == structs.OPCodes.OP_Combined:
            self.sequence.adjust_combined(data)
            data = self.check_rewrite_auth(data)
        elif opcode == structs.OPCodes.OP_SessionDisconnect:
            self.in_session = False
            self.sequence_free()
            # I don't think we need to do either of the above, just close down...
            # A new session will have a new class created here.
            # asyncio.ensure_future(self.shutdown())
        elif opcode == structs.OPCodes.OP_Ack:
            # /* Rewrite client-to-server ack sequence values, since we will be desynchronizing them */
            self.sequence.adjust_ack(data, 0, len(data))
        elif opcode == structs.OPCodes.OP_KeepAlive:
            print("Let's debug here and see about packet state")

        self.last_recv_time = recv_time
        self.send_to_loginserver(data)

    async def shutdown(self):
        # Close the transport to shut down the endpoint
        print(f"Shutting down UDP server on {self.transport.get_extra_info('sockname')}")
        self.transport.close()

    def send_to_client(self, data: bytearray):
        if not data:
            print("Empty data, not sending to client")
            return
        # debug_write_packet(data, True)
        print(f"Sending data to client {self.client_addr}: {data}")
        self.proxy.transport.sendto(data, self.client_addr)

    def send_to_loginserver(self, data: bytearray):
        if not data:
            print("Empty data, not sending to loginserver")
            return
        # debug_write_packet(data, False)
        print(f"Sending data to loginserver: {data}")
        self.transport.sendto(data, EQEMU_ADDR)

    def datagram_received(self, data: bytes, addr: tuple[str, int], start_index=0, length=None) -> None:
        """Called on a packet from the login server"""
        # if addr != EQEMU_ADDR:
        #     return self.handle_client_packet(bytearray(data))
        # self.recv_from_remote(self.buffer, 0, length)
        if length is None:
            length = len(data)
        debug_write_packet(data, True)
        data = bytearray(data)
        print(f"Received message: {data} from address: {addr}")
        opcode = structs.get_protocol_opcode(data[start_index:])

        print("Debug1")
        if opcode == structs.OPCodes.OP_SessionResponse:
            self.in_session = True
            self.sequence_free()
            print("Debug2")
        elif opcode == structs.OPCodes.OP_Combined:
            print("Debug4")
            self.receiving_combined_event.set()
            self.sequence.recv_combined(data, functools.partial(self.datagram_received), start_index, length)
            self.receiving_combined_event.clear()
            # Pieces will be forwarded individually
            return
        elif opcode == structs.OPCodes.OP_Packet:
            print("Debug5")
            maybe_server_list = self.sequence.recv_packet(data, start_index, length)
            if maybe_server_list is not None:
                # don't double-send packet after server-list?
                data = maybe_server_list
                # self.send_to_client(maybe_server_list)
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


class EQEMULoginProxy(asyncio.DatagramProtocol):

    connections: dict[tuple[str, int], LoginSessionManager]
    transport: asyncio.DatagramTransport
    cleanup_lock: asyncio.Lock

    def __init__(self):
        super().__init__()
        self.connections = {}
        self.cleanup_lock = asyncio.Lock()
        asyncio.create_task(self.cleanup_sessions())

    def connection_made(self, transport):
        self.transport = transport

    async def cleanup_sessions(self):
        while True:
            await asyncio.sleep(config.SESSION_CLEANUP_INTERVAL)
            async with self.cleanup_lock:
                # Remove sessions that haven't been used in a while
                current_session_count = len(self.connections)
                current_time = time.time()
                self.connections = {
                    addr: session for addr, session in self.connections.items()
                    if current_time - session.last_recv_time < config.SESSION_CLEANUP_INTERVAL
                }
                new_session_count = len(self.connections)
                print(f"Cleaned up {current_session_count - new_session_count} sessions.")

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        print(f"Received message from CLIENT({addr}): {data}")
        if len(data) < 2:
            return

        asyncio.create_task(self.handle_packet(data, addr))

    async def handle_packet(self, data: bytes, addr: tuple[str, int]):
        if addr not in self.connections:
            # Initialize a new datagram endpoint on a free high number port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('', 0))
            _, new_listen_port = sock.getsockname()
            sock.close()
            session_manager = LoginSessionManager(
                self, client_addr=addr,
                local_addr=(config.LISTEN_HOST, new_listen_port))
            loop = asyncio.get_running_loop()
            session_coroutine = loop.create_datagram_endpoint(
                lambda: session_manager,
                local_addr=(config.LISTEN_HOST, new_listen_port)
            )
            self.connections[addr] = session_manager
            asyncio.ensure_future(session_coroutine)
            await session_manager.connection_made_event.wait()

        # Send CLIENT packet to be processed and forwarded to EQEMU LOGIN-SERVER
        self.connections[addr].handle_client_packet(bytearray(data))


async def shutdown(transport):
    print("Shutting down proxy...")
    transport.close()
    loop = asyncio.get_running_loop()
    loop.close()


async def main():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        EQEMULoginProxy, local_addr=(config.LISTEN_HOST, config.LISTEN_PORT))
    print(f"Started UDP proxy, listening on {config.LISTEN_HOST}:{config.LISTEN_PORT}")
