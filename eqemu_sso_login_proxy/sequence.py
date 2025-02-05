from eqemu_sso_login_proxy import structs


def copy_fragment(packet, data, start_index, length):
    packet.data = data[start_index:start_index + length]


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

    def free(self):
        if not self.packets:
            return
        self.packets.clear()
        self.capacity = 0
        self.count = 0
        self.frag_start = 0
        self.frag_count = 0
        self.seq_to_local = 0
        self.seq_from_remote = 0
        self.seq_from_remote_offset = 0

    def adjust_combined(self, data: bytearray):
        pos = 2
        length = len(data)
        if length < 4:
            return
        while True:
            sublen = data[pos]
            pos += 1
            if (pos + sublen) > length or sublen == 0:
                return
            data[:] = data[pos:pos + sublen]
            # if struct.unpack('!H', data[:2])[0] == 0x15:
            if structs.get_protocol_opcode(data) == structs.OPCodes.OP_Combined:
                self.adjust_ack(data, sublen)
            pos += sublen
            if pos >= length:
                return

    def adjust_ack(self, data: bytearray, start_index: int):
        length = len(data)
        if length < 4:
            return
        # struct.pack_into('!H', data, 2, self.seq_from_remote - 1)
        new_bytes = (self.seq_from_remote - 1).to_bytes(2, byteorder='big')
        data[2 + start_index:4 + start_index] = new_bytes

    def sequence_recv_combined(self, buffer: bytearray, start_index: int, length: int) -> None:
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

    def sequence_recv_packet(
            self, buffer: bytearray, start_index: int, length: int) -> bytearray or None:
        seq_val = structs.get_sequence(buffer, start_index)
        packet = self.get_packet_space(seq_val, length)
        packet.is_fragment = False
        # struct.pack_into('!H', buffer, 2 + start_index, self.seq_to_local)
        new_bytes = self.seq_to_local.to_bytes(2, byteorder='big')
        buffer[2 + start_index:4 + start_index] = new_bytes

        self.seq_to_local += 1
        if seq_val != self.seq_from_remote:
            return
        seq_val -= self.seq_from_remote_offset
        for i in range(seq_val, self.count):
            packet = self.packets[i]
            # if packet.length > 0:
            if packet.data and len(packet.data) > 0:
                self.seq_from_remote += 1
                if packet.is_fragment and self.process_first_fragment(packet.data):
                    maybe_server_list = self.check_fragment_finished()
                    # If this is the server list, the caller should return it to the client
                    return maybe_server_list

    def sequence_recv_fragment(self, data: bytearray, start_index: int, length: int) -> bytearray or None:
        seq_val = structs.get_sequence(data, start_index)
        packet = self.get_packet_space(seq_val, length)

        packet.is_fragment = True
        copy_fragment(packet, data, start_index, length)

        if seq_val == self.seq_from_remote:
            self.process_first_fragment(data)
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
        # packet.length = length
        packet.data = None
        return packet

    def process_first_fragment(self, data: bytearray) -> bool:
        frag = structs.FirstFrag.from_buffer_copy(data)
        if frag.app_opcode != 0x18:
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
        got = len(packet.data) - structs.SIZE_OF_FIRST_FRAG + 2
        while count < n:
            index += 1
            if index >= self.count:
                return
            packet = self.packets[index]
            if not packet.data:
                return
            got += len(packet.data) - structs.SIZE_OF_FRAG
            count += 1
        server_list = self.filter_server_list(got - 2)
        return server_list

    def filter_server_list(self, total_len):
        # /* Should not need nearly this much space just for P99 server listings */
        out_buffer = bytearray()
        index = self.frag_start - self.seq_from_remote_offset
        new_index = self.frag_start
        packet = self.packets[index]
        # if packet.length == 0:
        if len(packet.data) == 0:
            return
        server_list = bytearray(total_len)
        # server_list[:packet.length - structs.SIZE_OF_FIRST_FRAG] = packet.data[structs.SIZE_OF_FIRST_FRAG:]
        server_list += packet.data[structs.SIZE_OF_FIRST_FRAG:]
        # pos = packet.length - structs.SIZE_OF_FIRST_FRAG
        pos = len(packet.data) - structs.SIZE_OF_FIRST_FRAG
        while pos < total_len:
            index += 1
            packet = self.packets[index]
            # server_list[pos:pos + packet.length - structs.SIZE_OF_FRAG] = packet.data[structs.SIZE_OF_FRAG:]
            server_list += packet.data[structs.SIZE_OF_FRAG:]
            # pos += packet.length - structs.SIZE_OF_FRAG
            pos += len(packet.data) - structs.SIZE_OF_FRAG

        # /* We now have the whole server list in one piece */
        # /* Write our output packet header */
        # out_buffer[0] = 0
        out_buffer.append(0)
        # out_buffer[1] = structs.OPCodes.OP_Packet
        out_buffer.append(structs.OPCodes.OP_Packet.value)
        # struct.pack_into('!H', out_buffer, 2, self.seq_to_local)
        new_bytes = self.seq_to_local.to_bytes(2, byteorder='big')
        # out_buffer[2:4] = new_bytes
        out_buffer += new_bytes

        self.seq_to_local += 1
        # out_buffer[4] = structs.OPCodes.OP_ServerListResponse
        out_buffer.append(structs.OPCodes.OP_ServerListResponse.value)
        # out_buffer[5] = 0
        out_buffer.append(0)

        # First 16 bytes of the server list packet is some kind of header, copy it over
        # out_buffer[6:22] = server_list[:16]
        out_buffer += server_list[:16]
        # out_len = 16 + 6 + 4
        # out_buffer += b'\0' * 4  # Looks like there are 4 bytes of padding here?
        # out_count = 0

        servers = []
        # /* List of servers starts at serverList[20] */
        pos = 20
        while pos < total_len:
            # /* Server listings are variable-size */
            i = pos

            # pos += self.strlen(server_list, pos) + 1  # /* IP address */
            ip_addr = server_list[pos:].split(b'\0', 1)[0]
            pos += len(ip_addr) + 1

            pos += structs.SIZE_OF_INT * 2  # /* ListId, runtimeId */

            # namesize = self.strlen(server_list, pos)  # Calculate the length of the next whole string from this point
            # name = server_list[pos:pos + namesize]
            name = server_list[pos:].split(b'\0', 1)[0]
            pos += len(name) + 1  # Move forward past the name we just pulled out

            # pos += self.strlen(server_list, pos) + 1  # /* language */
            # language = server_list[pos:pos + self.strlen(server_list, pos)]
            language = server_list[pos:].split(b'\0', 1)[0]
            pos += len(language) + 1

            # pos += self.strlen(server_list, pos) + 1  # /* region */
            # region = server_list[pos:pos + self.strlen(server_list, pos)]
            region = server_list[pos:].split(b'\0', 1)[0]
            pos += len(region) + 1

            pos += structs.SIZE_OF_INT * 2  # /* Status, player count */

            # /* Time to check the name! */
            if name.lower().startswith(b"project 1999") or name.lower().startswith(b"an interesting"):
                # out_count += 1
                # out_buffer[out_len:out_len + pos - i] = server_list[i:pos]
                servers.append(server_list[i:pos])
                # out_len += pos - i

        # /* Write our outgoing server count */
        # struct.pack_into('<I', out_buffer, 22, out_count)
        server_count_bytes = len(servers).to_bytes(4, byteorder='little')
        out_buffer += server_count_bytes
        for server in servers:
            out_buffer += server

        self.seq_from_remote = new_index + 1
        self.seq_from_remote_offset = self.seq_from_remote
        self.frag_count = 0
        self.frag_start = 0
        # for packet in self.packets:
        #     packet.data = None
            # packet.length = 0
        self.packets.clear()
        return out_buffer
