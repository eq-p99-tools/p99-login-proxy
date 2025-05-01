# Based in large part on the original work by Zaela:
# https://github.com/Zaela/p99-login-middlemand
from p99_sso_login_proxy import structs


class Packet:
    def __init__(self):
        self.is_fragment = False
        # self.length = 0
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

    def adjust_combined(self, buffer: bytearray):
        pos = 2
        length = len(buffer)
        if length < 4:
            return
        while True:
            sublen = buffer[pos]
            pos += 1
            if (pos + sublen) > length or sublen == 0:
                return
            # data = buffer[pos:pos + sublen]
            # if struct.unpack('!H', data[:2])[0] == 0x15:
            if structs.get_protocol_opcode(buffer[pos:pos + sublen]) == structs.OPCodes.OP_Combined:
                self.adjust_ack(buffer, pos, sublen)
            pos += sublen
            if pos >= length:
                return

    def adjust_ack(self, data: bytearray, start_index: int, length: int):
        if length < 4:
            return
        # struct.pack_into('!H', data, 2, self.seq_from_remote - 1)
        new_bytes = (max(self.seq_from_remote - 1, 0)).to_bytes(2, byteorder='big')
        data[2 + start_index:4 + start_index] = new_bytes

    @staticmethod
    def recv_combined(buffer: bytearray, recv_func, start_index, length) -> None:
        # length = len(buffer)
        pos = 2 + start_index
        if length < 4:
            return
        while True:
            sublen = buffer[pos]
            pos += 1
            if (pos + sublen) > length or sublen == 0:
                return
            recv_func(buffer, start_index=pos, length=sublen, addr=None)
            pos += sublen
            if pos >= length:
                return

    def recv_packet(
            self, buffer: bytearray, start_index: int, length: int) -> bytearray or None:
        seq_val = structs.get_sequence(buffer, start_index)
        packet = self.get_packet_space(seq_val, length)
        packet.is_fragment = False
        # struct.pack_into('!H', buffer, 2 + start_index, self.seq_to_local)
        new_bytes = self.seq_to_local.to_bytes(2, byteorder='big')
        buffer[2 + start_index:4 + start_index] = new_bytes
        print(f"recv_packet 1: {seq_val} ({self.seq_from_remote})")
        self.seq_to_local += 1
        if seq_val != self.seq_from_remote:
            print(f"recv_packet 1.5: {seq_val} ({self.seq_from_remote})")
            return
        seq_val -= self.seq_from_remote_offset
        print(f"recv_packet 2: {seq_val} ({self.seq_from_remote}) -> {len(self.packets)}")
        for i in range(seq_val, self.count):
            print(f"recv_packet 3: {i} ({len(self.packets)})")
            packet = self.packets[i]
            # if packet.length > 0:
            if packet.length > 0:
                self.seq_from_remote += 1
                if packet.is_fragment and self.process_first_fragment(packet.data):
                    maybe_server_list = self.check_fragment_finished()
                    print(f"recv_packet 4: {maybe_server_list}")
                    # If this is the server list, the caller should return it to the client
                    return maybe_server_list

    def recv_fragment(self, data: bytearray, start_index: int, length: int) -> bytearray or None:
        seq_val = structs.get_sequence(data, 0)
        packet = self.get_packet_space(seq_val, len(data))

        packet.is_fragment = True
        packet.data = data[start_index:start_index + length]

        print(f"recv_fragment 1: {seq_val} ({self.seq_from_remote}); frag_count: {self.frag_count}")
        if seq_val == self.seq_from_remote:
            self.process_first_fragment(data)
            maybe_server_list = self.check_fragment_finished()
            # If this is the server list, the caller should return it to the client
            return maybe_server_list
        elif self.frag_count > 0:
            maybe_server_list = self.check_fragment_finished()
            # If this is the server list, the caller should return it to the client
            return maybe_server_list

    def get_packet_space(self, sequence: int, length: int) -> Packet:
        sequence -= self.seq_from_remote_offset
        if sequence >= self.count:
            self.count = sequence + 1
        while sequence >= len(self.packets):
            self.packets.append(Packet())
        packet = self.packets[sequence]
        packet.length = length
        packet.data = None
        return packet

    def process_first_fragment(self, data: bytearray) -> bool:
        frag = structs.FirstFrag.from_buffer_copy(data)
        print(f"process_first_fragment 1: {frag.app_opcode} ({structs.OPCodes.OP_ServerListResponse.value})")
        if frag.app_opcode != structs.OPCodes.OP_ServerListResponse.value:
            return False
        self.frag_start = structs.get_sequence(data, 0)

        # All of this was originally:
        # self.frag_count = ((socket.ntohl(frag.total_len) - (512 - 8)) // (512 - 4)) + 2
        frag_length_bigendian = frag.total_len.to_bytes(4, byteorder='big')
        total_len = int.from_bytes(frag_length_bigendian, byteorder='little')
        first_frag_payload_size = 512 - 8
        subsequent_frag_payload_size = 512 - 4
        self.frag_count = ((total_len - first_frag_payload_size) // subsequent_frag_payload_size) + 2

        return True

    def check_fragment_finished(self) -> bytearray or None:
        index = self.frag_start - self.seq_from_remote_offset
        n = self.frag_count
        count = 1
        packet = self.packets[index]
        # got = packet.length - structs.SIZE_OF_FIRST_FRAG + 2
        got = packet.length - structs.SIZE_OF_FIRST_FRAG + 2
        print(f"check_fragment_finished 1: {got} ({n})")
        while count < n:
            index += 1
            # if index >= len(self.packets):
            if index >= self.count:
                return
            packet = self.packets[index]
            if not packet.data:
                return
            got += packet.length - structs.SIZE_OF_FRAG
            count += 1
        server_list = self.filter_server_list(got - 2)
        return server_list

    def filter_server_list(self, total_len):
        index = self.frag_start - self.seq_from_remote_offset
        packet = self.packets[index]
        if packet.length == 0:
            return

        server_list = bytearray(packet.data[structs.SIZE_OF_FIRST_FRAG:])
        while len(server_list) < total_len:
            index += 1
            packet = self.packets[index]
            server_list += packet.data[structs.SIZE_OF_FRAG:]

        # /* We now have the whole server list in one piece */
        servers = []
        # /* List of servers starts at serverList[20] */
        pos = 20
        while pos < total_len:
            # /* Server listings are variable-size */
            i = pos

            ip_addr = server_list[pos:].split(b'\0', 1)[0]
            pos += len(ip_addr) + 1

            pos += structs.SIZE_OF_INT * 2  # /* ListId, runtimeId */

            name = server_list[pos:].split(b'\0', 1)[0]
            pos += len(name) + 1  # Move forward past the name we just pulled out

            language = server_list[pos:].split(b'\0', 1)[0]
            pos += len(language) + 1

            region = server_list[pos:].split(b'\0', 1)[0]
            pos += len(region) + 1

            pos += structs.SIZE_OF_INT * 2  # /* Status, player count */

            # /* Time to check the name! */
            if name.lower().startswith(b"project 1999") or name.lower().startswith(b"an interesting"):
                servers.append(server_list[i:pos])

        out_buffer = b''.join(
            [
                # Starts with a null byte
                b'\x00',
                # Then the OP_Packet opcode
                bytes([structs.OPCodes.OP_Packet.value]),
                # Then the sequence number as 2 bytes
                self.seq_to_local.to_bytes(2, byteorder='big'),
                # Then the OP_ServerListResponse opcode
                bytes([structs.OPCodes.OP_ServerListResponse.value]),
                # Then a null byte
                b'\x00',
                # Then the first 16 bytes of the server list (the header)
                server_list[:16],
                # Then the server count as 4 bytes
                len(servers).to_bytes(4, byteorder='little'),
                # Then our compiled server list
                b''.join(servers)
            ]
        )
        print(f"filter_server_list: {servers}")

        self.seq_to_local += 1
        self.seq_from_remote = self.frag_start + 1
        self.seq_from_remote_offset = self.seq_from_remote
        self.frag_count = 0
        self.frag_start = 0
        for packet in self.packets:
            packet.data = None
            packet.length = 0
        # self.packets.clear()

        return out_buffer
