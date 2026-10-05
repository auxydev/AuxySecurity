"""Yakalanmamis istisnalari GUNLUGE yazar.

Konsolsuz calisan `pythonw` sureclerinde (tray ajani, pencere) yakalanmamis bir istisna hicbir yerde gorunmez ve
bir is parcacigi SESSIZCE olur (M7'de izleme is parcacigi boyle olmustu). Bu kanca, ana is parcacigi, diger
is parcaciklari ve "unraisable" (finalizer vb.) istisnalarin hepsini auxy.log'a yazar.
"""

from __future__ import annotations

import sys
import threading

from auxy.core.log import get_logger

_installed: str | None = None


def install(component: str) -> None:
    """Idempotent: ayni surecte tekrar cagrilirsa bilesen adini gunceller."""
    global _installed
    _installed = component
    log = get_logger()

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        log.error("YAKALANMAMIS ISTISNA [%s] is parcacigi=%s", _installed, name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    def main_hook(exc_type, exc, tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            log.critical("YAKALANMAMIS ISTISNA [%s] ana is parcacigi", _installed, exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def unraisable_hook(unraisable):
        log.error("YAKALANMAMIS ISTISNA [%s] (finalizer vb.): %s", _installed, unraisable.err_msg or "",
                  exc_info=(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback))

    threading.excepthook = thread_hook
    sys.excepthook = main_hook
    sys.unraisablehook = unraisable_hook


def log_exception(where: str, exc: BaseException) -> None:
    """Elle: yakalanan ama kaybolmamasi gereken istisnalar icin."""
    get_logger().error("ISTISNA [%s] %s", where, where, exc_info=(type(exc), exc, exc.__traceback__))
