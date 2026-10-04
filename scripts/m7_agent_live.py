"""M7 ajan uc-uca testi (yonetici GEREKMEZ). Calisan gercek ajana ve gercek ayarlara DOKUNMAZ:
ayri veri dizini (AUXY_HOME) ve ayri ornek adi (AUXY_INSTANCE) kullanir.

Kullanim: python scripts/m7_agent_live.py <calisma_klasoru>
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

work = Path(sys.argv[1]).resolve() / time.strftime("%H%M%S")  # her calistirmada benzersiz (onceki ajan dosyayi tutuyor olabilir)
home, watch = work / "home", work / "indirilenler"
home.mkdir(parents=True)
watch.mkdir()
os.environ["AUXY_HOME"] = str(home)
os.environ["AUXY_INSTANCE"] = "_m7test"

from auxy.core import config as cfgmod  # noqa: E402  (ortam degiskenlerinden SONRA)
from auxy.core import system  # noqa: E402


def log_text():
    p = home / "logs" / "auxy.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def say(m):
    print(m, flush=True)


cfgmod.save(cfgmod.Config(watch_enabled=True, watch_folders=[str(watch)], event_notifications=True))
exe = sys.executable.replace("python.exe", "pythonw.exe")
proc = subprocess.Popen([exe, "-m", "auxy", "agent"], env=os.environ.copy())
time.sleep(9)
say(f"ajan calisiyor (mutex gorunuyor): {system.is_agent_running()}")
say(f"izleme basladi (ilk ayar): {'Klasor izleme basladi' in log_text()}")
say(f"olay aboneligi basladi: {'Defender olay aboneligi basladi' in log_text()}")

(watch / "program.exe").write_bytes(b"MZ" + bytes(range(256)) * 40)
time.sleep(7)
say(f"yeni dosya tarandi: {'program.exe' in log_text() and 'TARAMA bitti' in log_text()}")

# --- ayar degisikligi: izlemeyi kapat (GUI'nin yaptigi gibi kaydet + sinyal gonder)
t0 = time.time()
c = cfgmod.load()
c.watch_enabled = False
cfgmod.save(c)
system.signal_config_changed()
while time.time() - t0 < 10 and "Klasor izleme durdu" not in log_text():
    time.sleep(0.1)
say(f"ayar kapatilinca izleme durdu: {'Klasor izleme durdu' in log_text()} ({time.time() - t0:.2f} sn sonra)")
n_before = log_text().count("TARAMA basladi")
(watch / "program2.exe").write_bytes(b"MZ" + b"z" * 500)
time.sleep(6)
say(f"kapaliyken yeni dosya TARANMADI: {log_text().count('TARAMA basladi') == n_before}")

# --- tekrar ac
c.watch_enabled = True
cfgmod.save(c)
system.signal_config_changed()
time.sleep(3)
(watch / "program3.exe").write_bytes(b"MZ" + b"y" * 500)
time.sleep(7)
say(f"tekrar acilinca yeni dosya tarandi: {'program3.exe' in log_text()}")

# --- bosta yuk (tum agac)
procs = [psutil.Process(proc.pid)] + psutil.Process(proc.pid).children(recursive=True)
for p in procs:
    p.cpu_percent(None)
time.sleep(30)
rss = cpu = 0.0
for p in procs:
    try:
        rss += p.memory_info().rss / 1e6
        cpu += p.cpu_percent(None)
        say(f"  pid {p.pid} {p.name():<14} RSS {p.memory_info().rss / 1e6:5.1f} MB  CPU {p.cpu_percent(None):.2f}%")
    except psutil.NoSuchProcess:
        pass
say(f"TOPLAM (izleme+abonelik acik, 30 sn): RSS {rss:.1f} MB | CPU {cpu:.3f}% (tek cekirdek)")

for p in reversed(procs):
    try:
        p.terminate()
    except psutil.NoSuchProcess:
        pass
say("ajan kapatildi")
