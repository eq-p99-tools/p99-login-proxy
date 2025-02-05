from __future__ import annotations
import asyncio
import functools
import time
import socket

from eqemu_sso_login_proxy import sequence
from eqemu_sso_login_proxy import structs

import faulthandler
faulthandler.enable()

UDP_IP = "0.0.0.0"

# Resolve the login server address via DNS
EQEMU_LOGIN_IP = socket.gethostbyname("login.eqemulator.net")
EQEMU_ADDR = (EQEMU_LOGIN_IP, 5998)
EQEMU_PORT = 5998


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

    def __init__(self, proxy: EQEMULoginProxy, client_addr: tuple[str, int]):
        self.proxy = proxy
        self.client_addr = client_addr
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
        # await self.connection_made_event.wait()
        asyncio.get_event_loop().run_until_complete(self.connection_made_event.wait())
        self.send_to_loginserver(data)

    async def shutdown(self):
        # Close the transport to shut down the endpoint
        print(f"Shutting down UDP server on {self.transport.get_extra_info('sockname')}")
        self.transport.close()

    def send_to_client(self, data: bytearray):
        debug_write_packet(data, True)
        print(f"Sending data to client: {data}")
        self.proxy.transport.sendto(data, self.client_addr)

    def send_to_loginserver(self, data: bytearray):
        # debug_write_packet(data, False)
        print(f"Sending data to loginserver: {data}")
        self.transport.sendto(data, EQEMU_ADDR)

    def datagram_received(self, data: bytes, addr: tuple[str, int], start_index=0, length=None) -> None:
        """Called on a packet from the login server"""
        # self.recv_from_remote(self.buffer, 0, length)
        if addr is not None:
            asyncio.get_event_loop().run_until_complete(self.connection_made_event.wait())
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

    def __init__(self):
        super().__init__()
        self.connections = {}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        print(f"Received message from CLIENT({addr}): {data}")

        if len(data) < 2:
            return

        if addr not in self.connections:
            # Initialize a new datagram endpoint on a free high number port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('', 0))
            _, listen_port = sock.getsockname()
            sock.close()
            session_manager = LoginSessionManager(self, client_addr=addr)
            loop = asyncio.get_running_loop()
            session_coroutine = loop.create_datagram_endpoint(
                lambda: session_manager,
                local_addr=(UDP_IP, listen_port)
            )
            asyncio.ensure_future(session_coroutine)
            self.connections[addr] = session_manager
            # session_manager.connection_made_event.wait()

        # Send CLIENT packet to be processed and forwarded to LOGIN SERVER
        # asyncio.ensure_future(self.connections[addr].handle_client_packet(bytearray(data)))
        self.connections[addr].handle_client_packet(bytearray(data))


async def main():
    loop = asyncio.get_event_loop()
    listen_server = loop.create_datagram_endpoint(
        EQEMULoginProxy, local_addr=(UDP_IP, EQEMU_PORT))
    transport, _ = loop.run_until_complete(listen_server)
    print("Started UDP proxy...")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    print("Closing proxy transport.")
    transport.close()
    loop.close()
