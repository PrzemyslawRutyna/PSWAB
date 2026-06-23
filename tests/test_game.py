"""Testy logiki gry: liczba rund i strzal 1/6."""

import random
import unittest

from ruletka import game


class FakeRng:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def randint(self, a, b):
        self.calls.append((a, b))
        return self.value


class TestRoundsFor(unittest.TestCase):
    def test_single_player(self):
        self.assertEqual(game.rounds_for(1), 1)

    def test_zero_or_negative(self):
        self.assertEqual(game.rounds_for(0), 1)

    def test_multiplayer(self):
        self.assertEqual(game.rounds_for(2), 1)
        self.assertEqual(game.rounds_for(3), 2)
        self.assertEqual(game.rounds_for(6), 5)
        self.assertEqual(game.rounds_for(10), 9)


class TestIsFatalShot(unittest.TestCase):
    def test_fatal_when_one(self):
        self.assertTrue(game.is_fatal_shot(FakeRng(1)))

    def test_empty_for_two_to_six(self):
        for v in (2, 3, 4, 5, 6):
            self.assertFalse(game.is_fatal_shot(FakeRng(v)))

    def test_uses_one_to_six_range(self):
        rng = FakeRng(4)
        game.is_fatal_shot(rng)
        self.assertEqual(rng.calls, [(1, game.CHAMBERS)])
        self.assertEqual(game.CHAMBERS, 6)

    def test_probability_is_one_sixth(self):
        rng = random.Random(12345)
        n = 60000
        fatal = sum(1 for _ in range(n) if game.is_fatal_shot(rng))
        self.assertAlmostEqual(fatal / n, game.PROB_FATAL, delta=0.01)


class TestConstants(unittest.TestCase):
    def test_single_win_streak(self):
        self.assertEqual(game.SINGLE_WIN_STREAK, 5)

    def test_prob_fatal_value(self):
        self.assertAlmostEqual(game.PROB_FATAL, 1.0 / 6.0)


if __name__ == "__main__":
    unittest.main()
