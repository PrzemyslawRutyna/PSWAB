"""Tryb demona -- uruchomienie serwera jako procesu w tle (double fork).

Mechanizm dziala wylacznie na systemach uniksowych (wymaga ``os.fork`` oraz
``os.setsid``).  Po odlaczeniu od terminala standardowe deskryptory
przekierowywane sa do /dev/null; zdarzenia trafiaja do logow systemowych
(patrz ``server.setup_logging``).
"""

import os
import sys


def daemonize():
    """Przeksztalca biezacy proces w demona technika podwojnego fork().

    Kroki:
      1. fork -- rodzic konczy, dziecko trwa (nie jest liderem grupy),
      2. setsid -- nowa sesja, odlaczenie od terminala sterujacego,
      3. drugi fork -- gwarancja, ze proces nie przejmie terminala,
      4. chdir('/') oraz umask(0),
      5. przekierowanie stdin/stdout/stderr do /dev/null.
    """
    if not hasattr(os, "fork"):
        raise RuntimeError(
            "Tryb demona wymaga systemu uniksowego (os.fork niedostepny). "
            "Uruchom serwer na Linux/macOS (np. w WSL lub maszynie wirtualnej)."
        )

    # --- pierwszy fork ---
    if os.fork() > 0:
        os._exit(0)            # rodzic konczy dzialanie

    os.setsid()                # nowa sesja, brak terminala sterujacego

    # --- drugi fork ---
    if os.fork() > 0:
        os._exit(0)            # konczy lidera sesji

    os.chdir("/")
    os.umask(0)

    # Przekierowanie standardowych strumieni do /dev/null.
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    if devnull > 2:
        os.close(devnull)
