"""M2 uc-uca test (YONETICI gerekir): GUI anahtari ile pua'yi kapatip geri acar.

Kullanim: python scripts/gui_e2e.py <cikti.txt>
"""

import sys

from auxy.core import defender
from auxy.gui import app as gui

out = sys.argv[1]
log = []
a = gui.App()
a.update()
log.append(f"admin={a.admin}")


def pua():
    return defender.read_status().prefs["PUAProtection"]


original = pua()
log.append(f"baslangic pua={original}")
sw = a.dashboard.switches["pua"]
steps = iter(["off", "restore"])


def step():
    try:
        s = next(steps)
    except StopIteration:
        return finish()
    if s == "off":
        sw.deselect()
        a.toggle("pua", sw)
        a.after(4000, check_off)
    else:
        (sw.select if original == 1 else sw.deselect)()
        a.toggle("pua", sw)
        a.after(4000, check_restore)


def check_off():
    log.append(f"anahtar kapatildi -> pua={pua()} (beklenen 0); mesaj: {a.dashboard.message.cget('text')}")
    step()


def check_restore():
    log.append(f"geri alindi -> pua={pua()} (beklenen {original}); mesaj: {a.dashboard.message.cget('text')}")
    step()


def finish():
    ok = pua() == original
    log.append("SONUC: " + ("BASARILI, orijinal deger geri geldi" if ok else "HATA: orijinal deger donmedi!"))
    open(out, "w", encoding="utf-8").write("\n".join(log))
    a.destroy()


a.after(1500, step)
a.mainloop()
