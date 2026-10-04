"""Arayuzu dondurmadan is calistirir. Polling yalnizca is varken (50 ms) calisir."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable


class Worker:
    def __init__(self, schedule: Callable[[int, Callable[[], None]], object]):
        self._schedule = schedule  # tk.after
        self._results: queue.Queue = queue.Queue()
        self._pending = 0
        self._polling = False

    def submit(self, fn: Callable, on_done: Callable[[object, Exception | None], None]) -> None:
        self._pending += 1

        def run():
            try:
                self._results.put((on_done, fn(), None))
            except Exception as exc:  # arayuze iletilir
                self._results.put((on_done, None, exc))

        threading.Thread(target=run, daemon=True).start()
        if not self._polling:
            self._polling = True
            self._schedule(50, self._drain)

    def _drain(self) -> None:
        try:
            while True:
                on_done, result, exc = self._results.get_nowait()
                self._pending -= 1
                on_done(result, exc)
        except queue.Empty:
            pass
        if self._pending > 0:
            self._schedule(50, self._drain)
        else:
            self._polling = False
