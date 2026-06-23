"""Testy protokolu TLV: round-trip, naglowek, odbior strumieniowy, datagram."""

import struct
import unittest

from ruletka import protocol as p


class FakeSocket:
    """Atrapa gniazda zwracajaca dane w porcjach o rozmiarze chunk."""

    def __init__(self, data, chunk=4096):
        self.data = bytes(data)
        self.pos = 0
        self.chunk = chunk

    def recv(self, n):
        if self.pos >= len(self.data):
            return b""
        end = min(self.pos + min(n, self.chunk), len(self.data))
        out = self.data[self.pos:end]
        self.pos = end
        return out


class TestHeader(unittest.TestCase):
    def test_header_layout(self):
        self.assertEqual(p.HEADER_SIZE, 3)
        frame = p.encode(p.T_JOIN, b"abc")
        self.assertEqual(frame[0], p.T_JOIN)
        self.assertEqual(struct.unpack("!H", frame[1:3])[0], 3)
        self.assertEqual(frame[3:], b"abc")

    def test_empty_value(self):
        frame = p.encode(p.T_GAME_OVER)
        self.assertEqual(len(frame), p.HEADER_SIZE)
        self.assertEqual(struct.unpack("!H", frame[1:3])[0], 0)

    def test_value_too_long_raises(self):
        with self.assertRaises(ValueError):
            p.encode(p.T_INFO, b"x" * (p.MAX_VALUE + 1))


class TestRoundTrip(unittest.TestCase):
    def _decode(self, frame, expected_type):
        parsed = p.parse_datagram(frame)
        self.assertIsNotNone(parsed)
        mtype, value = parsed
        self.assertEqual(mtype, expected_type)
        return value

    def test_announce(self):
        v = self._decode(p.encode_announce(50000, "serwer-1"), p.T_ANNOUNCE)
        self.assertEqual(p.decode_announce(v), (50000, "serwer-1"))

    def test_discover(self):
        self._decode(p.encode_discover(), p.T_DISCOVER)

    def test_join(self):
        v = self._decode(p.encode_join("Ala"), p.T_JOIN)
        self.assertEqual(p.decode_join(v), "Ala")

    def test_join_unicode(self):
        v = self._decode(p.encode_join("Żółć"), p.T_JOIN)
        self.assertEqual(p.decode_join(v), "Żółć")

    def test_join_ack(self):
        v = self._decode(p.encode_join_ack(7, "Bob"), p.T_JOIN_ACK)
        self.assertEqual(p.decode_join_ack(v), (7, "Bob"))

    def test_start_roster(self):
        roster = [(1, "Ala"), (2, "Bob"), (3, "Żółw")]
        v = self._decode(p.encode_start(2, roster), p.T_START)
        num_rounds, decoded = p.decode_start(v)
        self.assertEqual(num_rounds, 2)
        self.assertEqual(decoded, roster)

    def test_start_empty_roster(self):
        v = self._decode(p.encode_start(1, []), p.T_START)
        self.assertEqual(p.decode_start(v), (1, []))

    def test_shot(self):
        v = self._decode(p.encode_shot(3, 5, p.RESULT_FATAL), p.T_SHOT)
        self.assertEqual(p.decode_shot(v), (3, 5, p.RESULT_FATAL))

    def test_eliminated(self):
        v = self._decode(p.encode_eliminated(9), p.T_ELIMINATED)
        self.assertEqual(p.decode_eliminated(v), 9)

    def test_round_end(self):
        v = self._decode(p.encode_round_end(4, 2), p.T_ROUND_END)
        self.assertEqual(p.decode_round_end(v), (4, 2))

    def test_winner(self):
        v = self._decode(p.encode_winner(1), p.T_WINNER)
        self.assertEqual(p.decode_winner(v), 1)

    def test_error(self):
        v = self._decode(p.encode_error(p.ERR_NICK, "zly nick"), p.T_ERROR)
        self.assertEqual(p.decode_error(v), (p.ERR_NICK, "zly nick"))

    def test_info(self):
        v = self._decode(p.encode_info("witaj"), p.T_INFO)
        self.assertEqual(p.decode_info(v), "witaj")


class TestRecvMessage(unittest.TestCase):
    def test_single_message(self):
        frame = p.encode_shot(1, 2, p.RESULT_EMPTY)
        sock = FakeSocket(frame)
        mtype, value = p.recv_message(sock)
        self.assertEqual(mtype, p.T_SHOT)
        self.assertEqual(p.decode_shot(value), (1, 2, p.RESULT_EMPTY))

    def test_byte_by_byte(self):
        frame = p.encode_join_ack(3, "Krzys")
        sock = FakeSocket(frame, chunk=1)
        mtype, value = p.recv_message(sock)
        self.assertEqual(mtype, p.T_JOIN_ACK)
        self.assertEqual(p.decode_join_ack(value), (3, "Krzys"))

    def test_two_messages_in_stream(self):
        stream = p.encode_join("Ala") + p.encode_winner(1)
        sock = FakeSocket(stream, chunk=3)
        m1 = p.recv_message(sock)
        m2 = p.recv_message(sock)
        self.assertEqual(m1[0], p.T_JOIN)
        self.assertEqual(p.decode_join(m1[1]), "Ala")
        self.assertEqual(m2[0], p.T_WINNER)
        self.assertEqual(p.decode_winner(m2[1]), 1)

    def test_closed_connection_returns_none(self):
        self.assertIsNone(p.recv_message(FakeSocket(b"")))

    def test_truncated_header_returns_none(self):
        self.assertIsNone(p.recv_message(FakeSocket(b"\x10\x00")))

    def test_truncated_value_returns_none(self):
        frame = p.encode(p.T_INFO, b"hello")[:-2]
        self.assertIsNone(p.recv_message(FakeSocket(frame)))


class TestParseDatagram(unittest.TestCase):
    def test_too_short(self):
        self.assertIsNone(p.parse_datagram(b"\x01"))

    def test_truncated_value(self):
        frame = p.encode(p.T_INFO, b"hello")[:-1]
        self.assertIsNone(p.parse_datagram(frame))

    def test_ignores_trailing_bytes(self):
        frame = p.encode_eliminated(5) + b"GARBAGE"
        mtype, value = p.parse_datagram(frame)
        self.assertEqual(mtype, p.T_ELIMINATED)
        self.assertEqual(p.decode_eliminated(value), 5)


if __name__ == "__main__":
    unittest.main()
