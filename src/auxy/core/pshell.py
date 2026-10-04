"""Tek PowerShell calistirici: UTF-8 cikti zorlanir, pencere acilmaz, ortam degiskeniyle guvenli arguman.

Windows PowerShell 5.1 stdout'u varsayilan olarak OEM/ANSI kod sayfasinda yazar; Python'un UTF-8 cozmesi
Turkce karakterleri (kural adlari, dislama yollari, hata metinleri) bozuyordu. Her komut once konsol cikti
kodlamasini UTF-8 yapar.
"""

from __future__ import annotations

import os
import subprocess

_UTF8_PREFIX = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8; "


def decode_output(data: bytes) -> str:
    """Yerel program (MpCmdRun gibi) ciktisi: once gecerli UTF-8, degilse konsolun OEM kod sayfasi.

    Boru (pipe) ciktisinda Turkce Windows genellikle cp857/cp1254 kullanir; UTF-8 gibi cozmek yol adlarini bozar."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        import ctypes

        cp = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        try:
            return data.decode(cp)
        except (LookupError, UnicodeDecodeError):
            return data.decode("utf-8", "replace")


def run(command: str, env: dict[str, str] | None = None, timeout: float = 60) -> tuple[int, str, str]:
    """(cikis kodu, stdout, stderr). Degerler komuta gomulmez: `env` ile `$env:ADI` olarak okunur."""
    full_env = {**os.environ, **(env or {})} if env else None
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _UTF8_PREFIX + command],
        capture_output=True, timeout=timeout, env=full_env, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return (proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))
