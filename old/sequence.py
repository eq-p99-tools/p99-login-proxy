import struct
import ctypes

import connection


class Sequence:
    def __init__(self):
        self.packets = []
        self.count = 0
        self.capacity = 0
        self.seqFromRemote = 0
        self.seqToLocal = 0
        self.fragStart = 0
        self.fragCount = 0

class Packet:
    def __init__(self):
        self.data = None
        self.len = 0
        self.isFragment = False

class FirstFrag:
    def __init__(self, appOpcode, totalLen):
        self.appOpcode = appOpcode
        self.totalLen = totalLen

class Frag:
    pass

def ToHostShort(value):
    return struct.unpack('<H', struct.pack('>H', value))[0]

def ToNetworkShort(value):
    return struct.unpack('>H', struct.pack('<H', value))[0]

def ToHostLong(value):
    return struct.unpack('<L', struct.pack('>L', value))[0]

def check_fragment_finished(con):
    seq = con.sequence
    index = seq.fragStart
    got = seq.packets[index].len - ctypes.sizeof(FirstFrag) + 2
    count = 1

    while count < seq.fragCount:
        index += 1
        if index >= seq.count:
            return
        got += seq.packets[index].len - ctypes.sizeof(Frag)
        count += 1

    filter_server_list(con, got - 2)

def process_first_fragment(con, data):
    seq = con.sequence
    frag = FirstFrag(*struct.unpack('<BH', data[:3]))
    if frag.appOpcode != 0x18:
        return 0
    seq.fragStart = get_sequence(data)
    seq.fragCount = (ToHostLong(frag.totalLen) - (512 - 8)) // (512 - 4) + 2
    return 1

def filter_server_list(con, totalLen):
    seq = con.sequence
    index = seq.fragStart
    pos = 0
    outCount = 0
    outBuffer = bytearray(512)
    outLen = 0

    serverList = bytearray(totalLen)
    serverList[pos:pos + seq.packets[index].len - ctypes.sizeof(FirstFrag)] = seq.packets[index].data[ctypes.sizeof(FirstFrag):]
    pos += seq.packets[index].len - ctypes.sizeof(FirstFrag)

    while pos < totalLen:
        index += 1
        serverList[pos:pos + seq.packets[index].len - ctypes.sizeof(Frag)] = seq.packets[index].data[ctypes.sizeof(Frag):]
        pos += seq.packets[index].len - ctypes.sizeof(Frag)

    outBuffer[0:6] = struct.pack('<BBHBB', 0, 0x09, ToNetworkShort(seq.seqToLocal), 0x18, 0)
    outLen = 16 + 6 + 4

    pos = 20
    while pos < totalLen:
        i = pos
        pos += len(serverList[pos:].split(b'\x00', 1)[0]) + 1
        pos += 8
        name = serverList[pos:].split(b'\x00', 1)[0]
        pos += len(name) + 1
        pos += len(serverList[pos:].split(b'\x00', 1)[0]) + 1
        pos += len(serverList[pos:].split(b'\x00', 1)[0]) + 1
        pos += 8

        if compare_prefix(name.decode(), SERVER_NAME_PREFIX, len(SERVER_NAME_PREFIX) - 1):
            outCount += 1
            outBuffer[outLen:outLen + pos - i] = serverList[i:pos]
            outLen += pos - i

    struct.pack_into('<I', outBuffer, 22, outCount)
    seq.seqFromRemote = index + 1
    seq.fragCount = 0
    seq.fragStart = 0

    connection.connection_send(con, outBuffer, outLen, 0)

def get_sequence(data):
    return ToHostShort(struct.unpack('<H', data[2:4])[0])

def sequence_init(con):
    con.sequence = Sequence()

def sequence_free(con):
    seq = con.sequence
    if not seq.packets:
        return
    for packet in seq.packets:
        if packet.data:
            del packet.data
    seq.packets.clear()
    sequence_init(con)

def grow(con, index):
    seq = con.sequence
    cap = 32
    while cap <= index:
        cap *= 2
    array = [Packet() for _ in range(cap)]
    if seq.capacity != 0:
        array[:seq.capacity] = seq.packets
    seq.capacity = cap
    seq.packets = array

def sequence_adjust_ack(con, data, length):
    if length < 4:
        return
    struct.pack_into('<H', data, 2, ToNetworkShort(con.sequence.seqFromRemote - 1))

def get_packet_space(con, sequence, length):
    seq = con.sequence
    if sequence >= seq.count:
        seq.count = sequence + 1
    if sequence >= seq.capacity:
        grow(con, sequence + 1)
    p = seq.packets[sequence]
    if p.data:
        del p.data
    p.len = length
    p.data = None
    return p

def copy_fragment(con, p, data, length):
    p.data = bytearray(data[:length])

def sequence_recv_packet(con, data, length):
    seq = con.sequence
    val = get_sequence(data)
    p = get_packet_space(con, val, length)
    p.isFragment = False
    struct.pack_into('<H', data, 2, ToNetworkShort(seq.seqToLocal))
    seq.seqToLocal += 1
    if val != seq.seqFromRemote:
        return
    for i in range(val, seq.count):
        if seq.packets[i].len > 0:
            seq.seqFromRemote += 1
            if seq.packets[i].isFragment and process_first_fragment(con, seq.packets[i].data):
                check_fragment_finished(con)
                break

def sequence_recv_fragment(con, data, length):
    seq = con.sequence
    val = get_sequence(data)
    p = get_packet_space(con, val, length)
    p.isFragment = True
    copy_fragment(con, p, data, length)
    if val == seq.seqFromRemote:
        process_first_fragment(con, data)
    elif seq.fragCount > 0:
        check_fragment_finished(con)

def sequence_adjust_combined(con, length):
    pos = 2
    if length < 4:
        return
    while True:
        sublen = con.buffer[pos]
        pos += 1
        if (pos + sublen) > length or sublen == 0:
            return
        data = con.buffer[pos:pos + sublen]
        if ToHostShort(struct.unpack('<H', data[:2])[0]) == 0x15:
            sequence_adjust_ack(con, data, sublen)
        pos += sublen
        if pos >= length:
            return

def sequence_recv_combined(con, data, length):
    pos = 2
    if length < 4:
        return
    while True:
        sublen = data[pos]
        pos += 1
        if (pos + sublen) > length or sublen == 0:
            return
        recv_from_remote(con, data[pos:pos + sublen], sublen)
        pos += sublen
        if pos >= length:
            return

def compare_prefix(a, b, length):
    return a[:length] == b[:length]