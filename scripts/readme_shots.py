"""README icin TEMIZ ekran goruntuleri: yalitilmis veri dizini + ornek veri (kisisel yol/ad icermez).

Kullanim: python scripts/readme_shots.py docs/screenshots
Goruntu ekrani kopyalamaz (PrintWindow); uygulama penceresi gibi gorunmeyen goruntu KAYDEDILMEZ.
Gercek Defender/kasa/ayar verisine DOKUNMAZ; tehdit, gecmis ve kasa listeleri ornek verilerle doldurulur.
Pano, Guvenlik ve Ayarlar sayfalari gercek (kisisel olmayan) durumu gosterir.
"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
os.environ["AUXY_HOME"] = tempfile.mkdtemp(prefix="auxy-readme-")  # yalitilmis veri dizini

sys.path.insert(0, str(Path(__file__).parent))
from _capture import save_window  # noqa: E402

from auxy.core import actions, scan, threats  # noqa: E402
from auxy.core.actions import ActionResult  # noqa: E402
from auxy.core.vault import VaultItem  # noqa: E402
from auxy.gui import app as gui  # noqa: E402
from auxy.gui import vault_page  # noqa: E402

# ---- ornek veriler ----
threats.read_detections = lambda limit=200: [
    threats.Detection(1, "Virus:DOS/EICAR_Test_File", "Çok yüksek",
                      [r"C:\Users\ornek\Downloads\eicar-test.txt"], datetime(2026, 10, 4, 22, 54), True, False),
    threats.Detection(2, "Trojan:Win32/Ornek.A", "Yüksek", [r"C:\Users\ornek\Desktop\kurulum.exe"],
                      datetime(2026, 10, 3, 18, 12), False, True),
]
for i, (kind, path, st, th) in enumerate([
        (scan.QUICK, "", scan.COMPLETED, []),
        (scan.CUSTOM, r"C:\Users\ornek\Downloads", scan.COMPLETED, ["Virus:DOS/EICAR_Test_File"]),
        (scan.FULL, "", scan.CANCELLED, []),
        (scan.QUICK, "", scan.COMPLETED, [])]):
    scan.append_history(scan.ScanResult(kind, path, f"2026-10-0{i + 1}T09:{10 * i:02d}:00", 42.0 + i, st, 0, th))

VAULT_ITEMS = [
    VaultItem("a" * 32, r"C:\Users\ornek\Downloads\supheli-kurulum.exe", "supheli-kurulum.exe", "0" * 64,
              4_823_552, "2026-10-04T22:54:13", "Tehdit: Trojan:Win32/Ornek.A", 0.0),
    VaultItem("b" * 32, r"C:\Users\ornek\Desktop\eski-yukleyici.dll", "eski-yukleyici.dll", "1" * 64,
              312_320, "2026-10-03T18:12:40", "Elle eklendi", 0.0),
]


class FakeVault:
    def list(self):
        return VAULT_ITEMS


vault_page._vault = FakeVault()

# ag araclari: kisisel yol icermeyen ornek durum (gercek hizmetlere dokunulmaz)
from auxy.core import netservices  # noqa: E402

netservices.read_service = lambda name=netservices.GDPI_SERVICE: netservices.ServiceInfo(
    True, "running", "auto", r"C:\Program Files\AuxySecurity\tools\goodbyedpi\x86_64\goodbyedpi.exe", netservices.GDPI_DEFAULT_ARGS)
netservices.read_warp = lambda: netservices.WarpInfo(True, "Connected", "NetworkHealthy", "warp+doh", "MASQUE", True)
netservices.bundled_tools_dir = lambda: None
netservices.trusted_location = lambda *a, **k: True
DQ = [{"threat": "Virus:DOS/EICAR_Test_File", "path": r"C:\Users\ornek\Downloads\eicar-test.txt",
       "scheme": "file", "quarantined_at": "4.10.2026 19:54:32 (UTC)"}]
actions.defender_quarantine_op = lambda op, path="", to_dir="": ActionResult(True, "tamam", False, DQ)

mode = "light"
gui.ctk.set_appearance_mode(mode)
a = gui.App()
a.update()


def snap(name):
    a.update_idletasks()
    ok = save_window(a, out / f"{name}.png")  # PrintWindow: baska pencereler ustunu kapatsa bile yalnizca uygulama
    print("kaydedildi:" if ok else "ATLANDI:", name)


steps = [
    ("pano", "dashboard", None), ("guvenlik", "security", None), ("ag-guvenligi", "network", None), ("tarama", "scan", None),
    ("karantina-kasa", "quarantine", None), ("karantina-defender", "quarantine", "defender"),
    ("ayarlar", "settings", None), ("pano-koyu", "dashboard", "dark"),
]


def run(i=0):
    if i >= len(steps):
        a.destroy()
        return
    name, page, extra = steps[i]
    if extra == "dark":
        gui.ctk.set_appearance_mode("dark")
    a.show(page)
    if page == "quarantine":
        qp = a.pages["quarantine"]
        qp.mode_btn.set(vault_page.MODE_DEFENDER if extra == "defender" else vault_page.MODE_VAULT)
        qp._set_mode(qp.mode_btn.get())
    a.after(2800, lambda: (snap(name), a.after(200, lambda: run(i + 1))))


a.after(1500, run)
a.mainloop()
