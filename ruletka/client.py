"""Klient gry "Rosyjska Ruletka": wyszukiwanie (multicast/DNS) + rozgrywka."""

import argparse
import socket
import struct
import sys
import time

from . import protocol
from .protocol import (DEFAULT_MCAST_GROUP, DEFAULT_MCAST_GROUP6,
                       DEFAULT_MCAST_PORT, DEFAULT_TCP_PORT)


def discover_servers(group, mcast_port, timeout, iface=None):
    """DISCOVER + zbieranie ANNOUNCE; zwraca [(nazwa, host, port)] (IPv4/IPv6)."""
    family = socket.AF_INET6 if ":" in group else socket.AF_INET

    def v6_index():
        try:
            return socket.if_nametoindex(iface) if iface else 0
        except (OSError, ValueError):
            return 0

    s = socket.socket(family, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    try:
        s.bind(("", mcast_port))                # czlonkostwo w grupie
        if family == socket.AF_INET6:
            mreq = socket.inet_pton(socket.AF_INET6, group) + struct.pack("@I", v6_index())
            opt = getattr(socket, "IPV6_JOIN_GROUP",
                          getattr(socket, "IPV6_ADD_MEMBERSHIP", 20))
            s.setsockopt(socket.IPPROTO_IPV6, opt, mreq)
        else:
            iface_bin = (socket.inet_aton(iface) if iface
                         else struct.pack("!I", socket.INADDR_ANY))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         socket.inet_aton(group) + iface_bin)
    except OSError:
        s.close()                               # port zajety -> sam DISCOVER
        s = socket.socket(family, socket.SOCK_DGRAM)

    try:                                        # interfejs wyjsciowy multicastu
        if family == socket.AF_INET6:
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
            if iface:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, v6_index())
        else:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            if iface:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                             socket.inet_aton(iface))
    except OSError:
        pass

    try:
        s.sendto(protocol.encode_discover(), (group, mcast_port))
    except OSError as e:
        print("Uwaga: nie udalo sie wyslac DISCOVER (%s)." % e)
        print("  Siec bez trasy multicast (np. host-only). Sprobuj: "
              "--iface <ip-karty> albo polacz bezposrednio: --host <adres>.")

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
            host = addr[0]
            if family == socket.AF_INET6 and len(addr) >= 4 and addr[3]:
                if "%" not in host:             # scope IPv6 link-local
                    host = "%s%%%d" % (host, addr[3])
            found[(host, port)] = name
    s.close()
    return [(name, host, port) for (host, port), name in found.items()]


def resolve(host, port):
    """DNS przez getaddrinfo (AF_UNSPEC); zwraca [(rodzina, ip)]."""
    infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    out = []
    seen = set()
    for family, _stype, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in seen:
            seen.add(ip)
            out.append((family, ip))
    return out


class GamePrinter:
    def __init__(self, my_id):
        self.my_id = my_id
        self.roster = {}            # id -> pseudonim

    def name(self, pid):
        return self.roster.get(pid, "gracz#%d" % pid)

    def _me(self, pid):
        return " (TY)" if pid == self.my_id else ""

    def handle(self, mtype, value):
        """Obsluga komunikatu; False gdy koniec gry."""
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


def choose_server(args):
    """Zwraca (host, port) z argumentow (DNS) albo z wyszukiwania multicast."""
    if args.host:
        print("Rozwiazywanie nazwy '%s' (DNS, IPv4/IPv6)..." % args.host)
        try:
            addrs = resolve(args.host, args.port)
        except socket.gaierror as e:
            print("Blad rozwiazywania nazwy: %s" % e)
            return None
        for family, ip in addrs:
            label = "IPv6" if family == socket.AF_INET6 else "IPv4"
            print("  -> %s (%s)" % (ip, label))
        return args.host, args.port             # create_connection sprobuje wszystkich

    print("Wyszukiwanie serwerow w sieci (multicast %s:%d, %ds)..."
          % (args.group, args.mcast_port, args.discover_timeout))
    servers = discover_servers(args.group, args.mcast_port, args.discover_timeout,
                               args.iface)
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
    """JOIN z walidacja pseudonimu (ponawianie); zwraca id albo None."""
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
                   help="adres/nazwa serwera (pomija multicast)")
    p.add_argument("--port", type=int, default=DEFAULT_TCP_PORT,
                   help="port TCP serwera (domyslnie %d)" % DEFAULT_TCP_PORT)
    p.add_argument("--nick", default=None,
                   help="pseudonim gracza (max %d znakow)" % protocol.NICK_MAX)
    p.add_argument("--group", default=DEFAULT_MCAST_GROUP,
                   help="grupa multicast (IPv4 %s / IPv6 %s)"
                        % (DEFAULT_MCAST_GROUP, DEFAULT_MCAST_GROUP6))
    p.add_argument("--mcast-port", type=int, default=DEFAULT_MCAST_PORT,
                   help="port multicast (domyslnie %d)" % DEFAULT_MCAST_PORT)
    p.add_argument("--iface", default=None,
                   help="interfejs multicast: IP karty (IPv4) lub nazwa np. eth0 (IPv6)")
    p.add_argument("--discover-timeout", type=float, default=3.0,
                   help="czas wyszukiwania serwerow [s]")
    p.add_argument("--list", action="store_true",
                   help="tylko wypisz wykryte serwery")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.list:
        servers = discover_servers(args.group, args.mcast_port,
                                   args.discover_timeout, args.iface)
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
