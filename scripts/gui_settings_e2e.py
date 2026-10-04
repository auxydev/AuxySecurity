"""M7 uc-uca: Ayarlar sayfasi anahtarlari config.json'a yazar (yalitilmis AUXY_HOME, gercek ayara dokunmaz).

Kullanim: python scripts/gui_settings_e2e.py <gecici_klasor> <cikti.png>
"""

import os
import sys
import tempfile
from pathlib import Path

home = Path(sys.argv[1]).resolve()
home.mkdir(parents=True, exist_ok=True)
os.environ["AUXY_HOME"] = str(home)
os.environ["AUXY_INSTANCE"] = "_settingstest"

from PIL import ImageGrab  # noqa: E402

from auxy.core import config as cfgmod  # noqa: E402
from auxy.core import contextmenu  # noqa: E402
from auxy.gui import app as gui  # noqa: E402

gui.ctk.set_appearance_mode("light")
a = gui.App()
a.show("settings")
a.update()
page = a.pages["settings"]
log = [f"baslangic: {cfgmod.load()}"]


def step1():
    page.watch_sw.select()
    page.usb_sw.select()
    page.sched_sw.select()
    page.day_menu.set("Cuma")
    page.hour_menu.set("22:00")
    page.kind_menu.set("Tam tarama")
    page._save()
    c = cfgmod.load()
    log.append(f"kaydedildi: watch={c.watch_enabled} usb={c.usb_scan} sched={c.scheduled}")
    a.after(200, step2)


def step2():
    # sayfa yeniden yuklenince widget'lar dosyadan geri okunuyor mu?
    page.watch_sw.deselect()
    page.load_into_widgets()
    log.append(f"yeniden yuklendi: watch_sw={page.watch_sw.get()} gun={page.day_menu.get()} saat={page.hour_menu.get()} tur={page.kind_menu.get()}")
    page.ctx_sw.select()  # NOT: select() komutu tetiklemez; tiklamanin yaptigini elle cagiriyoruz
    page._toggle_context()  # gercek HKCU'ya yazar, hemen geri alinir
    log.append(f"sag tik (ac) kurulu: {contextmenu.is_installed()}")
    page.ctx_sw.deselect()
    page._toggle_context()
    log.append(f"sag tik (kapat) kurulu: {contextmenu.is_installed()}")
    a.update_idletasks()
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(sys.argv[2])
    print("\n".join(log))
    a.destroy()


a.after(1500, step1)
a.mainloop()
