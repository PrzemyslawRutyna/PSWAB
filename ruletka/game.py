"""Modul logiki gry -- czyste reguly rosyjskiej ruletki (bez sieci).

Wydzielenie logiki od warstwy sieciowej ulatwia testowanie jednostkowe
(funkcje sa deterministyczne przy podanym generatorze losowym).
"""

import random

# Prawdopodobienstwo zabojczego strzalu: 1 na 6 (jedna naboj w bebnie).
CHAMBERS = 6
PROB_FATAL = 1.0 / CHAMBERS

# Tryb jednoosobowy: wygrana po tylu kolejnych pustych strzalach.
SINGLE_WIN_STREAK = 5


def is_fatal_shot(rng=None):
    """Zwraca ``True`` jezeli strzal byl smiertelny (prawdopodobienstwo 1/6).

    Symuluje zakrecenie bebnem szesciostrzalowego rewolweru.
    """
    rng = rng or random
    return rng.randint(1, CHAMBERS) == 1


def rounds_for(num_players):
    """Liczba rund rozgrywki.

    Reguly: liczba rund = liczba graczy - 1.  Wyjatek: dla jednego gracza
    rozgrywana jest jedna runda (tryb solo).
    """
    if num_players <= 1:
        return 1
    return num_players - 1
