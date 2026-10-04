"""Arayuzu dondurmadan is calistirir. Yoklama yalnizca is varken calisir:
kisa islerde 50 ms, yalnizca uzun isler (tarama) bekliyorsa 500 ms.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

FAST_MS, SLOW_MS = 50, 500


class Worker:
    def __init__(self, schedule: Callable[[int, Callable[[], None]], object]):
        self._schedule = schedule  # tk.after
        self._results: queue.Queue = queue.Queue()
        self._pending = 0
        self._long_pending = 0
        self._polling = False

    def submit(self, fn: Callable, on_done: Callable[[object, Exception | None], None],
               long: bool = False) -> None:
        self._pending += 1
        self._long_pending += int(long)

        def run():
            try:
                self._results.put((on_done, fn(), None, long))
            except Exception as exc:  # arayuze iletilir
                self._results.put((on_done, None, exc, long))

        threading.Thread(target=run, daemon=True).start()
        if not self._polling:
            self._polling = True
            self._schedule(self._interval(), self._drain)

    def _interval(self) -> int:
        only_long = self._pending > 0 and self._pending == self._long_pending
        return SLOW_MS if only_long else FAST_MS

    def _drain(self) -> None:
        try:
            while True:
                on_done, result, exc, long = self._results.get_nowait()
                self._pending -= 1
                self._long_pending -= int(long)
                on_done(result, exc)
        except queue.Empty:
            pass
        if self._pending > 0:
            self._schedule(self._interval(), self._drain)
        else:
            self._polling = False
