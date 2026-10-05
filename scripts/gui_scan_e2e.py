"""M4 uc-uca: GUI tarama sayfasindan ozel tarama baslatir, sonucu ve ekran goruntusunu kaydeder.

Kullanim: python scripts/gui_scan_e2e.py <taranacak_klasor> <cikti.png>
"""

import sys

import sys as _sys
from pathlib import Path

_sys.path.insert(0, str(Path(__file__).parent))
from _capture import save_window  # noqa: E402

from auxy.core import scan
from auxy.gui import app as gui

folder, out = sys.argv[1], sys.argv[2]
gui.ctk.set_appearance_mode("light")
a = gui.App()
a.show("scan")
a.update()
page = a.pages["scan"]
log = []


def begin():
    page.start(scan.CUSTOM, folder)
    log.append(f"basladi, butonlar devre disi: {page.start_buttons[0].cget('state')}, "
               f"iptal: {page.cancel_btn.cget('state')}")
    poll()


def poll():
    if page.manager.running or page._started_at is not None:
        a.after(500, poll)
        return
    a.after(1500, finish)  # liste yenilemesi icin


def finish():
    a.update_idletasks()
    save_window(a, Path(out))  # PrintWindow: ekrani kopyalamaz
    log.append(f"durum: {page.status.cget('text')}")
    log.append(f"butonlar tekrar acik: {page.start_buttons[0].cget('state')}, "
               f"iptal: {page.cancel_btn.cget('state')}")
    print("\n".join(log))
    a.destroy()


a.after(1500, begin)
a.mainloop()
