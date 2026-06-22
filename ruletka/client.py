"""Modul klienta gry ,,Rosyjska Ruletka''.

Odpowiedzialnosci:
  * wyszukanie serwera w sieci lokalnej (multicast: wyslanie DISCOVER i
    odbior ANNOUNCE) albo rozwiazanie nazwy hosta przez DNS (getaddrinfo),
  * nawiazanie polaczenia unicast TCP i wprowadzenie pseudonimu,
  * odbior i prezentacja komunikatow: stanu gry, strzalow, eliminacji,
    zwyciezcy i konca gry.

Uruchomienie:  python3 -m ruletka.client [opcje]
"""

import argparse
import socket
import struct
import sys
import time

from . import protocol
from .protocol import DEFAULT_MCAST_GROUP, DEFAULT_MCAST_PORT, DEFAULT_TCP_PORT


# ---------------------------------------------------------------------------
# Wyszukiwanie serwera (multicast)
# ---------------------------------------------------------------------------
def discover_servers(group, mcast_port, timeout):
    """Wysyla DISCOVER i zbiera odpowiedzi ANNOUNCE przez *timeout* sekund.

    Zwraca liste krotek ``(nazwa, ip, port_tcp)`` (bez duplikatow).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    # Dolaczamy do grupy, aby odbierac takze cykliczne ANNOUNCE serwera.
    try:
        s.bind(("", mcast_port))
        mreq = struct.pack("4sl", socket.inet_aton(group), socket.INADDR_ANY)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError:
        # Gdy port zajety, mozemy nadal wyslac DISCOVER i sluchac odpowiedzi
        # unicast na efemerycznym porcie.
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    s.sendto(protocol.encode_discover(), (group, mcast_port))

    found = {}
    s.settimeout(0.4)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        parsed = protocol.parse_datagram(data)
        if parsed and parsed[0] == protocol.T_ANNOUNCE:
            port, name = protocol.decode_announce(parsed[1])
            found[(addr[0], port)] = name
    s.close()
    return [(name, ip, port) for (ip, port), name in found.items()]


def resolve(host, port):
    """Rozwiazuje nazwe hosta na adres IPv4 (DNS) -- socket.getaddrinfo()."""
    infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    return infos[0][4]          # (ip, port)


# ---------------------------------------------------------------------------
# Prezentacja komunikatow
# ---------------------------------------------------------------------------
class GamePrinter:
    def __init__(self, my_id):
        self.my_id = my_id
        self.roster = {}        # id -> pseudonim

    def name(self, pid):
        return self.roster.get(pid, "gracz#%d" % pid)

    def _me(self, pid):
        return " (TY)" if pid == self.my_id else ""

    def handle(self, mtype, value):
        """Obsluga jednego komunikatu. Zwraca False gdy gra sie zakonczyla."""
        if mtype == protocol.T_INFO:
            print("  [i] " + protocol.decode_info(value))

        elif mtype == protocol.T_START:
            num_rounds, roster = protocol.decode_start(value)
            self.roster = dict(roster)
            names = ", ".join("%s%s" % (n, self._me(i)) for i, n in roster)
            print("\n=== GRA SIE ROZPOCZYNA ===")
            print("  Graczy: %d | Rund: %d" % (len(roster), num_rounds))
            print("  Uczestnicy: " + names + "\n")

        elif mtype == protocol.T_SHOT:
            rnd, pid, result = protocol.decode_shot(value)
            if result == protocol.RESULT_FATAL:
                print("  [runda %d] BANG! Strzal do '%s'%s -- SMIERTELNY!"
                      % (rnd, self.name(pid), self._me(pid)))
            else:
                print("  [runda %d] *klik* '%s'%s -- pusta komora"
                      % (rnd, self.name(pid), self._me(pid)))

        elif mtype == protocol.T_ELIMINATED:
            pid = protocol.decode_eliminated(value)
            print("  --> '%s'%s zostaje wyeliminowany (obserwator)\n"
                  % (self.name(pid), self._me(pid)))

        elif mtype == protocol.T_ROUND_END:
            rnd, survivors = protocol.decode_round_end(value)
            print("  --- koniec rundy %d, pozostalo graczy: %d ---\n"
                  % (rnd, survivors))

        elif mtype == protocol.T_WINNER:
            pid = protocol.decode_winner(value)
            if pid == self.my_id:
                print("\n***** WYGRYWASZ! Jestes ostatnim ocalalym! *****")
            else:
                print("\n***** ZWYCIEZCA: '%s' *****" % self.name(pid))

        elif mtype == protocol.T_GAME_OVER:
            print("=== KONIEC GRY ===")
            return False

        elif mtype == protocol.T_ERROR:
            code, text = protocol.decode_error(value)
            print("  [BLAD] " + text)

        else:
            print("  [?] nieznany komunikat typu 0x%02x" % mtype)

        return True


# ---------------------------------------------------------------------------
# Logika klienta
# ---------------------------------------------------------------------------
def choose_server(args):
    """Zwraca (ip, port) serwera na podstawie argumentow lub wyszukiwania."""
    if args.host:
        print("Rozwiazywanie nazwy '%s' (DNS)..." % args.host)
        ip, port = resolve(args.host, args.port)
        print("  -> %s:%d" % (ip, port))
        return ip, port

    print("Wyszukiwanie serwerow w sieci (multicast %s:%d, %ds)..."
          % (args.group, args.mcast_port, args.discover_timeout))
    servers = discover_servers(args.group, args.mcast_port, args.discover_timeout)
    if not servers:
        print("Nie znaleziono serwerow. Podaj adres recznie opcja --host.")
        return None

    if len(servers) == 1:
        name, ip, port = servers[0]
        print("Znaleziono serwer: %s (%s:%d)" % (name, ip, port))
        return ip, port

    print("Znalezione serwery:")
    for i, (name, ip, port) in enumerate(servers, 1):
        print("  %d) %s  %s:%d" % (i, name, ip, port))
    while True:
        sel = input("Wybierz numer serwera: ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(servers):
            _, ip, port = servers[int(sel) - 1]
            return ip, port
        print("Nieprawidlowy wybor.")


def join_game(sock, nick):
    """Wysyla JOIN i obsluguje walidacje pseudonimu. Zwraca id albo None."""
    while True:
        sock.sendall(protocol.encode_join(nick))
        msg = protocol.recv_message(sock)
        if msg is None:
            print("Serwer zamknal polaczenie.")
            return None
        mtype, value = msg
        if mtype == protocol.T_JOIN_ACK:
            pid, acc_nick = protocol.decode_join_ack(value)
            print("Dolaczono jako '%s' (id=%d).\n" % (acc_nick, pid))
            return pid
        if mtype == protocol.T_ERROR:
            _, text = protocol.decode_error(value)
            print("Odmowa: %s" % text)
            nick = input("Podaj pseudonim (max %d znakow): "
                         % protocol.NICK_MAX).strip()
        else:
            print("Nieoczekiwana odpowiedz serwera (0x%02x)." % mtype)
            return None


def play(sock, my_id):
    printer = GamePrinter(my_id)
    print("Oczekiwanie na rozpoczecie gry...\n")
    while True:
        msg = protocol.recv_message(sock)
        if msg is None:
            print("\nPolaczenie z serwerem zostalo zamkniete.")
            return
        mtype, value = msg
        if not printer.handle(mtype, value):
            return


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Klient sieciowej gry 'Rosyjska Ruletka'.")
    p.add_argument("--host", default=None,
                   help="adres lub nazwa serwera (pomija wyszukiwanie multicast)")
    p.add_argument("--port", type=int, default=DEFAULT_TCP_PORT,
                   help="port TCP serwera (domyslnie %d)" % DEFAULT_TCP_PORT)
    p.add_argument("--nick", default=None,
                   help="pseudonim gracza (max %d znakow)" % protocol.NICK_MAX)
    p.add_argument("--group", default=DEFAULT_MCAST_GROUP,
                   help="grupa multicast (domyslnie %s)" % DEFAULT_MCAST_GROUP)
    p.add_argument("--mcast-port", type=int, default=DEFAULT_MCAST_PORT,
                   help="port multicast (domyslnie %d)" % DEFAULT_MCAST_PORT)
    p.add_argument("--discover-timeout", type=float, default=3.0,
                   help="czas wyszukiwania serwerow w sekundach (domyslnie 3)")
    p.add_argument("--list", action="store_true",
                   help="tylko wyszukaj i wypisz serwery, nie dolaczaj")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.list:
        servers = discover_servers(args.group, args.mcast_port,
                                   args.discover_timeout)
        if not servers:
            print("Nie znaleziono serwerow.")
        for name, ip, port in servers:
            print("%s  %s:%d" % (name, ip, port))
        return

    target = choose_server(args)
    if target is None:
        sys.exit(1)
    ip, port = target

    print("Laczenie z %s:%d (TCP unicast)..." % (ip, port))
    try:
        sock = socket.create_connection((ip, port), timeout=10)
    except OSError as e:
        print("Nie mozna polaczyc sie z serwerem: %s" % e)
        sys.exit(1)
    sock.settimeout(None)

    try:
        nick = args.nick
        if not nick:
            nick = input("Podaj pseudonim (max %d znakow): "
                         % protocol.NICK_MAX).strip()
        my_id = join_game(sock, nick)
        if my_id is None:
            return
        play(sock, my_id)
    except KeyboardInterrupt:
        print("\nPrzerwano.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
