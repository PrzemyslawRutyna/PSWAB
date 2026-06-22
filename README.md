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
- **Multicast + unicast** — serwer rozgłasza `ANNOUNCE` w grupie `239.0.0.1`
  (UDP) i odpowiada na `DISCOVER`; rozgrywka idzie po **unicast TCP**.
- **Binarny format TLV** — wszystkie ramki: `1 B typ + 2 B długość + N B wartość`
  (`struct.pack`, sieciowa kolejność bajtów / big-endian).
- **Tryb demona + logowanie** — `--daemon` (double fork), zdarzenia do
  **syslog** (`/dev/log`), opcjonalnie do pliku (`--log-file`).
- **DNS** — klient rozwiązuje nazwę hosta przez `socket.getaddrinfo()`.
- **Koordynacja zasobów** — lista graczy / numer rundy / wyniki pod `Lock`.

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

## Testy jednostkowe

Testy używają wbudowanego modułu `unittest` (bez zależności zewnętrznych).
Uruchamiane z katalogu głównego projektu:

```bash
# wszystkie testy
python3 -m unittest discover -s tests -v

# pojedynczy moduł
python3 -m unittest tests.test_protocol
python3 -m unittest tests.test_game
```

Zakres: round-trip kodowania/dekodowania wszystkich komunikatów TLV, budowa
nagłówka, odbiór strumieniowy z gniazda (składanie ramki z wielu `recv`),
parsowanie datagramów UDP oraz reguły gry (liczba rund, prawdopodobieństwo 1/6,
warunek wygranej w trybie solo).

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
| `--host` | adres nasłuchu TCP | `0.0.0.0` |
| `--port` | port TCP rozgrywki | `50000` |
| `--group` / `--mcast-port` | grupa i port multicast | `239.0.0.1` / `50001` |
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

### Alternatywa bez WSL mirrored (dwie maszyny wirtualne)

Najpewniejsze środowisko dla **multicastu**: dwie maszyny wirtualne Linux, obie
z kartą **bridged** w tej samej podsieci. Serwer w VM1, klienci w VM1 i VM2 —
multicast `239.0.0.1` działa bez dodatkowej konfiguracji. WSL2 w trybie NAT
(bez mirrored) nadaje się tylko do połączeń `--host` (unicast), nie do multicastu.

---

## Demonstracja poszczególnych wymagań

```bash
# 1) Współbieżność + synchronizacja — kilku klientów naraz (osobne wątki, Lock)
python3 -m ruletka.server --lobby-timeout 20
#   (uruchom 3-4 klientów z różnych terminali/maszyn)

# 2) Multicast — wykrycie serwera bez znajomości IP
python3 -m ruletka.client --list

# 3) DNS — łączenie po nazwie hosta (getaddrinfo)
python3 -m ruletka.client --host nazwa-hosta-vm --port 50000 --nick X

# 4) Tryb demona + syslog — serwer w tle, logi systemowe
python3 -m ruletka.server --daemon
journalctl -t ruletka -f        # albo: tail -f /var/log/syslog | grep ruletka
ps aux | grep ruletka           # proces odłączony od terminala

# 5) Binarny TLV — podgląd ramek w ruchu (Wireshark/tcpdump)
sudo tcpdump -i any -X port 50000 or port 50001
```

## Szybki test lokalny (loopback, jedna maszyna)

```bash
# terminal 1
python3 -m ruletka.server --host 127.0.0.1 --lobby-timeout 5 --shot-delay 0.5
# terminal 2 i 3
python3 -m ruletka.client --host 127.0.0.1 --nick Ala
python3 -m ruletka.client --host 127.0.0.1 --nick Bob
```
