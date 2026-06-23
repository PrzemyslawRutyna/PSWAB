"""Modul protokolu (TLV) -- wspolny dla klienta i serwera.

Wszystkie komunikaty kodowane sa binarnie w formacie TLV:

    +--------+----------+-----------------+
    | Type   | Length   | Value           |
    | 1 bajt | 2 bajty  | N bajtow        |
    +--------+----------+-----------------+

Naglowek pakowany jest funkcja ``struct.pack`` w sieciowej kolejnosci bajtow
(big-endian, format ``!BH``).  Pole Length okresla dlugosc czesci Value
(0..65535).  Pojedyncze datagramy UDP (multicast) niosa dokladnie jeden
komunikat TLV; po stronie TCP komunikaty czytane sa strumieniowo.
"""

import struct

# ---------------------------------------------------------------------------
# Typy komunikatow (pole Type)
# ---------------------------------------------------------------------------
T_ANNOUNCE = 0x01    # serwer -> multicast : [port:2][nazwa]
T_DISCOVER = 0x02    # klient -> multicast : [] (prosba o rozglos)
T_JOIN = 0x10        # klient -> serwer    : [pseudonim utf-8]
T_JOIN_ACK = 0x11    # serwer -> klient    : [id:1][pseudonim]
T_START = 0x12       # serwer -> klient    : [rundy:1][gracze:1] + roster
T_SHOT = 0x13        # serwer -> klient    : [runda:1][id:1][wynik:1]
T_ELIMINATED = 0x14  # serwer -> klient    : [id:1]
T_ROUND_END = 0x15   # serwer -> klient    : [runda:1][pozostali:1]
T_WINNER = 0x16      # serwer -> klient    : [id:1]
T_GAME_OVER = 0x17   # serwer -> klient    : []
T_ERROR = 0x18       # serwer -> klient    : [kod:1][tekst utf-8]
T_INFO = 0x19        # serwer -> klient    : [tekst utf-8]

TYPE_NAMES = {
    T_ANNOUNCE: "ANNOUNCE", T_DISCOVER: "DISCOVER", T_JOIN: "JOIN",
    T_JOIN_ACK: "JOIN_ACK", T_START: "START", T_SHOT: "SHOT",
    T_ELIMINATED: "ELIMINATED", T_ROUND_END: "ROUND_END", T_WINNER: "WINNER",
    T_GAME_OVER: "GAME_OVER", T_ERROR: "ERROR", T_INFO: "INFO",
}

# Wyniki strzalu (pole wynik w komunikacie SHOT)
RESULT_EMPTY = 0     # pusta komora -- gracz przezyl
RESULT_FATAL = 1     # smiertelny strzal -- gracz wyeliminowany

# Kody bledow (komunikat ERROR)
ERR_PROTOCOL = 0     # naruszenie protokolu
ERR_NICK = 1         # bledny pseudonim
ERR_BUSY = 2         # gra juz trwa / brak miejsc

# Domyslne parametry adresacji -- wspolne dla klienta i serwera.
DEFAULT_TCP_PORT = 50000             # unicast TCP (rozgrywka)
DEFAULT_MCAST_GROUP = "239.0.0.1"    # grupa multicast IPv4
DEFAULT_MCAST_GROUP6 = "ff15::1"     # grupa multicast IPv6 (zasieg site-local)
DEFAULT_MCAST_PORT = 50001           # multicast (wyszukiwanie uslugi)

# Naglowek TLV: 1 bajt typ + 2 bajty dlugosc, big-endian.
_HEADER = struct.Struct("!BH")
HEADER_SIZE = _HEADER.size
MAX_VALUE = 0xFFFF
NICK_MAX = 12


# ---------------------------------------------------------------------------
# Kodowanie / dekodowanie ramki
# ---------------------------------------------------------------------------
def encode(mtype, value=b""):
    """Zwraca bajty pojedynczej ramki TLV."""
    if len(value) > MAX_VALUE:
        raise ValueError("Wartosc TLV przekracza %d bajtow" % MAX_VALUE)
    return _HEADER.pack(mtype, len(value)) + value


def recv_exact(sock, n):
    """Czyta dokladnie *n* bajtow z gniazda TCP.

    Zwraca ``None`` jezeli polaczenie zostalo zamkniete przed odebraniem
    kompletu danych.
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def recv_message(sock):
    """Odbiera jeden komunikat TLV z gniazda strumieniowego (TCP).

    Zwraca krotke ``(typ, value)`` albo ``None`` przy rozlaczeniu.
    """
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
    """Parsuje pojedynczy datagram UDP zawierajacy jedna ramke TLV."""
    if len(data) < HEADER_SIZE:
        return None
    mtype, length = _HEADER.unpack(data[:HEADER_SIZE])
    value = data[HEADER_SIZE:HEADER_SIZE + length]
    if len(value) < length:
        return None
    return mtype, value


# ---------------------------------------------------------------------------
# Konstruktory poszczegolnych komunikatow
# ---------------------------------------------------------------------------
def encode_announce(tcp_port, name):
    return encode(T_ANNOUNCE, struct.pack("!H", tcp_port) + name.encode("utf-8"))


def decode_announce(value):
    (port,) = struct.unpack("!H", value[:2])
    name = value[2:].decode("utf-8", "replace")
    return port, name


def encode_discover():
    return encode(T_DISCOVER)


def encode_join(nick):
    return encode(T_JOIN, nick.encode("utf-8"))


def decode_join(value):
    return value.decode("utf-8", "replace")


def encode_join_ack(pid, nick):
    return encode(T_JOIN_ACK, struct.pack("!B", pid) + nick.encode("utf-8"))


def decode_join_ack(value):
    pid = value[0]
    nick = value[1:].decode("utf-8", "replace")
    return pid, nick


def encode_start(num_rounds, roster):
    """roster: lista krotek ``(id, pseudonim)`` graczy bioracych udzial."""
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
    return struct.unpack("!BBB", value)  # (runda, id, wynik)


def encode_eliminated(pid):
    return encode(T_ELIMINATED, struct.pack("!B", pid))


def decode_eliminated(value):
    return value[0]


def encode_round_end(rnd, survivors):
    return encode(T_ROUND_END, struct.pack("!BB", rnd, survivors))


def decode_round_end(value):
    return struct.unpack("!BB", value)  # (runda, pozostali)


def encode_winner(pid):
    return encode(T_WINNER, struct.pack("!B", pid))


def decode_winner(value):
    return value[0]


def encode_game_over():
    return encode(T_GAME_OVER)


def encode_error(code, text):
    return encode(T_ERROR, struct.pack("!B", code) + text.encode("utf-8"))


def decode_error(value):
    code = value[0]
    text = value[1:].decode("utf-8", "replace")
    return code, text


def encode_info(text):
    return encode(T_INFO, text.encode("utf-8"))


def decode_info(value):
    return value.decode("utf-8", "replace")
