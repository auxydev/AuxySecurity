"""M6 uc-uca (yonetici GEREKMEZ): Guvenlik sayfasindan 'Store SmartScreen' anahtarini kapatip geri acar.

Kullanim: python scripts/gui_security_e2e.py <cikti.png>
"""

import sys

import sys as _sys
from pathlib import Path

_sys.path.insert(0, str(Path(__file__).parent))
from _capture import save_window  # noqa: E402

from auxy.core import winsec
from auxy.gui import app as gui
from auxy.gui import security_page

security_page.messagebox.askyesno = lambda *a, **k: True
gui.ctk.set_appearance_mode("light")
a = gui.App()
a.show("security")
a.update()
page = a.pages["security"]
svc = winsec.WinSecService()
log = [f"basla: {svc.get_all()['smartscreen_store']}"]
sw = page.sw["smartscreen_store"]


def off():
    sw.deselect()
    page._toggle("smartscreen_store")


def check_off():
    log.append(f"anahtar kapatildi -> kayit={svc.get_all()['smartscreen_store']} | mesaj: {page.message.cget('text')}")
    sw.select()
    page._toggle("smartscreen_store")


def check_on():
    log.append(f"anahtar acildi -> kayit={svc.get_all()['smartscreen_store']} | mesaj: {page.message.cget('text')}")
    svc.revert() if winsec.backup.load().get("ws:smartscreen_store", "yok") != "yok" else None
    a.update_idletasks()
    save_window(a, Path(sys.argv[1]))  # PrintWindow: ekrani kopyalamaz
    log.append(f"son: {svc.get_all()['smartscreen_store']} yedek={winsec.backup.load()}")
    print("\n".join(log))
    a.destroy()


a.after(2500, off)
a.after(5500, check_off)
a.after(8500, check_on)
a.mainloop()
