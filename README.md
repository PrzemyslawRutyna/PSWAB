# Sieciowa gra „Rosyjska Ruletka” (klient–serwer)

Programowanie Sieciowe — CB 2026 — prowadzący: **Janusz Gozdecki**

Projekt w języku **Python** (biblioteka `socket`). Serwer przeprowadza kolejne
rundy rosyjskiej ruletki i eliminuje graczy aż do wyłonienia zwycięzcy.
Aplikacja działa na **systemach uniksowych** (Linux/macOS).

## Autorzy i podział pracy

| Autor | Moduł |
|-------|-------|
| **Przemysław Rutyna** | moduł serwera: współbieżność, tryb demona, logowanie, koordynacja dostępu do wspólnych zasobów |
| **Piotr Skoczylas** | moduł klienta: wyszukiwanie usługi przez multicast, obsługa DNS, interfejs użytkownika |
| **Bartosz Toś** | moduł logiki gry oraz binarny protokół TLV (kodowanie/dekodowanie) |

## Struktura projektu

| Plik | Moduł z konspektu | Zawartość |
|------|-------------------|-----------|
| `ruletka/protocol.py` | Moduł protokołu (TLV) | binarne kodowanie/dekodowanie `struct`, big-endian |
| `ruletka/game.py`     | Moduł logiki gry      | losowanie 1/6, liczba rund, warunki końca |
| `ruletka/server.py`   | Moduł serwera         | wątki + `Lock`, multicast, tryb demona, syslog |
| `ruletka/client.py`   | Moduł klienta         | wyszukiwanie multicast / DNS, interfejs |
| `ruletka/daemon.py`   | (część serwera)       | demonizacja przez double-fork |
| `tests/`              | testy jednostkowe     | testy protokołu TLV i logiki gry (`unittest`) |

### Realizacja wymagań projektu

- **Serwer współbieżny** — każde połączenie obsługiwane w osobnym wątku
  (`threading`), wspólny stan gry chroniony muteksem `threading.Lock`.
- **Multicast + unicast** — serwer rozgłasza `ANNOUNCE` w grupie multicast
  (UDP) i odpowiada na `DISCOVER`; rozgrywka idzie po **unicast TCP**.
- **Binarny format TLV** — wszystkie ramki: `1 B typ + 2 B długość + N B wartość`
  (`struct.pack`, sieciowa kolejność bajtów / big-endian).
- **Tryb demona + logowanie** — `--daemon` (double fork), zdarzenia do
  **syslog** (`/dev/log`), opcjonalnie do pliku (`--log-file`).
- **DNS** — klient rozwiązuje nazwę hosta przez `socket.getaddrinfo()`
  (`AF_UNSPEC` — adresy A i AAAA, czyli IPv4 i IPv6).
- **Koordynacja zasobów** — lista graczy / numer rundy / wyniki pod `Lock`.
- **Obsługa IPv4 i IPv6 (dual-stack)** — serwer nasłuchuje jednocześnie na
  gniazdach IPv4 i IPv6 (`getaddrinfo` + `AI_PASSIVE`, osobne gniazda z
  `IPV6_V6ONLY`); klient łączy się po adresie/nazwie obu rodzin. Multicast
  działa w grupie IPv4 (`239.0.0.1`) lub IPv6 (`ff15::1`) — wybór przez `--group`.

Typy komunikatów TLV: `ANNOUNCE/DISCOVER`, `JOIN`, `JOIN_ACK`, `START`,
`SHOT`, `ELIMINATED`, `ROUND_END`, `WINNER`, `GAME_OVER`, `ERROR` (+ `INFO`).

## Wymagania

- Python 3.8+ (tylko biblioteka standardowa, brak zależności zewnętrznych).
- System uniksowy (`os.fork`, `syslog` — dla trybu demona).

## Pliki wymagane na maszynach uniksowych (minimum do pokazu)

Nie trzeba instalować żadnych pakietów — wystarczy **Python 3** i odpowiednie
pliki źródłowe. Aplikacja jest pakietem, więc pliki muszą leżeć w katalogu
`ruletka/`, a programy uruchamia się z katalogu **nadrzędnego** nad `ruletka/`
(poleceniem `python3 -m ruletka.serwer/klient`).

**Maszyna z serwerem** — potrzebne pliki:

```
ruletka/__init__.py      (może być pusty, ale musi istnieć)
ruletka/protocol.py      (protokół TLV + domyślne porty/grupa)
ruletka/game.py          (logika gry)
ruletka/daemon.py        (tryb demona)
ruletka/server.py        (serwer)
```

**Maszyna z klientem** — potrzebne pliki (klient NIE zależy od serwera):

```
ruletka/__init__.py
ruletka/protocol.py
ruletka/client.py
```

> Najprościej skopiować cały katalog `ruletka/` na każdą maszynę — wtedy działa
> i serwer, i klient. Katalog `tests/` oraz `README.md` **nie są** potrzebne do
> samego uruchomienia gry (tylko do testów i dokumentacji).

Szybka weryfikacja, że pakiet jest widoczny:

```bash
cd <katalog-z-folderem-ruletka>
python3 -c "import ruletka.protocol, ruletka.client; print('OK')"   # klient
python3 -c "import ruletka.server; print('OK')"                     # serwer
```

## Automatyzacja — `Makefile`

Wszystkie typowe czynności (testy, pokaz, wdrożenie na drugą maszynę) są
zautomatyzowane. `make` bez argumentów wypisuje listę poleceń:

```bash
make                 # lista dostępnych poleceń (help)
make test            # testy jednostkowe (unittest)
make check           # kontrola składni (py_compile) wszystkich modułów
make demo            # pokaz lokalny: serwer + 2 klienci (Ala, Bob) na 127.0.0.1
make run-server      # serwer pierwszoplanowy (logi na konsolę i do pliku)
make daemon          # serwer jako demon (tryb w tle + syslog)
make stop            # zatrzymanie serwera
make logs / follow   # podgląd logów (ostatnie / na bieżąco)
make discover        # wykrycie serwerów w sieci (multicast)
make run-client                  # klient z wyszukiwaniem multicast
make run-client HOST=<ip/nazwa>  # klient łączący się bezpośrednio (unicast/DNS)
make firewall        # podpowiedź poleceń otwarcia portów (ufw)
make clean           # sprzątanie plików tymczasowych
```

Parametry przekazuje się jako zmienne, np.
`make run-server PORT=50000 LOBBY=20`, `make run-client HOST=192.168.1.50 NICK=Ala`,
`make run-server GROUP=ff15::1` (multicast IPv6).

**Pokaz na dwóch maszynach uniksowych** (A = serwer, B = klient w tej samej LAN):

```bash
# (opcjonalnie) wgranie projektu na maszynę B:
make deploy HOST=user@192.168.1.60      # kopiuje ruletka/, tests/, Makefile, README

# Maszyna A (serwer):
make run-server                         # albo: make daemon

# Maszyna B (klient):
make run-client                         # wykrycie serwera przez multicast
make run-client HOST=192.168.1.50       # lub bezpośrednio (gdy multicast nie przechodzi)
```

## Testy jednostkowe

Testy używają wbudowanego modułu `unittest` (bez zależności zewnętrznych).
Uruchamiane z katalogu głównego projektu (lub `make test`):

```bash
# wszystkie testy
python3 -m unittest discover -s tests -v

# pojedynczy moduł
python3 -m unittest tests.test_protocol
python3 -m unittest tests.test_game
```

Zakres (40 testów):

- `test_protocol.py` — round-trip kodowania/dekodowania wszystkich komunikatów
  TLV, budowa nagłówka, odbiór strumieniowy z gniazda (składanie ramki z wielu
  `recv`), parsowanie datagramów UDP.
- `test_game.py` — reguły gry: liczba rund, prawdopodobieństwo 1/6 (test
  statystyczny), warunek wygranej w trybie solo.
- `test_server.py` — **testy integracyjne**: prawdziwy serwer na loopbacku,
  walidacja pseudonimu (pusty / za długi / zajęty / brak `JOIN`) oraz pełny
  przebieg gry dla dwóch graczy i dla jednego gracza (sprawdza współbieżność
  i sekwencję `START → SHOT → ELIMINATED → ROUND_END → WINNER → GAME_OVER`).

## Uruchomienie

### Serwer

```bash
# tryb pierwszoplanowy (logi także na konsolę)
python3 -m ruletka.server

# z parametrami
python3 -m ruletka.server --port 50000 --lobby-timeout 15 --name moj-serwer

# tryb demona (proces w tle, logi do syslog)
python3 -m ruletka.server --daemon --log-file /tmp/ruletka.log
```

Ważniejsze opcje serwera:

| Opcja | Znaczenie | Domyślnie |
|-------|-----------|-----------|
| `--host` | adres nasłuchu TCP (puste = wszystkie interfejsy IPv4 **i** IPv6) | `` (puste) |
| `--port` | port TCP rozgrywki | `50000` |
| `--group` / `--mcast-port` | grupa i port multicast (IPv4 `239.0.0.1` lub IPv6 `ff15::1`) | `239.0.0.1` / `50001` |
| `--lobby-timeout` | czas poczekalni od 1. gracza [s] | `15` |
| `--max-players` | start od razu po N graczach (0 = bez limitu) | `0` |
| `--shot-delay` | odstęp między strzałami [s] | `1.0` |
| `--daemon` | uruchom jako demon (Unix) | — |
| `--log-file` | dodatkowy plik logu | — |

> **Reguły gry:** liczba rund = liczba graczy − 1 (przy jednym graczu — 1 runda).
> W każdej rundzie serwer strzela do aktywnych graczy (1/6 szansy na trafienie),
> runda kończy się eliminacją jednego gracza (zostaje obserwatorem).
> Wielu graczy: wygrywa ostatni żywy. Jeden gracz: wygrana po 5 pustych strzałach.

### Klient

```bash
# wyszukanie serwera w sieci lokalnej (multicast) i dołączenie
python3 -m ruletka.client

# połączenie po nazwie/adresie (DNS) — z pominięciem multicast
python3 -m ruletka.client --host 192.168.1.50 --port 50000 --nick Janek

# tylko wykrycie serwerów w sieci
python3 -m ruletka.client --list
```

---

## Testowanie: host Windows 11 + WSL + maszyna wirtualna (bridged)

Scenariusz: **serwer w maszynie wirtualnej (Linux, karta sieciowa w trybie
mostkowanym/bridged)**, a **klienci w WSL** na hoście Windows 11 (oraz dodatkowo
w samej VM). Celem jest pokazanie multicastu i unicastu w prawdziwej sieci LAN.

### Problem do rozwiązania

Domyślny WSL2 pracuje za **NAT-em** (własna podsieć `172.x`), co blokuje
multicast i utrudnia łączność z VM w trybie bridged. Są dwa sposoby obejścia —
zalecany jest **tryb mirrored** dostępny w Windows 11.

### Krok 1 — WSL w trybie *mirrored* (Windows 11)

W trybie mirrored WSL współdzieli interfejsy sieciowe hosta (ten sam adres LAN),
dzięki czemu **multicast i łączność z VM działają jak na zwykłym hoście**.

Utwórz/uzupełnij plik `C:\Users\<TwojUser>\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
# opcjonalnie pomaga multicastowi między hostem a WSL:
# localhostForwarding=true
```

Następnie w PowerShell:

```powershell
wsl --shutdown
wsl
```

Sprawdź w WSL, że masz adres z sieci LAN (np. `192.168.x.x`), a nie `172.x`:

```bash
ip addr show
```

### Krok 2 — Maszyna wirtualna z kartą *bridged*

W VirtualBox/VMware ustaw kartę sieciową VM na **Bridged Adapter** (podpięta do
fizycznej karty hosta). Po starcie Linux w VM powinien dostać adres z tej samej
podsieci co host, np. `192.168.1.0/24`. Sprawdź `ip addr` w VM.

> Host (Windows + WSL mirrored), VM oraz ewentualne inne komputery **muszą być
> w tej samej podsieci** — wtedy grupa multicast `239.0.0.1` jest osiągalna.

### Krok 3 — Skopiuj projekt na maszyny uniksowe

Katalog `ruletka/` musi być dostępny w WSL i w VM. Przykładowo:

```bash
# w WSL projekt z dysku Windows jest pod /mnt/c
cd /mnt/c/Projects/szpont
python3 -c "import ruletka; print('ok')"

# kopiowanie na VM (scp) — gdy VM ma adres 192.168.1.50
scp -r /mnt/c/Projects/szpont/ruletka  user@192.168.1.50:~/szpont/ruletka
```

### Krok 4 — Uruchom serwer w VM

```bash
# w maszynie wirtualnej (Linux)
cd ~/szpont
python3 -m ruletka.server --lobby-timeout 20
```

Sprawdź, na jakim adresie nasłuchuje (`ip addr`), np. `192.168.1.50`.

### Krok 5 — Dołącz klientami

```bash
# klient w WSL (host Windows) — automatyczne wyszukanie przez multicast
cd /mnt/c/Projects/szpont
python3 -m ruletka.client --nick WSL_Gracz

# gdyby multicast nie przechodził — połączenie bezpośrednie (unicast + DNS)
python3 -m ruletka.client --host 192.168.1.50 --port 50000 --nick WSL_Gracz

# drugi klient np. w samej VM lub na innym komputerze w LAN
python3 -m ruletka.client --nick Gracz2
```

Gdy w poczekalni jest ≥1 gracz, po `--lobby-timeout` sekundach rusza rozgrywka.

### Zapora sieciowa (firewall)

- **Windows Defender Firewall** może blokować ruch przychodzący do WSL/host —
  jeśli klient nie wykrywa serwera, dopuść ruch UDP `50001` i TCP `50000`,
  albo na czas testów wyłącz zaporę dla sieci prywatnej.
- W maszynie wirtualnej (Linux) zezwól na porty, jeśli `ufw`/`firewalld` aktywne:
  ```bash
  sudo ufw allow 50000/tcp
  sudo ufw allow 50001/udp
  ```

### VirtualBox — sieć *host-only* i błąd „Network is unreachable”

Przy dwóch maszynach Linux (np. Kali) w sieci **host-only** multicast bywa
niedostępny i pojawiają się błędy:

```
OSError: [Errno 101] Network is unreachable        # wysyłka DISCOVER/ANNOUNCE
Nie mozna nasluchiwac DISCOVER: [Errno 19] No such device
```

**Przyczyna:** karta host-only zwykle **nie ma trasy domyślnej**, więc jądro nie
wie, którym interfejsem wysłać pakiet multicast. Sama rozgrywka (unicast TCP)
działa — problem dotyczy tylko warstwy wykrywania serwera (multicast).

Są trzy rozwiązania (od najprostszego):

1. **Połączenie bezpośrednie (zalecane do pokazu host-only).** Multicast jest
   tylko udogodnieniem — pomiń go i podaj adres serwera. Na serwerze sprawdź IP
   karty host-only (`ip -4 addr show`, np. `192.168.56.10`), a na kliencie:
   ```bash
   make run-client HOST=192.168.56.10
   #   lub:  python3 -m ruletka.client --host 192.168.56.10 --port 50000 --nick Ala
   ```

2. **Wskazanie interfejsu multicastu opcją `--iface`** (multicast nadal działa).
   Podaj adres IP karty host-only na obu maszynach:
   ```bash
   # serwer (IP jego karty host-only, np. 192.168.56.10):
   make run-server IFACE=192.168.56.10
   # klient (IP jego karty host-only, np. 192.168.56.11):
   make run-client IFACE=192.168.56.11
   #   discovery:  make discover IFACE=192.168.56.11
   ```

3. **Dodanie trasy multicast** na interfejsie host-only (bez zmian w kodzie):
   ```bash
   ip -4 addr show                         # ustal nazwę karty, np. eth0
   sudo ip route add 224.0.0.0/4 dev eth0  # na serwerze i kliencie
   ```

> Wskazówka: nazwę/adres interfejsu host-only podejrzysz przez `ip -4 addr show`
> (karta z adresem `192.168.56.x` to typowa sieć host-only VirtualBox).

### Alternatywa dla pełnego multicastu (dwie maszyny *bridged*)

Najpewniejsze środowisko dla **multicastu bez dodatkowej konfiguracji**: dwie
maszyny wirtualne Linux, obie z kartą **bridged** w tej samej podsieci. Serwer
w VM1, klienci w VM1 i VM2 — grupa `239.0.0.1` działa od razu. WSL2 w trybie NAT
(bez mirrored) oraz sieci host-only nadają się głównie do połączeń `--host`
(unicast) lub wymagają `--iface` / trasy multicast (patrz wyżej).

---

## Demonstracja wszystkich wymaganych funkcji

Poniższa lista pozwala pokazać **każde** wymaganie z konspektu. Najwygodniej
mieć otwarte: terminal serwera, 2–3 terminale klientów oraz (opcjonalnie)
terminal z `tcpdump`/`journalctl`.

| # | Wymaganie | Jak pokazać | Co zaobserwować |
|---|-----------|-------------|-----------------|
| 1 | **Serwer współbieżny (wątki)** | uruchom serwer i dołącz 3–4 klientów naraz | log „Nowe połączenie…”, każdy klient obsługiwany równolegle, gra toczy się dla wszystkich |
| 2 | **Koordynacja zasobów (`Lock`)** | dołącz kilku klientów jednocześnie; spróbuj zająć ten sam pseudonim | unikalne `id`, brak duplikatów nicków, spójny stan i kolejność rund |
| 3 | **Multicast (wykrywanie)** | `make discover` lub klient bez `--host` | klient znajduje serwer bez podawania IP (`ANNOUNCE`/`DISCOVER`) |
| 4 | **Unicast TCP (rozgrywka)** | dowolna rozgrywka | log „Nasłuch TCP (unicast)…”, połączenia po TCP |
| 5 | **Binarny protokół TLV** | `tcpdump` na portach gry (patrz niżej) | binarne ramki `typ+długość+wartość`, big-endian |
| 6 | **DNS (`getaddrinfo`)** | klient `--host <nazwa-hosta>` | komunikat „Rozwiązywanie nazwy…”, wypisane adresy IPv4/IPv6 |
| 7 | **Tryb demona + syslog** | `make daemon`, `ps`, `journalctl` | proces w tle bez terminala, zdarzenia w logach systemowych |
| 8 | **IPv4 i IPv6 (dual-stack)** | serwer nasłuch na obu, klient po IPv6 | dwa wpisy „Nasłuch TCP … [IPv4]/[IPv6]”, połączenie po `::1` |
| 9 | **Walidacja pseudonimu** | spróbuj nicka pustego / >12 znaków / zajętego | komunikat `Błąd:` i prośba o ponowienie |
| 10 | **Reguły gry** | rozgrywka wielu graczy oraz solo | eliminacje (1/6), obserwator, zwycięzca / 5 pustych w solo |

```bash
# 1+2) Współbieżność i synchronizacja — kilku klientów naraz (wątki + Lock)
python3 -m ruletka.server --lobby-timeout 20      # następnie 3-4 klientów

# 3) Multicast — wykrycie serwera bez znajomości IP
python3 -m ruletka.client --list                  # lub: make discover

# 6) DNS — łączenie po nazwie hosta (getaddrinfo, A + AAAA)
python3 -m ruletka.client --host nazwa-hosta-vm --port 50000 --nick X

# 7) Tryb demona + syslog — serwer w tle, logi systemowe
python3 -m ruletka.server --daemon
journalctl -t ruletka -f        # albo: tail -f /var/log/syslog | grep ruletka
ps aux | grep ruletka           # proces odłączony od terminala (brak TTY)

# 5) Binarny TLV — podgląd ramek w ruchu (Wireshark/tcpdump)
sudo tcpdump -i any -X 'port 50000 or port 50001'

# 9) Walidacja pseudonimu — w kliencie interaktywnym podaj pusty / 13-znakowy nick
python3 -m ruletka.client --host 127.0.0.1        # i wpisz np. "" albo "x"*13
```

### IPv6 (dual-stack)

```bash
# Serwer nasłuchuje domyślnie na IPv4 i IPv6 jednocześnie; w logu widać:
#   Nasłuch TCP (unicast) na ('0.0.0.0', 50000) [IPv4]
#   Nasłuch TCP (unicast) na ('::', 50000, 0, 0) [IPv6]

# Połączenie klientem po IPv6 (loopback):
python3 -m ruletka.client --host ::1 --port 50000 --nick Ala

# Wykrywanie przez multicast IPv6 (grupa ff15::1) — serwer i klient z tą grupą:
python3 -m ruletka.server --group ff15::1
python3 -m ruletka.client --group ff15::1 --nick Ala
```

> Uwaga: multicast IPv6 bywa zależny od interfejsu (scope link-local). Dla pokazu
> w LAN najpewniejszy jest multicast IPv4 (`239.0.0.1`); pełną obsługę IPv6 widać
> w rozgrywce unicast (`--host ::1` / adres globalny IPv6).

## Szybki test lokalny (loopback, jedna maszyna)

```bash
make demo            # automatyczny pokaz: serwer + Ala + Bob

# lub ręcznie:
# terminal 1
python3 -m ruletka.server --host 127.0.0.1 --lobby-timeout 5 --shot-delay 0.5
# terminal 2 i 3
python3 -m ruletka.client --host 127.0.0.1 --nick Ala
python3 -m ruletka.client --host 127.0.0.1 --nick Bob
```
