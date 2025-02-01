import time
import struct

import connection
import sequence


def get_protocol_opcode(data):
    return struct.unpack('<H', data[:2])[0]


def debug_write_packet(buf, login_to_client):
    print(f"{int(time.time())} ", end='')
    if login_to_client:
        print(f"LOGIN to CLIENT (len {len(buf)}):")
    else:
        print(f"CLIENT to LOGIN (len {len(buf)}):")

    for i in range(0, len(buf), 16):
        chunk = buf[i:i + 16]
        hex_part = ' '.join(f"{byte:02x}" for byte in chunk)
        ascii_part = ''.join(chr(byte) if chr(byte).isalnum() else '.' for byte in chunk)
        print(f"{hex_part:<48}  {ascii_part}")


def recv_from_local(con, length):
    opcode = get_protocol_opcode(con.buffer)
    if opcode == 0x03:  # OP_Combined
        sequence.sequence_adjust_combined(con, length)
    elif opcode == 0x05:  # OP_SessionDisconnect
        con.in_session = False
        sequence.sequence_free(con)
    elif opcode == 0x15:  # OP_Ack
        sequence.sequence_adjust_ack(con, con.buffer, length)

    connection.connection_send(con, con.buffer, length, True)


def recv_from_remote(con, data, length):
    opcode = get_protocol_opcode(data)
    if opcode == 0x02:  # OP_SessionResponse
        con.in_session = True
        sequence.sequence_free(con)
    elif opcode == 0x03:  # OP_Combined
        sequence.sequence_recv_combined(con, data, length)
        return
    elif opcode == 0x09:  # OP_Packet
        sequence.sequence_recv_packet(con, data, length)
    elif opcode == 0x0d:  # OP_Fragment
        sequence.sequence_recv_fragment(con, data, length)
        return

    connection.connection_send(con, data, length, False)