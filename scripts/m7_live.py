"""M7 gercek makine testi (yonetici GEREKMEZ): olay aboneligi + klasor izleme + gercek tarama.

Kullanim: python scripts/m7_live.py <calisma_klasoru>
EICAR, bir test klasorune yazilir (Defender yakalar). Baska hicbir sistem ayarina dokunulmaz.
"""

import shutil
import sys
import time
from pathlib import Path

import psutil

from auxy.agent import watchers
from auxy.core import scan

work = Path(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
(work / "izle").mkdir(parents=True)
(work / "eicar").mkdir()
log = []


def say(m):
    log.append(m)
    print(m, flush=True)


# ---------- 1) Defender olay aboneligi ----------
events = []
listener = watchers.DefenderEventListener(events.append)
listener.start()
say("olay aboneligi basladi")
time.sleep(1)
e = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-" + "TEST-FILE!$H+H*"
t0 = time.time()
(work / "eicar" / "test-eicar.txt").write_text(e)
while time.time() - t0 < 25 and not any(ev.event_id == 1116 for ev in events):
    time.sleep(0.2)
for ev in events:
    say(f"  olay {ev.event_id}: tehdit={ev.threat!r} siddet={ev.severity!r} yol={ev.path!r} "
        f"({time.time() - t0:.1f} sn)")
say(f"1116 alindi: {any(ev.event_id == 1116 for ev in events)}")
time.sleep(2)
say(f"1117 alindi: {any(ev.event_id == 1117 for ev in events)}")
listener.stop()

# ---------- 2) klasor izleme + gercek tarama ----------
class Recording(scan.ScanManager):
    def run(self, scan_type, path=None, quiet=False):
        res = super().run(scan_type, path, quiet)
        say(f"  TARAMA: {path} -> {res.status}, tehdit={res.threats}, {res.seconds}s")
        return res


notes = []
w = watchers.FolderWatcher([str(work / "izle")], Recording(), notes.append)
w.start()
p = psutil.Process()
p.cpu_percent(None)
time.sleep(1)
say("klasor izleme basladi; temiz dosya yaziliyor")
(work / "izle" / "program.exe").write_bytes(b"MZ" + bytes(range(256)) * 50)
(work / "izle" / "yarim.crdownload").write_bytes(b"x" * 1000)
time.sleep(8)
say("indirme tamamlandi (yeniden adlandirma)")
(work / "izle" / "yarim.crdownload").rename(work / "izle" / "belge.pdf")
time.sleep(8)
say("30 dosyali yigin (zip acma benzeri)")
for i in range(30):
    (work / "izle" / f"f{i}.txt").write_text("a")
time.sleep(12)

# ---------- 3) bosta yuk (izleme acikken) ----------
p.cpu_percent(None)
time.sleep(15)
cpu = p.cpu_percent(None)
say(f"BOSTA (izleme + abonelik acik, 15 sn): CPU {cpu:.2f}% tek cekirdek, RSS {p.memory_info().rss / 1e6:.0f} MB")
w.stop()
say("bitti")
