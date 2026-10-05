"""M2 oz-sinama: pencereyi acar, acilis suresini olcer, ekran goruntusu alir, kapanir.

Kullanim: python scripts/shot_gui.py [sayfa] [cikti.png] [light|dark]
"""

import sys
import time

import psutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _capture import save_window  # noqa: E402

from auxy.gui import app as gui

page = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"

t0 = time.perf_counter()
gui.ctk.set_appearance_mode(sys.argv[3] if len(sys.argv) > 3 else "light")
a = gui.App()
a.show(page)
a.update()
print(f"pencere hazir: {(time.perf_counter() - t0) * 1000:.0f} ms")


def finish():
    a.update_idletasks()
    save_window(a, Path(out))  # PrintWindow: ekrani kopyalamaz, baska pencere goruntuye girmez
    print(f"RSS: {psutil.Process().memory_info().rss / 1e6:.0f} MB, admin={a.admin}")
    print(f"ilk veri: {a.last_status is not None}")
    a.destroy()


a.after(2500, finish)  # worker sonucu icin bekle
a.mainloop()
