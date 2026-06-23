"""Modul serwera (wspolbiezny) gry ,,Rosyjska Ruletka''.

Odpowiedzialnosci:
  * nasluch unicast TCP (rozgrywka) -- kazde polaczenie w osobnym watku,
  * cykliczne rozglaszanie uslugi w grupie multicast (ANNOUNCE) oraz
    odpowiadanie na zapytania DISCOVER,
  * walidacja pseudonimow i zarzadzanie lista aktywnych graczy,
  * synchronizacja wspolnego stanu gry muteksem (threading.Lock),
  * sterowanie rundami (logika z modulu game),
  * logowanie zdarzen do syslog/logging,
  * tryb demona (double fork).

Uruchomienie:  python3 -m ruletka.server [opcje]
"""

import argparse
import logging
import logging.handlers
import os
import random
import selectors
import socket
import struct
import threading
import time

from . import daemon, game, protocol

log = logging.getLogger("ruletka.server")

# Domyslne parametry adresacji sa wspolne -- patrz ruletka.protocol.
ANNOUNCE_INTERVAL = 2.0      # co ile sekund rozglaszac ANNOUNCE
MCAST_TTL = 1                # zasieg multicast (1 = siec lokalna)


# ---------------------------------------------------------------------------
# Reprezentacja pojedynczego gracza / polaczenia
# ---------------------------------------------------------------------------
class Player:
    def __init__(self, pid, nick, conn, addr):
        self.id = pid
        self.nick = nick
        self.conn = conn
        self.addr = addr
        self.alive = True          # czy nie zostal jeszcze wyeliminowany
        self.connected = True      # czy gniazdo jest wciaz aktywne
        self._send_lock = threading.Lock()

    def send(self, data):
        """Wysyla ramke do klienta; zwraca False przy bledzie gniazda."""
        with self._send_lock:
            try:
                self.conn.sendall(data)
                return True
            except OSError:
                self.connected = False
                return False


# ---------------------------------------------------------------------------
# Serwer gry
# ---------------------------------------------------------------------------
class GameServer:
    def __init__(self, host, tcp_port, name, mcast_group, mcast_port,
                 lobby_timeout, max_players, shot_delay, iface=None):
        self.host = host
        self.tcp_port = tcp_port
        self.name = name
        self.mcast_group = mcast_group
        self.mcast_port = mcast_port
        self.lobby_timeout = lobby_timeout
        self.max_players = max_players          # 0 = bez limitu
        self.shot_delay = shot_delay
        # Interfejs multicast: dla IPv4 adres IP karty, dla IPv6 nazwa (np. eth0).
        # Wymagany w sieciach bez trasy domyslnej (np. VirtualBox host-only).
        self.iface = iface or None

        # --- wspolny stan gry chroniony muteksem ---
        self.lock = threading.Lock()
        self.players = {}                       # id -> Player
        self.next_id = 1
        self.state = "LOBBY"                    # LOBBY | RUNNING | FINISHED

        self.stop_event = threading.Event()
        self.tcp_socks = []                     # gniazda nasluchu (IPv4 + IPv6)
        self._threads = []

    # -- pomocnicze operacje na wspolnym stanie -----------------------------
    def _snapshot_players(self):
        with self.lock:
            return list(self.players.values())

    def broadcast(self, data):
        """Rozsyla ramke do wszystkich podlaczonych graczy (takze obserwatorow)."""
        for p in self._snapshot_players():
            if p.connected:
                p.send(data)

    def broadcast_info(self, text):
        log.info("INFO -> klienci: %s", text)
        self.broadcast(protocol.encode_info(text))

    def set_dead(self, pid):
        with self.lock:
            p = self.players.get(pid)
            if p:
                p.alive = False

    # -- gniazda TCP (unicast, dual-stack IPv4 + IPv6) ----------------------
    def _make_listening_sockets(self):
        """Otwiera gniazda nasluchu dla wszystkich rodzin adresow (IPv4/IPv6).

        Wykorzystuje ``getaddrinfo`` z ``AI_PASSIVE`` -- dla pustego adresu
        zwraca wpisy wieloznaczne dla kazdej dostepnej rodziny.  Gniazda IPv6
        ustawiane sa jako V6ONLY, dzieki czemu mozna jednoczesnie zwiazac
        wildcard IPv4 (0.0.0.0) oraz IPv6 (::) bez konfliktu portu.
        """
        socks = []
        host = self.host or None                # "" -> wszystkie interfejsy
        chosen_port = self.tcp_port
        seen = set()
        infos = socket.getaddrinfo(host, chosen_port, socket.AF_UNSPEC,
                                   socket.SOCK_STREAM, 0, socket.AI_PASSIVE)
        for family, socktype, proto, _canon, sockaddr in infos:
            if (family, sockaddr[0]) in seen:
                continue
            seen.add((family, sockaddr[0]))
            try:
                s = socket.socket(family, socktype, proto)
            except OSError:
                continue
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                try:
                    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                except OSError:
                    pass
            bind_addr = (sockaddr[0], chosen_port) + tuple(sockaddr[2:])
            try:
                s.bind(bind_addr)
                s.listen(16)
            except OSError as e:
                log.warning("Pomijam adres %s: %s", sockaddr[0], e)
                s.close()
                continue
            # Po pierwszym zwiazaniu utrwalamy port (istotne gdy podano 0).
            chosen_port = s.getsockname()[1]
            socks.append(s)
            log.info("Nasluch TCP (unicast) na %s [%s]", s.getsockname(),
                    "IPv6" if family == socket.AF_INET6 else "IPv4")
        if not socks:
            raise OSError("Nie udalo sie otworzyc zadnego gniazda nasluchu TCP")
        self.tcp_port = chosen_port
        return socks

    def _accept_loop(self):
        sel = selectors.DefaultSelector()
        for s in self.tcp_socks:
            s.setblocking(False)
            sel.register(s, selectors.EVENT_READ)
        while not self.stop_event.is_set():
            for key, _ in sel.select(timeout=0.5):
                try:
                    conn, addr = key.fileobj.accept()
                except OSError:
                    continue
                conn.setblocking(True)
                t = threading.Thread(target=self._handle_client,
                                     args=(conn, addr), daemon=True)
                t.start()
        sel.close()

    def _handle_client(self, conn, addr):
        """Obsluga pojedynczego polaczenia w osobnym watku."""
        log.info("Nowe polaczenie od %s:%d", addr[0], addr[1])
        player = None
        try:
            # Faza dolaczania: czytamy JOIN az do akceptacji pseudonimu.
            player = self._do_join(conn, addr)
            if player is None:
                return

            # Po dolaczeniu watek czyta dalej, aby wykryc rozlaczenie klienta.
            while not self.stop_event.is_set():
                msg = protocol.recv_message(conn)
                if msg is None:
                    break
                # Klient nie wysyla nic istotnego po JOIN -- ignorujemy.
        except OSError:
            pass
        finally:
            if player is not None:
                player.connected = False
                log.info("Rozlaczono gracza '%s' (id=%d)", player.nick, player.id)
            try:
                conn.close()
            except OSError:
                pass

    def _do_join(self, conn, addr):
        """Negocjacja pseudonimu. Zwraca Player albo None."""
        while not self.stop_event.is_set():
            msg = protocol.recv_message(conn)
            if msg is None:
                return None
            mtype, value = msg
            if mtype != protocol.T_JOIN:
                conn.sendall(protocol.encode_error(
                    protocol.ERR_PROTOCOL, "Oczekiwano komunikatu JOIN"))
                continue

            nick = protocol.decode_join(value).strip()

            with self.lock:
                if self.state != "LOBBY":
                    err = (protocol.ERR_BUSY, "Gra juz trwa -- sprobuj pozniej")
                elif not nick:
                    err = (protocol.ERR_NICK, "Pseudonim nie moze byc pusty")
                elif len(nick) > protocol.NICK_MAX:
                    err = (protocol.ERR_NICK,
                           "Pseudonim moze miec max %d znakow" % protocol.NICK_MAX)
                elif any(p.nick == nick for p in self.players.values()):
                    err = (protocol.ERR_NICK, "Pseudonim jest juz zajety")
                else:
                    err = None
                    pid = self.next_id
                    self.next_id += 1
                    player = Player(pid, nick, conn, addr)
                    self.players[pid] = player
                    count = len(self.players)

            if err is not None:
                code, text = err
                conn.sendall(protocol.encode_error(code, text))
                log.info("Odrzucono JOIN '%s' od %s: %s", nick, addr[0], text)
                continue

            player.send(protocol.encode_join_ack(pid, nick))
            log.info("Gracz '%s' dolaczyl jako id=%d (graczy: %d)",
                    nick, pid, count)
            self.broadcast_info("Gracz '%s' dolaczyl do gry (%d)" % (nick, count))
            return player

        return None

    @property
    def mcast_family(self):
        """Rodzina adresow grupy multicast wynika z jej zapisu (':' -> IPv6)."""
        return socket.AF_INET6 if ":" in self.mcast_group else socket.AF_INET

    def _v6_iface_index(self):
        """Indeks interfejsu IPv6 z nazwy (np. 'eth0') albo 0 = domyslny."""
        if not self.iface:
            return 0
        try:
            return socket.if_nametoindex(self.iface)
        except (OSError, ValueError):
            return 0

    def _join_multicast(self, sock):
        """Dolacza gniazdo do grupy multicast (IPv4 lub IPv6).

        Gdy podano ``--iface``, czlonkostwo zakladane jest na konkretnym
        interfejsie (konieczne w sieciach bez trasy domyslnej, np. host-only).
        """
        if self.mcast_family == socket.AF_INET6:
            group_bin = socket.inet_pton(socket.AF_INET6, self.mcast_group)
            mreq = group_bin + struct.pack("@I", self._v6_iface_index())
            opt = getattr(socket, "IPV6_JOIN_GROUP",
                          getattr(socket, "IPV6_ADD_MEMBERSHIP", 20))
            sock.setsockopt(socket.IPPROTO_IPV6, opt, mreq)
        else:
            group_bin = socket.inet_aton(self.mcast_group)
            iface_bin = (socket.inet_aton(self.iface) if self.iface
                         else struct.pack("!I", socket.INADDR_ANY))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            group_bin + iface_bin)

    def _set_multicast_iface(self, sock, fam):
        """Wskazuje interfejs wyjsciowy dla wysylanego multicastu (jezeli podano).

        Bez tego, w sieci bez trasy domyslnej, ``sendto`` na adres grupy konczy
        sie bledem ENETUNREACH ('Network is unreachable').
        """
        if not self.iface:
            return
        if fam == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF,
                            self._v6_iface_index())
        else:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                            socket.inet_aton(self.iface))

    # -- multicast: rozglaszanie ANNOUNCE -----------------------------------
    def _announce_loop(self):
        fam = self.mcast_family
        s = socket.socket(fam, socket.SOCK_DGRAM)
        if fam == socket.AF_INET6:
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, MCAST_TTL)
        else:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MCAST_TTL)
        try:
            self._set_multicast_iface(s, fam)
        except OSError as e:
            log.warning("Nie mozna ustawic interfejsu multicast (--iface %s): %s",
                        self.iface, e)
        packet = protocol.encode_announce(self.tcp_port, self.name)
        dest = (self.mcast_group, self.mcast_port)
        log.info("Rozglaszanie ANNOUNCE w grupie %s:%d [%s] (co %.1fs)",
                self.mcast_group, self.mcast_port,
                "IPv6" if fam == socket.AF_INET6 else "IPv4", ANNOUNCE_INTERVAL)
        warned = False
        while not self.stop_event.is_set():
            try:
                s.sendto(packet, dest)
                warned = False
            except OSError as e:
                if not warned:                  # logujemy raz, nie zalewamy logu
                    log.warning("Blad rozglaszania ANNOUNCE: %s. Podpowiedz: w "
                                "sieci host-only podaj --iface <ip-karty> albo "
                                "lacz klienta bezposrednio (--host <adres>).", e)
                    warned = True
            self.stop_event.wait(ANNOUNCE_INTERVAL)
        s.close()

    # -- multicast: odpowiadanie na DISCOVER --------------------------------
    def _discover_loop(self):
        fam = self.mcast_family
        s = socket.socket(fam, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        try:
            s.bind(("", self.mcast_port))
            self._join_multicast(s)
        except OSError as e:
            log.warning("Nie mozna nasluchiwac DISCOVER: %s", e)
            s.close()
            return
        s.settimeout(0.5)
        announce = protocol.encode_announce(self.tcp_port, self.name)
        while not self.stop_event.is_set():
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = protocol.parse_datagram(data)
            if parsed and parsed[0] == protocol.T_DISCOVER:
                log.info("DISCOVER od %s -> odsylam ANNOUNCE", addr[0])
                try:
                    s.sendto(announce, addr)   # odpowiedz unicast
                except OSError:
                    pass
        s.close()

    # -- sterowanie poczekalnia i startem gry -------------------------------
    def _lobby_controller(self):
        # Czekamy na pierwszego gracza.
        while not self.stop_event.is_set():
            with self.lock:
                n = len(self.players)
            if n >= 1:
                break
            time.sleep(0.2)
        if self.stop_event.is_set():
            return

        log.info("Pierwszy gracz w poczekalni -- start za %ds", self.lobby_timeout)
        self.broadcast_info("Rozpoczecie gry za %d s..." % self.lobby_timeout)
        deadline = time.time() + self.lobby_timeout
        while time.time() < deadline and not self.stop_event.is_set():
            with self.lock:
                n = len(self.players)
            if self.max_players and n >= self.max_players:
                break
            time.sleep(0.3)

        with self.lock:
            self.state = "RUNNING"
            active = [p.id for p in self.players.values() if p.connected]

        if not active:
            log.warning("Brak aktywnych graczy w chwili startu -- anulowano")
            self.state = "FINISHED"
            self.stop_event.set()
            return

        try:
            self._run_game(active)
        except Exception:                       # noqa: BLE001
            log.exception("Blad w trakcie rozgrywki")
        finally:
            with self.lock:
                self.state = "FINISHED"
            self.broadcast(protocol.encode_game_over())
            log.info("Gra zakonczona")
            self.stop_event.set()

    # -- rozgrywka ----------------------------------------------------------
    def _nick(self, pid):
        with self.lock:
            p = self.players.get(pid)
            return p.nick if p else "?"

    def _run_game(self, active):
        with self.lock:
            roster = [(p.id, p.nick) for p in self.players.values()
                      if p.id in active]
        num_players = len(active)
        num_rounds = game.rounds_for(num_players)

        self.broadcast(protocol.encode_start(num_rounds, roster))
        log.info("START: %d graczy, %d rund", num_players, num_rounds)
        time.sleep(self.shot_delay)

        if num_players == 1:
            self._run_single(active[0])
        else:
            self._run_multi(active, num_rounds)

    def _run_single(self, pid):
        """Tryb jednoosobowy: wygrana po SINGLE_WIN_STREAK pustych strzalach."""
        streak = 0
        while streak < game.SINGLE_WIN_STREAK and not self.stop_event.is_set():
            fatal = game.is_fatal_shot()
            result = protocol.RESULT_FATAL if fatal else protocol.RESULT_EMPTY
            self.broadcast(protocol.encode_shot(1, pid, result))
            log.info("SHOT solo -> '%s': %s", self._nick(pid),
                    "SMIERTELNY" if fatal else "pusty (%d/%d)"
                    % (streak + 1, game.SINGLE_WIN_STREAK))
            time.sleep(self.shot_delay)
            if fatal:
                self.set_dead(pid)
                self.broadcast(protocol.encode_eliminated(pid))
                log.info("Gracz '%s' przegral w trybie solo", self._nick(pid))
                return                          # przegrana -- brak zwyciezcy
            streak += 1

        self.broadcast(protocol.encode_winner(pid))
        log.info("Gracz '%s' wygral (przezyl %d strzalow)",
                self._nick(pid), game.SINGLE_WIN_STREAK)

    def _run_multi(self, active, num_rounds):
        """Tryb wieloosobowy: kazda runda eliminuje jednego gracza."""
        for rnd in range(1, num_rounds + 1):
            active = self._prune_disconnected(active)
            if len(active) <= 1:
                break

            eliminated = None
            idx = 0
            while eliminated is None and not self.stop_event.is_set():
                pid = active[idx % len(active)]
                fatal = game.is_fatal_shot()
                result = protocol.RESULT_FATAL if fatal else protocol.RESULT_EMPTY
                self.broadcast(protocol.encode_shot(rnd, pid, result))
                log.info("SHOT runda %d -> '%s': %s", rnd, self._nick(pid),
                        "SMIERTELNY" if fatal else "pusty")
                time.sleep(self.shot_delay)
                if fatal:
                    eliminated = pid
                idx += 1

            if eliminated is None:
                return
            active.remove(eliminated)
            self.set_dead(eliminated)
            self.broadcast(protocol.encode_eliminated(eliminated))
            self.broadcast(protocol.encode_round_end(rnd, len(active)))
            log.info("Runda %d: wyeliminowano '%s' (pozostalo %d)",
                    rnd, self._nick(eliminated), len(active))

        active = self._prune_disconnected(active)
        if active:
            winner = active[0]
            self.broadcast(protocol.encode_winner(winner))
            log.info("Zwyciezca: '%s'", self._nick(winner))

    def _prune_disconnected(self, active):
        """Usuwa z listy aktywnych graczy, ktorzy sie rozlaczyli."""
        result = []
        for pid in active:
            with self.lock:
                p = self.players.get(pid)
                ok = p is not None and p.connected
            if ok:
                result.append(pid)
            else:
                self.broadcast_info("Gracz '%s' rozlaczyl sie" % self._nick(pid))
                log.info("Gracz id=%d rozlaczony -- usuniety z rozgrywki", pid)
        return result

    # -- cykl zycia serwera -------------------------------------------------
    def serve_forever(self):
        self.tcp_socks = self._make_listening_sockets()
        targets = [self._accept_loop, self._announce_loop,
                   self._discover_loop, self._lobby_controller]
        for fn in targets:
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self._threads.append(t)
        log.info("Serwer '%s' uruchomiony", self.name)
        try:
            while not self.stop_event.is_set():
                self.stop_event.wait(0.5)
        except KeyboardInterrupt:
            log.info("Przerwano (Ctrl-C) -- zamykanie serwera")
        finally:
            self.shutdown()

    def shutdown(self):
        self.stop_event.set()
        for s in self.tcp_socks:
            try:
                s.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Konfiguracja logowania (syslog / plik / stderr)
# ---------------------------------------------------------------------------
def setup_logging(daemonized, log_file):
    root = logging.getLogger("ruletka")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    fmt = logging.Formatter("ruletka[%(process)d] %(name)s: %(message)s")

    # 1) Logi systemowe (syslog) -- preferowane na systemach uniksowych.
    for address in ("/dev/log", "/var/run/syslog"):
        if os.path.exists(address):
            try:
                h = logging.handlers.SysLogHandler(address=address)
                h.setFormatter(fmt)
                root.addHandler(h)
                break
            except OSError:
                pass

    # 2) Opcjonalny plik logu.
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s ruletka[%(process)d] %(name)s: %(message)s"))
        root.addHandler(fh)

    # 3) Konsola -- tylko gdy serwer nie jest demonem.
    if not daemonized:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s"))
        root.addHandler(sh)

    if not root.handlers:                       # awaryjnie
        root.addHandler(logging.StreamHandler())


# ---------------------------------------------------------------------------
# Punkt wejscia
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Serwer sieciowej gry 'Rosyjska Ruletka'.")
    p.add_argument("--host", default="",
                   help="adres nasluchu TCP (domyslnie puste = wszystkie "
                        "interfejsy IPv4 i IPv6)")
    p.add_argument("--port", type=int, default=protocol.DEFAULT_TCP_PORT,
                   help="port TCP rozgrywki (domyslnie %d)" % protocol.DEFAULT_TCP_PORT)
    p.add_argument("--name", default=socket.gethostname(),
                   help="nazwa serwera rozglaszana w multicast")
    p.add_argument("--group", default=protocol.DEFAULT_MCAST_GROUP,
                   help="grupa multicast: IPv4 %s lub IPv6 np. %s"
                        % (protocol.DEFAULT_MCAST_GROUP, protocol.DEFAULT_MCAST_GROUP6))
    p.add_argument("--mcast-port", type=int, default=protocol.DEFAULT_MCAST_PORT,
                   help="port multicast (domyslnie %d)" % protocol.DEFAULT_MCAST_PORT)
    p.add_argument("--iface", default=None,
                   help="interfejs multicast: adres IP karty (IPv4) lub nazwa "
                        "np. eth0 (IPv6). Wymagany w sieci host-only / bez trasy "
                        "domyslnej")
    p.add_argument("--lobby-timeout", type=int, default=15,
                   help="czas poczekalni od 1. gracza w sekundach (domyslnie 15)")
    p.add_argument("--max-players", type=int, default=0,
                   help="start od razu po N graczach (0 = bez limitu)")
    p.add_argument("--shot-delay", type=float, default=1.0,
                   help="odstep miedzy strzalami w sekundach (domyslnie 1.0)")
    p.add_argument("--daemon", action="store_true",
                   help="uruchom jako demon (tryb w tle, tylko Unix)")
    p.add_argument("--log-file", default=None,
                   help="dodatkowy plik logu")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.daemon:
        daemon.daemonize()                      # double fork (Unix)

    setup_logging(args.daemon, args.log_file)
    random.seed()                               # rozne wyniki w kazdym procesie

    server = GameServer(
        host=args.host, tcp_port=args.port, name=args.name,
        mcast_group=args.group, mcast_port=args.mcast_port,
        lobby_timeout=args.lobby_timeout, max_players=args.max_players,
        shot_delay=args.shot_delay, iface=args.iface,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
