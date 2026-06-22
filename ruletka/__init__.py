"""Sieciowa gra ,,Rosyjska Ruletka'' (klient-serwer).

Pakiet zawiera moduly:
  * protocol -- binarny protokol TLV (kodowanie/dekodowanie, struct, big-endian),
  * game     -- logika gry (losowanie strzalow 1/6, liczba rund, warunki konca),
  * server   -- wspolbiezny serwer (threading + Lock), multicast, tryb demona,
  * client   -- klient (wyszukiwanie multicast / DNS, interfejs uzytkownika),
  * daemon   -- pomocniczy double-fork dla trybu demona (tylko systemy uniksowe).
"""

__all__ = ["protocol", "game", "server", "client", "daemon"]
__version__ = "1.0.0"
