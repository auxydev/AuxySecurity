"""M3 olcumu: calisan 'auxy agent' sureclerinin bellek (RSS) ve CPU kullanimini olcer.

Kullanim: python scripts/measure_agent.py [saniye=30] [--spawn]
  --spawn: ajani kendisi baslatir ve sonunda kapatir.
"""

import subprocess
import sys
import time

import psutil

seconds = int(next((a for a in sys.argv[1:] if a.isdigit()), 30))
spawned = None
if "--spawn" in sys.argv:
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    spawned = subprocess.Popen([exe, "-m", "auxy", "agent"])
    time.sleep(8)  # acilis + ilk durum okuma


def agent_procs():
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        cl = " ".join(p.info["cmdline"] or [])
        if "-m auxy agent" in cl:
            out.append(p)
    return out


procs = agent_procs()
if not procs:
    print("ajan sureci bulunamadi")
    sys.exit(1)

for p in procs:
    p.cpu_percent(None)
t0 = time.time()
time.sleep(seconds)
elapsed = time.time() - t0

total_rss = total_cpu = 0.0
for p in procs:
    try:
        rss = p.memory_info().rss / 1e6
        cpu = p.cpu_percent(None)  # son cagridan beri, tek cekirdek yuzdesi
        total_rss += rss
        total_cpu += cpu
        print(f"pid {p.pid:>6} {p.name():<14} RSS {rss:6.1f} MB  CPU {cpu:5.2f}%  "
              f"admin-benzeri: {p.username()}")
    except psutil.NoSuchProcess:
        pass
ncpu = psutil.cpu_count()
print(f"TOPLAM RSS {total_rss:.1f} MB | CPU {total_cpu:.2f}% (tek cekirdek) = "
      f"{total_cpu / ncpu:.3f}% (tum sistem, {ncpu} mantiksal cekirdek) | olcum {elapsed:.0f} sn")

if spawned:
    for p in agent_procs():
        p.terminate()
