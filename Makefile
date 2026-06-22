# Makefile - sieciowa gra "Rosyjska Ruletka" (klient-serwer)
# Automatyzacja testow oraz pokazu na dwoch maszynach uniksowych.
#
# Szybki start (dwie maszyny w tej samej sieci LAN):
#   Maszyna A (serwer):  make run-server
#   Maszyna B (klient):  make run-client                # wykrycie przez multicast
#                        make run-client HOST=<ip-A>    # lub bezposrednio (DNS/IP)
#   Wgranie kodu zdalnie: make deploy HOST=user@<ip-B>
#
# Pokaz lokalny (jedna maszyna):  make demo

PYTHON      ?= python3
BIND        ?= 0.0.0.0
HOST        ?=
PORT        ?= 50000
GROUP       ?= 239.0.0.1
MCAST_PORT  ?= 50001
NICK        ?= gracz
LOBBY       ?= 15
SHOT_DELAY  ?= 1.0
LOG         ?= /tmp/ruletka.log
REMOTE_DIR  ?= ~/ruletka-game

.DEFAULT_GOAL := help

.PHONY: help test test-v check run-server daemon stop logs follow \
        discover run-client demo demo-local deploy firewall clean

help: ## Pokaz dostepne polecenia
	@echo "Rosyjska Ruletka - polecenia (make <cel>):"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'
	@echo ""
	@echo "Zmienne: PYTHON PORT GROUP MCAST_PORT NICK LOBBY SHOT_DELAY HOST LOG REMOTE_DIR"
	@echo "Przyklad: make run-client HOST=192.168.1.50 NICK=Ala"

# --- testy / kontrola jakosci ---------------------------------------------
test: ## Uruchom testy jednostkowe
	$(PYTHON) -m unittest discover -s tests

test-v: ## Testy jednostkowe (verbose)
	$(PYTHON) -m unittest discover -s tests -v

check: ## Kompilacja kontrolna wszystkich modulow
	$(PYTHON) -m py_compile ruletka/*.py tests/*.py
	@echo "OK - skladnia poprawna"

# --- serwer ----------------------------------------------------------------
run-server: ## Uruchom serwer (pierwszoplanowo, logi tez na konsole)
	$(PYTHON) -m ruletka.server --host $(BIND) --port $(PORT) --group $(GROUP) \
		--mcast-port $(MCAST_PORT) --lobby-timeout $(LOBBY) \
		--shot-delay $(SHOT_DELAY) --log-file $(LOG)

daemon: ## Uruchom serwer jako demon (tryb w tle, syslog)
	$(PYTHON) -m ruletka.server --daemon --host $(BIND) --port $(PORT) \
		--group $(GROUP) --mcast-port $(MCAST_PORT) --lobby-timeout $(LOBBY) \
		--shot-delay $(SHOT_DELAY) --log-file $(LOG)
	@echo "Demon uruchomiony. Podglad: make logs / make follow ; status: ps aux | grep ruletka"

stop: ## Zatrzymaj dzialajacy serwer
	-@pkill -f "ruletka.server" && echo "Zatrzymano serwer." || echo "Brak dzialajacego serwera."

logs: ## Pokaz ostatnie wpisy logu
	@echo "=== $(LOG) ==="
	@tail -n 40 $(LOG) 2>/dev/null || echo "(brak pliku $(LOG) - uruchom serwer)"

follow: ## Sledz log na biezaco (Ctrl-C aby przerwac)
	@tail -n 20 -f $(LOG)

# --- klient ----------------------------------------------------------------
discover: ## Wykryj serwery w sieci (multicast)
	$(PYTHON) -m ruletka.client --list --group $(GROUP) --mcast-port $(MCAST_PORT)

run-client: ## Dolacz jako klient (HOST=ip/nazwa aby pominac multicast)
ifeq ($(strip $(HOST)),)
	$(PYTHON) -m ruletka.client --nick $(NICK) --group $(GROUP) --mcast-port $(MCAST_PORT)
else
	$(PYTHON) -m ruletka.client --host $(HOST) --port $(PORT) --nick $(NICK)
endif

# --- pokaz lokalny (jedna maszyna, loopback) -------------------------------
demo: demo-local ## Alias dla demo-local

demo-local: ## Lokalny pokaz: serwer + 2 klienci (Ala, Bob) na 127.0.0.1
	@echo ">> Start serwera (loopback, lobby 4s, szybkie strzaly)..."
	@$(PYTHON) -m ruletka.server --host 127.0.0.1 --port $(PORT) \
		--lobby-timeout 4 --shot-delay 0.3 --log-file $(LOG) & echo $$! > .server.pid
	@sleep 1.5
	@echo ">> Dolaczaja gracze Ala i Bob..."
	@( $(PYTHON) -m ruletka.client --host 127.0.0.1 --port $(PORT) --nick Ala & \
	   $(PYTHON) -m ruletka.client --host 127.0.0.1 --port $(PORT) --nick Bob & \
	   wait )
	-@kill $$(cat .server.pid) 2>/dev/null || true
	@rm -f .server.pid
	@echo ">> Koniec pokazu. Log serwera: $(LOG)"

# --- wdrozenie na druga maszyne --------------------------------------------
deploy: ## Skopiuj projekt na zdalna maszyne (make deploy HOST=user@ip)
	@test -n "$(HOST)" || { echo "Uzycie: make deploy HOST=user@adres [REMOTE_DIR=~/kat]"; exit 1; }
	ssh $(HOST) "mkdir -p $(REMOTE_DIR)"
	scp -r ruletka tests Makefile README.md $(HOST):$(REMOTE_DIR)/
	@echo "Gotowe. Na zdalnej maszynie: cd $(REMOTE_DIR) && make run-server (lub make run-client)"

firewall: ## Pokaz polecenia otwarcia portow (ufw)
	@echo "Na maszynie z serwerem otworz porty:"
	@echo "  sudo ufw allow $(PORT)/tcp        # rozgrywka (unicast TCP)"
	@echo "  sudo ufw allow $(MCAST_PORT)/udp  # wyszukiwanie uslugi (multicast)"

clean: ## Usun pliki tymczasowe (__pycache__, pid)
	rm -rf ruletka/__pycache__ tests/__pycache__ .server.pid
	@echo "Wyczyszczono."
