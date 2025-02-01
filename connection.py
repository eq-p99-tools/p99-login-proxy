import socket
import struct
import ctypes
import os
import time
import logging

LOGGER = logging.getLogger(__name__)


class Packet:
    def __init__(self):
        self.is_fragment = False
        self.length = 0
        self.data = None


class Sequence:
    def __init__(self):
        self.packets = []
        self.capacity = 0
        self.count = 0
        self.frag_start = 0
        self.frag_count = 0
        self.seq_to_local = 0
        self.seq_from_remote = 0
        self.seq_from_remote_offset = 0


class FirstFrag(ctypes.Structure):
    _fields_ = [("protocol_opcode", ctypes.c_ushort),
                ("sequence", ctypes.c_ushort),
                ("total_len", ctypes.c_uint),
                ("app_opcode", ctypes.c_ushort)]


class Frag(ctypes.Structure):
    _fields_ = [("protocol_opcode", ctypes.c_short),
                ("sequence", ctypes.c_short)]


class Connection:
    SIZE_OF_FIRST_FRAG = ctypes.sizeof(FirstFrag)
    SIZE_OF_FRAG = ctypes.sizeof(Frag)

    def __init__(self):
        self.socket = None
        self.in_session = False
        self.last_recv_time = 0
        self.local_addr = None
        self.remote_addr = None
        self.buffer = bytearray(2048)
        self.sequence = Sequence()

    def dispose(self):
        if self.socket:
            self.socket.close()
            self.socket = None
        self.sequence_free()

    def sequence_init(self):
        self.sequence = Sequence()

    def sequence_free(self):
        if not self.sequence.packets:
            return
        for packet in self.sequence.packets:
            packet.data = None
        self.sequence.packets.clear()
        self.sequence_init()

    def open(self, port):
        self.sequence_init()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.local_addr = ('', port)
        self.socket.bind(('', port))

        # Resolve the login server address via DNS
        remote_host_ip = socket.gethostbyname("login.eqemulator.net")
        self.remote_addr = (remote_host_ip, 5998)
        self.in_session = False
        self.last_recv_time = 0

    def sequence_adjust_combined(self, length, start_index):
        pos = 2 + start_index
        if length < 4:
            return
        while True:
            sublen = self.buffer[pos]
            pos += 1
            if (pos + sublen) > length or sublen == 0:
                return
            data = self.buffer[pos:pos + sublen]
            if struct.unpack('!H', data[:2])[0] == 0x15:
                self.sequence_adjust_ack(data, 0, sublen)
            pos += sublen
            if pos >= length:
                return

    @staticmethod
    def debug_write_packet(buf, start_index, length, login_to_client):
        print(f"{time.time()} ", end="")
        if login_to_client:
            print(f"LOGIN to CLIENT (len {length}):")
        else:
            print(f"CLIENT to LOGIN (len {length}):")
        for i in range(start_index, start_index + length, 16):
            print(" ".join(f"{x:02x}" for x in buf[i:i + 16]), end="  ")
            print("".join(chr(x) if 32 <= x < 127 else '.' for x in buf[i:i + 16]))

    def connection_send(self, data, start_index, length, to_remote):
        addr = self.remote_addr if to_remote else self.local_addr
        self.debug_write_packet(data, start_index, length, not to_remote)
        try:
            self.socket.sendto(data[start_index:start_index + length], addr)
        except Exception as ex:
            LOGGER.exception(ex)

    def sequence_adjust_ack(self, data, start_index, length):
        if length < 4:
            return
        struct.pack_into('!H', data, 2 + start_index, self.sequence.seq_from_remote - 1)

    def recv_from_local(self, length):
        opcode = self.get_protocol_opcode(self.buffer, 0)
        if opcode == 0x03:  # /* OP_Combined */
            self.sequence_adjust_combined(length, 0)
        elif opcode == 0x05:  # /* OP_SessionDisconnect */
            self.in_session = False
            self.sequence_free()
        elif opcode == 0x15:  # /* OP_Ack */
            # /* Rewrite client-to-server ack sequence values, since we will be desynchronizing them */
            self.sequence_adjust_ack(self.buffer, 0, length)
        self.connection_send(self.buffer, 0, length, True)

    def connection_read(self):
        length, addr = self.socket.recvfrom_into(self.buffer)

        if length < 2:
            return True

        recv_time = time.time()

        # // Check if packet is from remote server
        if addr == self.remote_addr:
            self.recv_from_remote(self.buffer, 0, length)
        else:
            if not self.in_session or (recv_time - self.last_recv_time) > 60:
                # was: connection_reset(addr)
                self.local_addr = addr
                self.sequence_free()
            self.recv_from_local(length)
        self.last_recv_time = recv_time
        return True

    # def connection_reset(self, addr):
    #     # Totally AI, does this work?
    #     # self.remote_addr = addr
    #     self.local_addr = addr
    #     self.in_session = False
    #     self.sequence_free()

    @staticmethod
    def get_protocol_opcode(data, start_index):
        return struct.unpack('!H', data[start_index:start_index + 2])[0]

    @staticmethod
    def get_sequence(data, start_index):
        return struct.unpack('!H', data[start_index + 2:start_index + 4])[0]

    @staticmethod
    def copy_fragment(packet, data, start_index, length):
        packet.data = data[start_index:start_index + length]

    def sequence_recv_fragment(self, data, start_index, length):
        val = self.get_sequence(data, start_index)
        packet = self.get_packet_space(val, length)

        packet.is_fragment = True
        self.copy_fragment(packet, data, start_index, length)

        if val == self.sequence.seq_from_remote:
            self.process_first_fragment(data)
        elif self.sequence.frag_count > 0:
            self.check_fragment_finished()

    def recv_from_remote(self, buffer, start_index, length):
        opcode = self.get_protocol_opcode(buffer, start_index)
        if opcode == 0x02:  # /* OP_SessionResponse */
            self.in_session = True
            self.sequence_free()
        elif opcode == 0x03:  # /* OP_Combined */
            self.sequence_recv_combined(buffer, start_index, length)
            return  # /* Pieces will be forwarded individually */
        elif opcode == 0x09:  # /* OP_Packet */
            self.sequence_recv_packet(buffer, start_index, length)
        elif opcode == 0x0d:  # /* OP_Fragment -- must be one of the server list packets */
            self.sequence_recv_fragment(buffer, start_index, length)
            return  # /* Don't forward, whole point is to filter this */
        self.connection_send(buffer, start_index, length, False)

    def get_packet_space(self, sequence, length) -> Packet:
        sequence -= self.sequence.seq_from_remote_offset
        if sequence >= self.sequence.count:
            self.sequence.count = sequence + 1
        while sequence >= len(self.sequence.packets):
            self.sequence.packets.append(Packet())
        packet = self.sequence.packets[sequence]
        packet.length = length
        packet.data = None
        return packet

    def process_first_fragment(self, data) -> bool:
        frag = FirstFrag.from_buffer_copy(data)
        if frag.app_opcode != 0x18:
            return False
        self.sequence.frag_start = self.get_sequence(data, 0)
        self.sequence.frag_count = ((socket.ntohl(frag.total_len) - (512 - 8)) // (512 - 4)) + 2
        return True

    def check_fragment_finished(self) -> None:
        index = self.sequence.frag_start - self.sequence.seq_from_remote_offset
        n = self.sequence.frag_count
        count = 1
        packet = self.sequence.packets[index]
        got = packet.length - self.SIZE_OF_FIRST_FRAG + 2
        while count < n:
            index += 1
            if index >= self.sequence.count:
                return
            packet = self.sequence.packets[index]
            if not packet.data:
                return
            got += packet.length - self.SIZE_OF_FRAG
            count += 1
        self.filter_server_list(got - 2)

    def sequence_recv_combined(self, buffer, start_index, length) -> None:
        pos = 2 + start_index
        if length < 4:
            return
        while True:
            sublen = buffer[pos]
            pos += 1
            if (pos + sublen) > length or sublen == 0:
                return
            self.recv_from_remote(buffer, pos, sublen)
            pos += sublen
            if pos >= length:
                return

    def strlen(self, array, offset):
        if not array or len(array) == 0 or offset >= len(array):
            return 0
        start_offset = offset
        while array[offset] != 0:
            offset += 1
        return offset - start_offset

    def filter_server_list(self, total_len):
        # /* Should not need nearly this much space just for P99 server listings */
        out_buffer = bytearray(512)
        index = self.sequence.frag_start - self.sequence.seq_from_remote_offset
        new_index = self.sequence.frag_start
        packet = self.sequence.packets[index]
        if packet.length == 0:
            return
        server_list = bytearray(total_len)
        server_list[:packet.length - self.SIZE_OF_FIRST_FRAG] = packet.data[self.SIZE_OF_FIRST_FRAG:]
        pos = packet.length - self.SIZE_OF_FIRST_FRAG
        while pos < total_len:
            index += 1
            packet = self.sequence.packets[index]
            server_list[pos:pos + packet.length - self.SIZE_OF_FRAG] = packet.data[self.SIZE_OF_FRAG:]
            pos += packet.length - self.SIZE_OF_FRAG

        # /* We now have the whole server list in one piece */
        # /* Write our output packet header */
        out_buffer[0] = 0
        out_buffer[1] = 0x09  # /* OP_Packet */
        struct.pack_into('!H', out_buffer, 2, self.sequence.seq_to_local)
        self.sequence.seq_to_local += 1
        out_buffer[4] = 0x18  # /* OP_ServerListResponse */
        out_buffer[5] = 0

        # /* First 16 bytes of the server list packet is some kind of header, copy it over */
        out_buffer[6:22] = server_list[:16]
        out_len = 16 + 6 + 4
        out_count = 0

        # /* List of servers starts at serverList[20] */
        pos = 20
        while pos < total_len:
            # /* Server listings are variable-size */
            i = pos
            pos += self.strlen(server_list, pos) + 1  # /* IP address */
            pos += struct.calcsize('i') * 2  # /* ListId, runtimeId */
            namesize = self.strlen(server_list, pos)
            name = server_list[pos:pos + namesize]
            pos += len(name) + 1
            language = server_list[pos:pos + self.strlen(server_list, pos)]
            pos += self.strlen(server_list, pos) + 1  # /* language */
            region = server_list[pos:pos + self.strlen(server_list, pos)]
            pos += self.strlen(server_list, pos) + 1  # /* region */
            pos += struct.calcsize('i') * 2  # /* Status, player count */

            # /* Time to check the name! */
            if name.lower().startswith(b"project 1999") or name.lower().startswith(b"an interesting"):
                out_count += 1
                out_buffer[out_len:out_len + pos - i] = server_list[i:pos]
                out_len += pos - i

        # /* Write our outgoing server count */
        struct.pack_into('!I', out_buffer, 22, out_count)

        self.sequence.seq_from_remote = new_index + 1
        self.sequence.seq_from_remote_offset = self.sequence.seq_from_remote
        self.sequence.frag_count = 0
        self.sequence.frag_start = 0
        for packet in self.sequence.packets:
            packet.data = None
            # packet.length = 0
        self.connection_send(out_buffer, 0, out_len, False)

    def sequence_recv_packet(self, buffer, start_index, length) -> None:
        val = self.get_sequence(buffer, start_index)
        packet = self.get_packet_space(val, length)
        packet.is_fragment = False
        struct.pack_into('!H', buffer, 2 + start_index, self.sequence.seq_to_local)
        self.sequence.seq_to_local += 1
        if val != self.sequence.seq_from_remote:
            return
        val -= self.sequence.seq_from_remote_offset
        for i in range(val, self.sequence.count):
            packet = self.sequence.packets[i]
            if packet.length > 0:
                self.sequence.seq_from_remote += 1
                if packet.is_fragment and self.process_first_fragment(packet.data):
                    self.check_fragment_finished()
                    break
