"""M2 oz-sinama: pencereyi acar, acilis suresini olcer, ekran goruntusu alir, kapanir.

Kullanim: python scripts/shot_gui.py [sayfa] [cikti.png]
"""

import sys
import time

import psutil
from PIL import ImageGrab

from auxy.gui import app as gui

page = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"

t0 = time.perf_counter()
gui.ctk.set_appearance_mode("light")
a = gui.App()
a.show(page)
a.update()
print(f"pencere hazir: {(time.perf_counter() - t0) * 1000:.0f} ms")


def finish():
    a.update_idletasks()
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(out)
    print(f"RSS: {psutil.Process().memory_info().rss / 1e6:.0f} MB, admin={a.admin}")
    print(f"ilk veri: {a.last_status is not None}")
    a.destroy()


a.after(2500, finish)  # worker sonucu icin bekle
a.mainloop()
