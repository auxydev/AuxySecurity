"""Karantina sayfasinin iki gorunumunu (kasa / Defender karantinasi) sirayla fotograflar.

Kullanim: python scripts/shot_quarantine_modes.py <cikti_oneki>
Gercek Defender karantina islemi YAPILMAZ: liste sahte veriyle doldurulur.
"""

import sys

import sys as _sys
from pathlib import Path

_sys.path.insert(0, str(Path(__file__).parent))
from _capture import save_window  # noqa: E402

from auxy.core import actions
from auxy.core.actions import ActionResult
from auxy.gui import app as gui
from auxy.gui import vault_page

DATA = [
    {"threat": "Virus:DOS/EICAR_Test_File", "path": r"C:\Users\ornek\Desktop\eicar.txt", "scheme": "file",
     "quarantined_at": "4.10.2026 19:54:32 (UTC)"},
    {"threat": "Trojan:Win32/Sahte", "path": r"D:\Indirilenler\kotu.exe", "scheme": "file",
     "quarantined_at": "5.10.2026 09:00:00 (UTC)"},
]
actions.defender_quarantine_op = lambda op, path="", to_dir="": ActionResult(True, "tamam", False, DATA)

prefix = sys.argv[1]
gui.ctk.set_appearance_mode("light")
a = gui.App()
a.show("quarantine")
a.update()
page = a.pages["quarantine"]


def snap(name):
    a.update_idletasks()
    save_window(a, Path(f"{prefix}-{name}.png"))  # PrintWindow: ekrani kopyalamaz


def to_defender():
    page.mode_btn.set(vault_page.MODE_DEFENDER)
    page._set_mode(vault_page.MODE_DEFENDER)
    a.after(2500, lambda: (snap("defender"), a.after(100, back)))


def back():
    page.mode_btn.set(vault_page.MODE_VAULT)
    page._set_mode(vault_page.MODE_VAULT)
    a.after(1500, lambda: (snap("kasa-geri"), print(
        "kasa listesi gorunur (parent_frame):", page.list._parent_frame.winfo_ismapped(),
        "| defender gorunur:", page.defender_view.winfo_ismapped()), a.destroy()))


a.after(1500, to_defender)
a.mainloop()
