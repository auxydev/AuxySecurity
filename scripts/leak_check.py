"""Sizinti taramasi: ajanin 60 sn'lik yenileme isinin ayni kodunu N kez calistirir; handle / is parcacigi / bellek
buyumesini olcer. Buyume varsa o islev sizdiriyor demektir.

Kullanim: python scripts/leak_check.py [tekrar=300]
"""

import gc
import sys
import threading
import time

import psutil

from auxy.agent.icon import make_icon
from auxy.core import defender, winsec
from auxy.gui import viewmodel as vm

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
p = psutil.Process()


def sample():
    gc.collect()
    return p.num_handles(), threading.active_count(), p.memory_info().rss / 1e6


def cycle(use_threads: bool):
    """Ajan refresh() ile ayni is: WMI durum + kayit defteri + saglik + simge."""
    def work():
        st = defender.read_status()
        vm.evaluate(st)
        winsec.WinSecService().get_many(("fw_domain", "fw_private", "fw_public"))
        make_icon("ok")

    if use_threads:  # ajan donguyu ayri is parcaciginda calistirir
        t = threading.Thread(target=work)
        t.start()
        t.join()
    else:
        work()


for label, threaded in (("ayni is parcacigi", False), ("her seferinde yeni is parcacigi", True)):
    cycle(threaded)  # isinma (ilk import maliyeti)
    h0, t0, m0 = sample()
    t_start = time.perf_counter()
    for i in range(N):
        cycle(threaded)
    h1, t1, m1 = sample()
    print(f"{label:34} {N} tur, {time.perf_counter() - t_start:5.1f} sn | "
          f"handle {h0}->{h1} ({h1 - h0:+d}) | is parcacigi {t0}->{t1} ({t1 - t0:+d}) | RSS {m0:.1f}->{m1:.1f} MB ({m1 - m0:+.1f})")
