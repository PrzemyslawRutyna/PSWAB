"""Binarny protokol TLV: typ (1B) + dlugosc (2B) + wartosc (NB), big-endian."""

import struct

# typy komunikatow (1. bajt ramki); w komentarzu uklad pola wartosci
T_ANNOUNCE = 0x01    # [port:2][nazwa]   serwer -> multicast
T_DISCOVER = 0x02    # []                klient -> multicast
T_JOIN = 0x10        # [pseudonim]
T_JOIN_ACK = 0x11    # [id:1][pseudonim]
T_START = 0x12       # [rundy:1][gracze:1] + roster
T_SHOT = 0x13        # [runda:1][id:1][wynik:1]
T_ELIMINATED = 0x14  # [id:1]
T_ROUND_END = 0x15   # [runda:1][pozostali:1]
T_WINNER = 0x16      # [id:1]
T_GAME_OVER = 0x17   # []
T_ERROR = 0x18       # [kod:1][tekst]
T_INFO = 0x19        # [tekst]

TYPE_NAMES = {
    T_ANNOUNCE: "ANNOUNCE", T_DISCOVER: "DISCOVER", T_JOIN: "JOIN",
    T_JOIN_ACK: "JOIN_ACK", T_START: "START", T_SHOT: "SHOT",
    T_ELIMINATED: "ELIMINATED", T_ROUND_END: "ROUND_END", T_WINNER: "WINNER",
    T_GAME_OVER: "GAME_OVER", T_ERROR: "ERROR", T_INFO: "INFO",
}

# wynik strzalu
RESULT_EMPTY = 0     # pusto
RESULT_FATAL = 1     # smiertelny

# kody bledow
ERR_PROTOCOL = 0
ERR_NICK = 1
ERR_BUSY = 2

# domyslna adresacja (wspolna dla klienta i serwera)
DEFAULT_TCP_PORT = 50000
DEFAULT_MCAST_GROUP = "239.0.0.1"    # IPv4
DEFAULT_MCAST_GROUP6 = "ff15::1"     # IPv6 (site-local)
DEFAULT_MCAST_PORT = 50001

_HEADER = struct.Struct("!BH")       # typ + dlugosc, big-endian
HEADER_SIZE = _HEADER.size
MAX_VALUE = 0xFFFF
NICK_MAX = 12


def encode(mtype, value=b""):
    if len(value) > MAX_VALUE:
        raise ValueError("Wartosc TLV przekracza %d bajtow" % MAX_VALUE)
    return _HEADER.pack(mtype, len(value)) + value


def recv_exact(sock, n):
    """Czyta dokladnie n bajtow; None gdy polaczenie zamkniete."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def recv_message(sock):
    """Jeden komunikat TLV z TCP: (typ, value) albo None przy rozlaczeniu."""
    head = recv_exact(sock, HEADER_SIZE)
    if head is None:
        return None
    mtype, length = _HEADER.unpack(head)
    value = b""
    if length:
        value = recv_exact(sock, length)
        if value is None:
            return None
    return mtype, value


def parse_datagram(data):
    """Jeden komunikat TLV z datagramu UDP."""
    if len(data) < HEADER_SIZE:
        return None
    mtype, length = _HEADER.unpack(data[:HEADER_SIZE])
    value = data[HEADER_SIZE:HEADER_SIZE + length]
    if len(value) < length:
        return None
    return mtype, value


def encode_announce(tcp_port, name):
    return encode(T_ANNOUNCE, struct.pack("!H", tcp_port) + name.encode("utf-8"))


def decode_announce(value):
    (port,) = struct.unpack("!H", value[:2])
    return port, value[2:].decode("utf-8", "replace")


def encode_discover():
    return encode(T_DISCOVER)


def encode_join(nick):
    return encode(T_JOIN, nick.encode("utf-8"))


def decode_join(value):
    return value.decode("utf-8", "replace")


def encode_join_ack(pid, nick):
    return encode(T_JOIN_ACK, struct.pack("!B", pid) + nick.encode("utf-8"))


def decode_join_ack(value):
    return value[0], value[1:].decode("utf-8", "replace")


def encode_start(num_rounds, roster):
    """roster: lista (id, pseudonim)."""
    parts = [struct.pack("!BB", num_rounds, len(roster))]
    for pid, nick in roster:
        nb = nick.encode("utf-8")
        parts.append(struct.pack("!BB", pid, len(nb)))
        parts.append(nb)
    return encode(T_START, b"".join(parts))


def decode_start(value):
    num_rounds, count = struct.unpack("!BB", value[:2])
    roster = []
    off = 2
    for _ in range(count):
        pid, nlen = struct.unpack("!BB", value[off:off + 2])
        off += 2
        nick = value[off:off + nlen].decode("utf-8", "replace")
        off += nlen
        roster.append((pid, nick))
    return num_rounds, roster


def encode_shot(rnd, pid, result):
    return encode(T_SHOT, struct.pack("!BBB", rnd, pid, result))


def decode_shot(value):
    return struct.unpack("!BBB", value)             # (runda, id, wynik)


def encode_eliminated(pid):
    return encode(T_ELIMINATED, struct.pack("!B", pid))


def decode_eliminated(value):
    return value[0]


def encode_round_end(rnd, survivors):
    return encode(T_ROUND_END, struct.pack("!BB", rnd, survivors))


def decode_round_end(value):
    return struct.unpack("!BB", value)              # (runda, pozostali)


def encode_winner(pid):
    return encode(T_WINNER, struct.pack("!B", pid))


def decode_winner(value):
    return value[0]


def encode_game_over():
    return encode(T_GAME_OVER)


def encode_error(code, text):
    return encode(T_ERROR, struct.pack("!B", code) + text.encode("utf-8"))


def decode_error(value):
    return value[0], value[1:].decode("utf-8", "replace")


def encode_info(text):
    return encode(T_INFO, text.encode("utf-8"))


def decode_info(value):
    return value.decode("utf-8", "replace")
