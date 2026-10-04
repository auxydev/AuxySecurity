"""M5 uc-uca: GUI karantina akisi (kasaya al, listele, tehdit listesinden 'Kasaya al', geri yukle).

Kullanim: python scripts/gui_vault_e2e.py <calisma_klasoru> <cikti_prefix>
Onay pencereleri (messagebox) otomatik 'evet' yapilir.
"""

import hashlib
import sys
from datetime import datetime
from pathlib import Path

from PIL import ImageGrab

from auxy.core import threats
from auxy.gui import app as gui
from auxy.gui import vault_page

work = Path(sys.argv[1])
prefix = sys.argv[2]
work.mkdir(parents=True, exist_ok=True)
vault_page.messagebox.askyesno = lambda *a, **k: True

f1 = work / "supheli-1.exe"
f2 = work / "supheli-2.dll"
f1.write_bytes(b"MZ" + bytes(range(256)) * 400)
f2.write_bytes(b"MZ" + bytes(reversed(range(256))) * 900)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
h1, h2 = sha(f1), sha(f2)

# tehdit listesine bu dosyayi 'beklemede' gosteren sahte tespit (gercek Defender kaydina dokunmaz)
threats.read_detections = lambda limit=200: [
    threats.Detection(1, "Trojan:Test/Sahte", "Yüksek", [str(f2)], datetime.now(), False, True)]

gui.ctk.set_appearance_mode("light")
a = gui.App()
a.update()
log = []
steps = []


def shot(name):
    a.update_idletasks()
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(f"{prefix}-{name}.png")


def rows():
    return [w for w in a.pages["quarantine"].list.winfo_children() if isinstance(w, gui.ctk.CTkFrame)]


def find_button(frame, text):
    stack = [frame]
    while stack:
        w = stack.pop()
        if isinstance(w, gui.ctk.CTkButton) and w.cget("text") == text:
            return w
        stack.extend(w.winfo_children())


def step(fn, delay=2500):
    steps.append((fn, delay))


def run_next():
    if not steps:
        return finish()
    fn, delay = steps.pop(0)
    fn()
    a.after(delay, run_next)


q = a.pages["quarantine"]
step(lambda: (a.show("quarantine"), q.quarantine(str(f1), "E2E elle")))
step(lambda: (log.append(f"1) orijinal-1 silindi: {not f1.exists()}  satir sayisi: {len(rows())}  durum: {q.status.cget('text')}"),
              shot("kasa")), 500)
step(lambda: a.show("scan"), 1500)
step(lambda: (log.append(f"2) tehdit listesinde 'Kasaya al' var: {find_button(a.pages['scan'].threat_box, 'Kasaya al') is not None}"),
              shot("tehdit"), find_button(a.pages["scan"].threat_box, "Kasaya al").invoke()), 2500)
step(lambda: (a.show("quarantine"), None), 2000)
step(lambda: log.append(f"3) tehditten kasaya alindi, orijinal-2 silindi: {not f2.exists()}  satir: {len(rows())}"), 100)


def restore_all():
    for r in rows():
        find_button(r, "Geri yükle").invoke()
        return


step(restore_all, 2500)
step(restore_all, 2500)
step(lambda: log.append(
    f"4) geri yuklendi: f1 var={f1.exists()} ozet esit={f1.exists() and sha(f1) == h1}; "
    f"f2 var={f2.exists()} ozet esit={f2.exists() and sha(f2) == h2}; kalan satir={len(rows())}"), 100)


def finish():
    print("\n".join(log))
    a.destroy()


a.after(1500, run_next)
a.mainloop()
