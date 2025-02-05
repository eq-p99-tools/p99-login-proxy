import ctypes

import enum


class FirstFrag(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("protocol_opcode", ctypes.c_ushort),
                ("sequence", ctypes.c_ushort),
                ("total_len", ctypes.c_uint),
                ("app_opcode", ctypes.c_ushort)]


class Frag(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("protocol_opcode", ctypes.c_short),
                ("sequence", ctypes.c_short)]


class LoginBaseMessage(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("sequence", ctypes.c_int32),
                ("compressed", ctypes.c_bool),
                ("encrypt_type", ctypes.c_int8),
                ("unk3", ctypes.c_int32)]


SIZE_OF_FIRST_FRAG = ctypes.sizeof(FirstFrag)
SIZE_OF_FRAG = ctypes.sizeof(Frag)
SIZE_OF_LOGIN_BASE_MESSAGE = ctypes.sizeof(LoginBaseMessage)
SIZE_OF_INT = ctypes.sizeof(ctypes.c_int)


class OPCodes(enum.Enum):
    # Used Login OPCodes
    OP_SessionResponse = 0x0002
    OP_Combined = 0x0003
    OP_SessionDisconnect = 0x0005
    OP_Ack = 0x0015
    OP_Packet = 0x0009
    OP_Fragment = 0x000d
    OP_ServerListResponse = 0x0018

    # Unused Login OPCodes
    OP_SessionRequest = 0x0001
    OP_ServerListRequest = 0x0004
    OP_KeepAlive = 0x0006
    OP_SessionStatRequest = 0x0007
    OP_SessionStatResponse = 0x0008
    OP_OutOfOrderAck = 0x0011
    OP_AppCombined = 0x0019
    OP_OutOfSession = 0x001d

    # Other Everquest OPCodes?
    OP_PlayEverquestResponse = 0x0021
    OP_ChatMessage = 0x0016
    OP_LoginAccepted = 0x0017
    OP_Poll = 0x0029
    OP_EnterChat = 0x000f
    OP_PollResponse = 0x0011

    OP_Unknown = 0x9999

    @classmethod
    def _missing_(cls, value):
        return cls.OP_Unknown


def get_protocol_opcode(data: bytes):
    # cstyle_opcode = struct.unpack('!H', data[:2])[0]
    opcode = int.from_bytes(data[:2], byteorder='big')
    print(f"get_protocol_opcode: {opcode} ({OPCodes(opcode).name})")
    return OPCodes(opcode)


def get_sequence(data, start_index):
    # cstyle_seq = struct.unpack('!H', data[start_index + 2:start_index + 4])[0]
    seq = int.from_bytes(data[start_index + 2:start_index + 4], byteorder='big')
    print(f"sequence: {seq}")
    return seq
