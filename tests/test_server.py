"""Testy integracyjne serwera (ruletka.server).

Uruchamiaja prawdziwy serwer na loopbacku (127.0.0.1, port dynamiczny) i lacza
sie z nim surowymi gniazdami TCP, sprawdzajac:
  * walidacje pseudonimu (pusty, za dlugi, zajety, brak JOIN),
  * pelny przebieg gry dla dwoch graczy (START -> SHOT -> ELIMINATED ->
    ROUND_END -> WINNER -> GAME_OVER) oraz spojnosc stanu wspoldzielonego.

Testy nie korzystaja z multicast (uruchamiane sa tylko watki TCP), dzieki
czemu sa stabilne takze poza Linuksem.
"""

import socket
import threading
import unittest

from ruletka import protocol, server


def _start_server(with_lobby, **overrides):
    """Tworzy serwer na 127.0.0.1 i uruchamia wymagane watki TCP."""
    params = dict(
        host="127.0.0.1", tcp_port=0, name="test",
        mcast_group=protocol.DEFAULT_MCAST_GROUP, mcast_port=0,
        lobby_timeout=60, max_players=0, shot_delay=0.0,
    )
    params.update(overrides)
    srv = server.GameServer(**params)
    srv.tcp_socks = srv._make_listening_sockets()      # ustala srv.tcp_port
    threading.Thread(target=srv._accept_loop, daemon=True).start()
    if with_lobby:
        threading.Thread(target=srv._lobby_controller, daemon=True).start()
    return srv


def _connect(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.settimeout(5)
    return s


def _recv(sock):
    """Odbiera jeden komunikat (typ, value); None przy rozlaczeniu/timeout."""
    try:
        return protocol.recv_message(sock)
    except socket.timeout:
        return None


def _drain_until_game_over(sock, sink):
    """Czyta komunikaty az do GAME_OVER, dopisujac (typ, value) do *sink*."""
    sock.settimeout(10)
    while True:
        msg = _recv(sock)
        if msg is None:
            return
        sink.append(msg)
        if msg[0] == protocol.T_GAME_OVER:
            return


class TestNickValidation(unittest.TestCase):
    def setUp(self):
        self.srv = _start_server(with_lobby=False)
        self.addCleanup(self.srv.shutdown)
        self.port = self.srv.tcp_port

    def test_empty_nick_rejected_then_retry(self):
        s = _connect(self.port)
        self.addCleanup(s.close)

        s.sendall(protocol.encode_join(""))
        mtype, value = _recv(s)
        self.assertEqual(mtype, protocol.T_ERROR)
        self.assertEqual(protocol.decode_error(value)[0], protocol.ERR_NICK)

        # To samo polaczenie pozwala ponowic z poprawnym pseudonimem.
        s.sendall(protocol.encode_join("Bob"))
        mtype, value = _recv(s)
        self.assertEqual(mtype, protocol.T_JOIN_ACK)
        self.assertEqual(protocol.decode_join_ack(value)[1], "Bob")

    def test_too_long_nick_rejected(self):
        s = _connect(self.port)
        self.addCleanup(s.close)
        s.sendall(protocol.encode_join("x" * (protocol.NICK_MAX + 1)))
        mtype, value = _recv(s)
        self.assertEqual(mtype, protocol.T_ERROR)
        self.assertEqual(protocol.decode_error(value)[0], protocol.ERR_NICK)

    def test_duplicate_nick_rejected(self):
        s1 = _connect(self.port)
        self.addCleanup(s1.close)
        s1.sendall(protocol.encode_join("Ala"))
        self.assertEqual(_recv(s1)[0], protocol.T_JOIN_ACK)

        s2 = _connect(self.port)
        self.addCleanup(s2.close)
        s2.sendall(protocol.encode_join("Ala"))
        mtype, value = _recv(s2)
        self.assertEqual(mtype, protocol.T_ERROR)
        self.assertEqual(protocol.decode_error(value)[0], protocol.ERR_NICK)

    def test_first_message_must_be_join(self):
        s = _connect(self.port)
        self.addCleanup(s.close)
        # Komunikat inny niz JOIN -> blad protokolu, polaczenie utrzymane.
        s.sendall(protocol.encode_info("nie-join"))
        mtype, value = _recv(s)
        self.assertEqual(mtype, protocol.T_ERROR)
        self.assertEqual(protocol.decode_error(value)[0], protocol.ERR_PROTOCOL)


class TestFullGameTwoPlayers(unittest.TestCase):
    def test_two_players_play_to_winner(self):
        # Start natychmiast po dolaczeniu 2 graczy (max_players=2).
        srv = _start_server(with_lobby=True, lobby_timeout=2, max_players=2)
        self.addCleanup(srv.shutdown)
        port = srv.tcp_port

        sa = _connect(port)
        self.addCleanup(sa.close)
        sb = _connect(port)
        self.addCleanup(sb.close)

        sa.sendall(protocol.encode_join("Ala"))
        id_a = protocol.decode_join_ack(_recv(sa)[1])[0]
        sb.sendall(protocol.encode_join("Bob"))
        id_b = protocol.decode_join_ack(_recv(sb)[1])[0]
        self.assertNotEqual(id_a, id_b)

        # Czytamy oba strumienie rownolegle az do GAME_OVER.
        msgs_a, msgs_b = [], []
        ta = threading.Thread(target=_drain_until_game_over, args=(sa, msgs_a))
        tb = threading.Thread(target=_drain_until_game_over, args=(sb, msgs_b))
        ta.start(); tb.start()
        ta.join(15); tb.join(15)

        for label, msgs in (("Ala", msgs_a), ("Bob", msgs_b)):
            types = [m[0] for m in msgs]
            self.assertIn(protocol.T_START, types, "%s: brak START" % label)
            self.assertIn(protocol.T_GAME_OVER, types, "%s: brak GAME_OVER" % label)
            # Dwoch graczy -> jedna runda -> dokladnie jedna eliminacja.
            self.assertEqual(types.count(protocol.T_ELIMINATED), 1,
                             "%s: oczekiwano 1 eliminacji" % label)
            self.assertEqual(types.count(protocol.T_WINNER), 1,
                             "%s: oczekiwano 1 zwyciezcy" % label)

        # Zwyciezca to gracz, ktory nie zostal wyeliminowany.
        winner = next(protocol.decode_winner(v) for t, v in msgs_a
                      if t == protocol.T_WINNER)
        eliminated = next(protocol.decode_eliminated(v) for t, v in msgs_a
                          if t == protocol.T_ELIMINATED)
        self.assertIn(winner, (id_a, id_b))
        self.assertNotEqual(winner, eliminated)


class TestSinglePlayer(unittest.TestCase):
    def test_single_player_game_finishes(self):
        # Jeden gracz: start po uplywie krotkiej poczekalni; gra konczy sie
        # zwyciestwem (5 pustych) lub eliminacja -- zawsze GAME_OVER.
        srv = _start_server(with_lobby=True, lobby_timeout=1, max_players=1)
        self.addCleanup(srv.shutdown)
        port = srv.tcp_port

        s = _connect(port)
        self.addCleanup(s.close)
        s.sendall(protocol.encode_join("Solo"))
        self.assertEqual(_recv(s)[0], protocol.T_JOIN_ACK)

        msgs = []
        _drain_until_game_over(s, msgs)
        types = [m[0] for m in msgs]
        self.assertIn(protocol.T_START, types)
        self.assertIn(protocol.T_GAME_OVER, types)
        self.assertGreaterEqual(types.count(protocol.T_SHOT), 1)


if __name__ == "__main__":
    unittest.main()
