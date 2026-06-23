"""Tryb demona: odlaczenie procesu w tle technika double-fork (tylko Unix)."""

import os
import sys


def daemonize():
    """Double fork + setsid; std fd -> /dev/null."""
    if not hasattr(os, "fork"):
        raise RuntimeError(
            "Tryb demona wymaga systemu uniksowego (os.fork niedostepny).")

    if os.fork() > 0:
        os._exit(0)            # rodzic konczy

    os.setsid()                # nowa sesja, brak terminala

    if os.fork() > 0:
        os._exit(0)            # konczy lidera sesji

    os.chdir("/")
    os.umask(0)

    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    if devnull > 2:
        os.close(devnull)
