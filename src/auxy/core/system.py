"""Sistem yardimcilari: yonetici yetkisi kontrolu."""

import ctypes


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False
