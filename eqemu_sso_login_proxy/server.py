from __future__ import annotations
import asyncio
import time
import socket

from eqemu_sso_login_proxy import config
from eqemu_sso_login_proxy import structs

UDP_IP = "0.0.0.0"

# Resolve the login server address via DNS
EQEMU_LOGIN_IP = socket.gethostbyname("login.eqemulator.net")
EQEMU_ADDR = (EQEMU_LOGIN_IP, 5998)
EQEMU_PORT = 5998


class LoginSessionManager(asyncio.DatagramProtocol):
    addr: tuple[str, int]
    proxy: EQEMULoginProxy
    transport: asyncio.DatagramTransport
    last_recv_time: time

    def __init__(self, proxy: EQEMULoginProxy, addr: tuple[str, int]):
        self.proxy = proxy
        self.addr = addr

        self.sequence = structs.Sequence()

        print(f"Additional UDP listener started on {self.addr}")

    def connection_made(self, transport):
        self.transport = transport

    def handle_client_packet(self, data: bytearray):
        """Called on a packet from the client"""
        recv_time = time.time()
        if not self.sequence.in_session or (recv_time - self.last_recv_time) > 60:
            self.sequence.free()
        self.last_recv_time = recv_time

        # From recv_from_local
        opcode = structs.get_protocol_opcode(data)
        if opcode == structs.OPCodes.OP_Combined:
            self.sequence.adjust_combined(data)
        elif opcode == structs.OPCodes.OP_SessionDisconnect:
            self.sequence.in_session = False
            self.sequence.free()
        elif opcode == structs.OPCodes.OP_Ack:
            # /* Rewrite client-to-server ack sequence values, since we will be desynchronizing them */
            self.sequence.adjust_ack(data, 0)
        self.transport.sendto(data, EQEMU_ADDR)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Called on a packet from the login server"""
        # self.recv_from_remote(self.buffer, 0, length)
        data = bytearray(data)
        print(f"Received message: {data} for address: {addr}")
        opcode = structs.get_protocol_opcode(data)

        if opcode == structs.OPCodes.OP_SessionResponse:
            self.sequence.in_session = True
            self.sequence.free()
        elif opcode == structs.OPCodes.OP_Combined:
            self.sequence.recv_combined(buffer, start_index)
            # Pieces will be forwarded individually
            return
        elif opcode == structs.OPCodes.OP_Packet:
            self.sequence.recv_packet(buffer, start_index)
        elif opcode == structs.OPCodes.OP_Fragment:
            # must be one of the server list packets
            self.sequence.recv_fragment(buffer, start_index)
            # Don't forward, whole point is to filter this
            return
        self.proxy.transport.sendto(data, addr)


class EQEMULoginProxy(asyncio.DatagramProtocol):

    connections: dict[tuple[str, int], LoginSessionManager]
    transport: asyncio.DatagramTransport

    def __init__(self):
        super().__init__()

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
            session_manager = LoginSessionManager(self, addr)
            loop = asyncio.get_running_loop()
            session_coroutine = loop.create_datagram_endpoint(
                lambda: session_manager,
                local_addr=(UDP_IP, listen_port)
            )
            asyncio.ensure_future(session_coroutine)
            self.connections[addr] = session_manager

        # Send CLIENT packet to be processed and forwarded to LOGIN SERVER
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
