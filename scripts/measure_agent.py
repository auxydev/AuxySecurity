"""Ajan bellek (RSS / ozel bellek) ve CPU olcumu. Kendi baslattigi, YALITILMIS ajani olcer
(ayri AUXY_INSTANCE + gecici AUXY_HOME): calisan gercek ajana dokunmaz ve onu olcmez.

Kullanim: python scripts/measure_agent.py [saniye=30] [--idle-after=N]
"""

import os
import subprocess
import sys
import tempfile
import time

import psutil

seconds = int(next((a for a in sys.argv[1:] if a.isdigit()), 30))
env = os.environ.copy()
env["AUXY_INSTANCE"] = "_measure"
env["AUXY_HOME"] = tempfile.mkdtemp(prefix="auxy-measure-")
frozen_exe = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--exe=")), None)
if frozen_exe:  # paketlenmis AuxySecurity.exe ajanini olc
    cmd = [frozen_exe, "agent"]
else:
    cmd = [sys.executable.replace("python.exe", "pythonw.exe"), "-m", "auxy", "agent"]
proc = subprocess.Popen(cmd, env=env)
time.sleep(10)  # acilis + ilk durum okuma + (varsa) calisma kumesi kucultme

try:
    root = psutil.Process(proc.pid)
    tree = [root] + root.children(recursive=True)
except psutil.NoSuchProcess:
    print("ajan baslamadi")
    sys.exit(1)

for p in tree:
    p.cpu_percent(None)
time.sleep(seconds)

total_ws = total_priv = total_cpu = 0.0
real = None
for p in tree:
    try:
        mi = p.memory_full_info()
        ws, priv = mi.rss / 1e6, mi.private / 1e6 if hasattr(mi, "private") else mi.uss / 1e6
        cpu = p.cpu_percent(None)
        print(f"pid {p.pid:>6} {p.name():<14} calisma kumesi {ws:6.1f} MB | ozel bellek {priv:6.1f} MB | CPU {cpu:5.2f}%")
        total_ws += ws
        total_priv += priv
        total_cpu += cpu
        if "3.12" in p.name() or p.pid != proc.pid:
            real = (ws, priv)
    except psutil.NoSuchProcess:
        pass
ncpu = psutil.cpu_count()
print(f"TOPLAM (launcher dahil): calisma kumesi {total_ws:.1f} MB | ozel {total_priv:.1f} MB | "
      f"CPU {total_cpu:.3f}% tek cekirdek ({total_cpu / ncpu:.3f}% sistem) | {seconds} sn")
if real:
    print(f"ASIL SUREC (launcher haric): calisma kumesi {real[0]:.1f} MB | ozel bellek {real[1]:.1f} MB")

for p in reversed(tree):
    try:
        p.terminate()
    except psutil.NoSuchProcess:
        pass
