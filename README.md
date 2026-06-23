# Sieciowa gra „Rosyjska Ruletka” (klient–serwer)

Programowanie Sieciowe — CB 2026 — prowadzący: **Janusz Gozdecki**

Wieloosobowa, współbieżna gra sieciowa w architekturze **klient–serwer**, napisana
w języku **Python** (wyłącznie biblioteka standardowa `socket`). Serwer prowadzi
kolejne rundy rosyjskiej ruletki i eliminuje graczy aż do wyłonienia zwycięzcy.
Aplikacja działa na **systemach uniksowych** (Linux, macOS).

## Autorzy i podział pracy

Podział pracy zgodny z konspektem projektu:

| Autor | Zakres odpowiedzialności (moduł) |
|-------|----------------------------------|
| **Przemysław Rutyna** | Moduł serwera: współbieżność (wątki), tryb demona, logowanie do syslog, koordynacja dostępu do wspólnego stanu gry (`threading.Lock`). |
| **Piotr Skoczylas** | Moduł klienta: wyszukiwanie usługi przez multicast, obsługa DNS (`getaddrinfo`), interfejs użytkownika. |
| **Bartosz Toś** | Moduł logiki gry oraz binarny protokół TLV (kodowanie/dekodowanie). |

## Wymagania

- **Python 3.8+** — bez zależności zewnętrznych (tylko biblioteka standardowa).
- **System uniksowy** (Linux/macOS). Tryb demona korzysta z `os.fork` i `syslog`.

## Struktura projektu

| Plik | Moduł z konspektu | Zawartość |
|------|-------------------|-----------|
| `ruletka/protocol.py` | Moduł protokołu (TLV) | binarne kodowanie/dekodowanie ramek (`struct`, big-endian) |
| `ruletka/game.py`     | Moduł logiki gry      | losowanie 1/6, liczba rund, warunki końca |
| `ruletka/server.py`   | Moduł serwera         | wątki + `Lock`, multicast, tryb demona, syslog |
| `ruletka/client.py`   | Moduł klienta         | wyszukiwanie multicast / DNS, interfejs |
| `ruletka/daemon.py`   | (część serwera)       | demonizacja przez double-fork |
| `tests/`              | testy jednostkowe     | `unittest` — protokół, logika, integracja |

## Zrealizowane wymagania projektu

- **Serwer współbieżny** — każde połączenie obsługiwane w osobnym wątku
  (`threading`); wspólny stan gry chroniony muteksem `threading.Lock`.
- **Multicast + unicast** — serwer rozgłasza `ANNOUNCE` w grupie `239.0.0.1`
  (UDP) i odpowiada na `DISCOVER`; właściwa rozgrywka odbywa się po **unicast TCP**.
- **Binarny format TLV** — ramki `1 B typ + 2 B długość + N B wartość`
  (`struct.pack`, sieciowa kolejność bajtów / big-endian).
- **Tryb demona + logowanie** — `--daemon` (double fork), zdarzenia trafiają do
  **syslog**, opcjonalnie do pliku (`--log-file`).
- **DNS** — klient rozwiązuje nazwę hosta przez `socket.getaddrinfo()`.
- **Koordynacja zasobów** — lista graczy / numer rundy / wyniki pod `Lock`.
- **Obsługa IPv4 i IPv6** — serwer nasłuchuje na obu rodzinach adresów; klient
  łączy się po adresie/nazwie IPv4 lub IPv6.

## Szybki start

### Wariant A — jedna maszyna (test lokalny)

```bash
make demo        # automatycznie: serwer + 2 klienci (Ala, Bob) na 127.0.0.1
```

albo ręcznie, w osobnych terminalach:

```bash
# terminal 1 — serwer
make run-server LOBBY=8

# terminal 2 i 3 — klienci
make run-client HOST=127.0.0.1 NICK=Ala
make run-client HOST=127.0.0.1 NICK=Bob
```

### Wariant B — dwie maszyny w sieci LAN

Na maszynie z serwerem (przykładowy adres `192.168.56.101`):

```bash
make run-server
```

Na maszynie klienta:

```bash
# połączenie bezpośrednie (po adresie lub nazwie hosta — DNS):
make run-client HOST=192.168.56.101 NICK=Ala

# albo automatyczne wykrycie serwera w sieci (multicast):
make run-client NICK=Ala
```

> Gra startuje, gdy w poczekalni jest ≥1 gracz i upłynie `LOBBY` sekund
> (lub gdy dołączy `MAXP` graczy). Dwóch lub więcej graczy → wygrywa ostatni żywy;
> jeden gracz → wygrana po 5 kolejnych pustych strzałach.

## Polecenia (`Makefile`)

`make` bez argumentów wypisuje pełną listę. Najważniejsze:

| Polecenie | Działanie |
|-----------|-----------|
| `make test` | testy jednostkowe (`unittest`) |
| `make demo` | pokaz lokalny: serwer + 2 klienci |
| `make run-server` | serwer (pierwszoplanowo) |
| `make daemon` / `make stop` | serwer jako demon / zatrzymanie |
| `make logs` / `make follow` | podgląd logów (ostatnie / na bieżąco) |
| `make run-client [HOST=…]` | klient (z `HOST=` bezpośrednio, bez — multicast) |
| `make discover` | wykrycie serwerów w sieci (multicast) |
| `make clean` | sprzątanie plików tymczasowych |

Parametry przekazuje się jako zmienne, np.:

```bash
make run-server LOBBY=20            # dłuższa poczekalnia
make run-server MAXP=3              # start od razu po dołączeniu 3 graczy
make run-client HOST=192.168.56.101 NICK=Ala
```

Zmienne: `PORT` `GROUP` `MCAST_PORT` `IFACE` `NICK` `LOBBY` `MAXP` `SHOT_DELAY` `HOST` `LOG`.

## Opcje serwera

| Opcja | Znaczenie | Domyślnie |
|-------|-----------|-----------|
| `--host` | adres nasłuchu TCP (puste = wszystkie interfejsy) | `0.0.0.0` |
| `--port` | port TCP rozgrywki | `50000` |
| `--group` / `--mcast-port` | grupa i port multicast | `239.0.0.1` / `50001` |
| `--lobby-timeout` | czas poczekalni od 1. gracza [s] | `15` |
| `--max-players` | start od razu po N graczach (0 = bez limitu) | `0` |
| `--shot-delay` | odstęp między strzałami [s] | `1.0` |
| `--daemon` / `--log-file` | tryb demona / dodatkowy plik logu | — |

Klient: `--host` (adres/nazwa, pomija multicast), `--port`, `--nick`,
`--group`/`--mcast-port`, `--list` (tylko wykryj serwery).

## Reguły gry

- Liczba rund = liczba graczy − 1 (przy jednym graczu — 1 runda).
- W każdej rundzie serwer strzela do aktywnych graczy; szansa zabójczego
  strzału wynosi **1/6**. Runda kończy się eliminacją jednego gracza, który
  pozostaje połączony jako **obserwator**.
- Tryb wieloosobowy: wygrywa ostatni żywy gracz. Tryb jednoosobowy: wygrana po
  **5 kolejnych pustych** strzałach.
- Pseudonim: niepusty, maksymalnie 12 znaków, unikalny (walidacja po stronie serwera).

## Protokół (binarny TLV)

Każdy komunikat: `1 B typ` + `2 B długość` + `N B wartość` (big-endian, `struct`).
Typy: `ANNOUNCE`/`DISCOVER` (multicast), `JOIN`, `JOIN_ACK`, `START`, `SHOT`,
`ELIMINATED`, `ROUND_END`, `WINNER`, `GAME_OVER`, `ERROR`, `INFO`.

## Testy

```bash
make test                # albo: python3 -m unittest discover -s tests -v
```

Zakres (40 testów): kodowanie/dekodowanie wszystkich komunikatów TLV i odbiór
strumieniowy (`test_protocol.py`), reguły gry (`test_game.py`) oraz testy
integracyjne pełnej rozgrywki i walidacji pseudonimu na działającym serwerze
(`test_server.py`).

## Demonstracja wymagań

| Wymaganie | Jak pokazać | Co zaobserwować |
|-----------|-------------|-----------------|
| Współbieżność + `Lock` | serwer + 3–4 klientów naraz | log „Nowe połączenie…”, gra równolegle dla wszystkich |
| Multicast (wykrywanie) | `make discover` lub klient bez `HOST` | klient znajduje serwer bez podawania IP |
| Unicast TCP | dowolna rozgrywka | połączenia i rozgrywka po TCP |
| Binarny TLV | `sudo tcpdump -i any -X 'port 50000 or port 50001'` | binarne ramki `typ+długość+wartość` |
| DNS | `make run-client HOST=<nazwa-hosta>` | komunikat „Rozwiązywanie nazwy…” |
| Demon + syslog | `make daemon`; `ps aux \| grep ruletka`; `make follow` | proces bez terminala, zdarzenia w logach |
| Walidacja pseudonimu | klient bez `NICK`: podaj pusty / >12 znaków / zajęty | komunikat błędu i ponowienie |

> **Uwaga (multicast):** w sieciach bez trasy domyślnej (np. VirtualBox host-only)
> wykrywanie multicast może wymagać wskazania interfejsu:
> `make run-server IFACE=<ip-karty>` oraz `make run-client IFACE=<ip-karty>`.
> Połączenie bezpośrednie (`HOST=<adres>`) działa zawsze, niezależnie od multicastu.
