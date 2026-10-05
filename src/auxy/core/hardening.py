"""Guvenlik sertlestirme yardimcilari: kurulum konumu riski, sonuc dosyasi guvenli yazimi.

KURULUM KONUMU RISKI: UAC ile (ya da yuksek yetkili gorevle) calisan kod, kullanicinin YAZABILDIGI bir dizinden
(.venv, src) gelirse, kullanici hesabinda calisan herhangi bir zararli program o dosyalari degistirip bir sonraki
UAC onayinda / oturum acilisinda YONETICI yetkisiyle calisabilir. Kurulu (Program Files, yalnizca yonetici yazar)
surum bu riski kapatir; gelistirme kurulumunda risk vardir ve acikca gosterilir.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

OK, WARN = "ok", "warn"
_REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


@dataclass(frozen=True)
class LocationRisk:
    level: str
    detail: str
    paths: tuple[str, ...] = ()

    @property
    def risky(self) -> bool:
        return self.level == WARN


def _safe_roots() -> list[Path]:
    roots = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "SystemRoot"):
        v = os.environ.get(var)
        if v:
            roots.append(Path(v).resolve())
    return roots


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def install_location_risk(code_dir: Path | None = None, python_dir: Path | None = None) -> LocationRisk:
    """Uygulama kodu ve Python yorumlayicisi yalnizca-yonetici yazilabilir bir konumda mi?"""
    import auxy

    code = Path(code_dir) if code_dir else Path(auxy.__file__).resolve().parent
    py = Path(python_dir) if python_dir else Path(sys.executable).resolve().parent
    roots = _safe_roots()
    risky = [str(p) for p in (code, py) if not any(_under(p, r) for r in roots)]
    if not risky:
        return LocationRisk(OK, "Uygulama ve Python, yalnızca yöneticinin yazabildiği bir konumda (Program Files).")
    return LocationRisk(
        WARN,
        "Uygulama kodu / Python kullanıcının yazabildiği bir dizinde: UAC ile ya da yüksek yetkili görevle çalışan "
        "kod bu dosyalardan gelir. Kullanıcı hesabında çalışan zararlı bir program bunları değiştirip "
        "yönetici yetkisi kazanabilir. Kurulu (Program Files) sürüm bu riski kapatır.",
        tuple(risky),
    )


def open_result_file(path: str):
    """Yukseltilmis sureclerin sonuc dosyasini GUVENLI acar (yazma icin, ikili modda).

    Sembolik baglanti / yeniden ayristirma noktasi / sabit baglanti (hardlink) ya da kontrol ile yazma arasinda
    degistirilmis dosya reddedilir: yonetici yetkisiyle rastgele bir dosyanin uzerine yazilmasi onlenir.
    Dosya yoksa ozel olarak (O_EXCL) olusturulur.
    """
    flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return os.fdopen(os.open(path, flags | os.O_CREAT | os.O_EXCL), "wb")
    if (stat.S_ISLNK(before.st_mode) or getattr(before, "st_file_attributes", 0) & _REPARSE
            or not stat.S_ISREG(before.st_mode)):
        raise ValueError("Sonuc dosyasi sade bir dosya degil (baglanti/yeniden ayristirma noktasi).")
    if before.st_nlink > 1:
        raise ValueError("Sonuc dosyasi sabit baglanti (hardlink) iceriyor.")
    fd = os.open(path, flags | os.O_TRUNC)
    after = os.fstat(fd)
    if (after.st_ino, after.st_dev) != (before.st_ino, before.st_dev):
        os.close(fd)
        raise ValueError("Sonuc dosyasi kontrol ile yazma arasinda degistirildi.")
    return os.fdopen(fd, "wb")
