"""Ajan denetcisi: beklenmedik Python istisnasinda ajani surec ICINDE yeniden baslatir.

Neden surec ici: ayri bir denetci sureci ek bellek ve karmasiklik getirir. Python duzeyindeki cokmeler (istisna) buradan,
surec olumu / yerel cokme ise Gorev Zamanlayici'nin tekrarlanan tetikleyicisinden (IgnoreNew) kurtarilir
(bkz. core/autostart.py; gercek makinede dogrulandi: GOREV "hata durumunda yeniden baslat" ayari hata koduyla
TETIKLENMIYOR, bu yuzden o ayara guvenilmez).

Cok sik cokuyorsa (pencere icinde MAX_CRASHES) donguye girmemek icin vazgecer ve cikis kodu 1 doner.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from auxy.core.log import get_logger

MAX_CRASHES = 5  # bu kadar cokme ...
WINDOW_S = 600  # ... bu sure icinde olursa vazgec
BACKOFF_S = (2, 5, 15, 30, 60)  # her cokmeden sonra artan bekleme


def supervise(serve: Callable[[], int], sleep: Callable[[float], None] = time.sleep,
              now: Callable[[], float] = time.monotonic) -> int:
    log = get_logger()
    crashes: list[float] = []
    while True:
        try:
            return serve()
        except Exception as exc:  # noqa: BLE001 - beklenmedik her istisna
            t = now()
            crashes = [c for c in crashes if t - c < WINDOW_S] + [t]
            log.critical("AJAN COKTU (%d/%d, son %d sn)", len(crashes), MAX_CRASHES, WINDOW_S,
                         exc_info=(type(exc), exc, exc.__traceback__))
            if len(crashes) >= MAX_CRASHES:
                log.critical("Ajan cok sik coktu; yeniden baslatma durduruldu (Gorev Zamanlayici sonra yeniden dener)")
                return 1
            wait = BACKOFF_S[min(len(crashes) - 1, len(BACKOFF_S) - 1)]
            log.warning("Ajan %d sn sonra yeniden baslatilacak", wait)
            sleep(wait)
