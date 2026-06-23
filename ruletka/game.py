"""Logika gry: losowanie strzalu 1/6, liczba rund, warunki konca."""

import random

CHAMBERS = 6
PROB_FATAL = 1.0 / CHAMBERS
SINGLE_WIN_STREAK = 5            # solo: wygrana po tylu pustych


def is_fatal_shot(rng=None):
    """True gdy strzal smiertelny (prawdopodobienstwo 1/6)."""
    rng = rng or random
    return rng.randint(1, CHAMBERS) == 1


def rounds_for(num_players):
    """Liczba rund = gracze - 1 (dla 1 gracza: 1 runda)."""
    if num_players <= 1:
        return 1
    return num_players - 1
