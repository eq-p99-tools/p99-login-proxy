import socket
import datetime
import time
import ctypes

import connection
import sequence

MIDDLEMAN_PORT = 5998
REMOTE_HOST = "login.eqemulator.net"
REMOTE_PORT = "5998"

BUFFER_SIZE = 2048
SESSION_TIMEOUT_SECONDS = 60

class Connection:
    socket = None
    inSession = None
    lastRecvTime: datetime = None
    localAddr = None
    remoteAddr = None

    def __init__(self):
        self.buffer = bytearray(1024)
        self.remoteAddr = None
        self.localAddr = None
        self.socket = None
        self.inSession = False
        self.lastRecvTime = 0
        self.sequence = sequence.Sequence()
        self.jmpBuf = ctypes.create_string_buffer(256)

def connection_open(con):
    addr = ('', 0)
    hints = socket.getaddrinfo(REMOTE_HOST, REMOTE_PORT, socket.AF_INET, socket.SOCK_DGRAM)

    if not hints:
        raise Exception("ERR_GETADDRINFO_CALL")

    con.remoteAddr = hints[0][4]

    con.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if con.socket == -1:
        raise Exception("ERR_SOCKET_CALL")

    con.socket.bind((addr[0], MIDDLEMAN_PORT))

    con.inSession = False
    con.lastRecvTime = 0

def connection_close(con):
    if con.socket:
        con.socket.close()
        con.socket = None

    sequence.sequence_free(con)

def connection_read(con):
    try:
        data, addr = con.socket.recvfrom(1024)
    except socket.error as e:
        if e.errno not in (socket.EWOULDBLOCK, socket.EAGAIN, socket.ESHUTDOWN):
            raise Exception("ERR_RECVFROM")
        return

    recvTime = time.time()

    if addr == con.remoteAddr:
        connection.recv_from_remote(con, data, len(data))
    else:
        if not con.inSession or (recvTime - con.lastRecvTime) > SESSION_TIMEOUT_SECONDS:
            connection_reset(con, addr)
        connection.recv_from_local(con, len(data))

    con.lastRecvTime = recvTime

def connection_send(con, data, toRemote):
    addr = con.remoteAddr if toRemote else con.localAddr

    try:
        con.socket.sendto(data, addr)
    except socket.error:
        raise Exception("ERR_SENDTO")

def connection_reset(con, addr):
    con.localAddr = addr
    sequence.sequence_free(con)