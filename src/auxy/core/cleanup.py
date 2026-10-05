"""`auxy cleanup`: kaldirma temizligi. Yalnizca ACIKCA istenen seyleri yapar; varsayilan: kalici sistem girdilerini
(sag tik menusu, baslangic gorevi) kaldirir, VERIYE dokunmaz.

Kasada dosya varken veri silme REDDEDILIR (sifreli dosyalar anahtarsiz/kayitsiz geri alinamaz); once geri yukle/sil
ya da bilincli olarak `--force-vault` ver.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass

from auxy.core import actions, autostart, backup, contextmenu, paths, system


@dataclass(frozen=True)
class Step:
    name: str
    ok: bool
    detail: str


def vault_item_count() -> int:
    root = paths.home() / "vault"
    if not (root / "vault.db").exists():
        return 0
    import sqlite3
    from contextlib import closing

    try:
        with closing(sqlite3.connect(root / "vault.db")) as db:
            return db.execute("SELECT count(*) FROM items").fetchone()[0]
    except sqlite3.DatabaseError:
        return -1  # okunamiyor: dikkatli ol, silme


def run(remove_data: bool = False, revert_settings: bool = False, force_vault: bool = False,
        revert_fn: Callable[[], actions.ActionResult] | None = None) -> list[Step]:
    steps: list[Step] = []

    # 1) sag tik menusu (HKCU, yonetici gerekmez)
    if contextmenu.is_installed():
        contextmenu.remove()
        steps.append(Step("Sağ tık menüsü", True, "kaldırıldı"))
    else:
        steps.append(Step("Sağ tık menüsü", True, "zaten kurulu değil"))

    # 2) baslangic gorevi (UAC)
    if autostart.is_installed():
        res = actions.autostart_op("remove")
        steps.append(Step("Başlangıç görevi", res.ok, res.message))
    else:
        steps.append(Step("Başlangıç görevi", True, "zaten kurulu değil"))

    # 3) ayarlari orijinale dondur (isteğe bagli; UAC)
    if revert_settings:
        saved = backup.load()
        if not saved:
            steps.append(Step("Ayarlar", True, "geri alınacak değişiklik yok"))
        else:
            res = (revert_fn or actions.revert_all)()
            steps.append(Step("Ayarlar", res.ok, res.message))

    # 4) veri (isteğe bagli, korumali)
    if remove_data:
        home = paths.home()
        if system.is_agent_running():
            steps.append(Step("Veri", False, "tray ajanı çalışıyor: önce menüden Çıkış yap"))
        else:
            n = vault_item_count()
            if n != 0 and not force_vault:
                why = "okunamadı" if n < 0 else f"{n} dosya var"
                steps.append(Step("Veri", False, f"kasada dosya {why}: silmek bunları KALICI kaybettirir. "
                                                 "Önce geri yükle ya da bilerek --force-vault ver"))
            else:
                size = sum(p.stat().st_size for p in home.rglob("*") if p.is_file())
                shutil.rmtree(home, ignore_errors=True)
                gone = not home.exists() or not any(home.rglob("*"))
                steps.append(Step("Veri", gone, f"silindi ({size / 1024:.0f} KB): {home}" if gone else f"silinemedi: {home}"))
    else:
        steps.append(Step("Veri", True, f"korundu: {paths.home()} (silmek için --remove-data)"))

    if not all(s.ok for s in steps):
        raise_if_failed = [s for s in steps if not s.ok]
        steps.append(Step("Sonuç", False, f"{len(raise_if_failed)} adım tamamlanamadı"))
    return steps

