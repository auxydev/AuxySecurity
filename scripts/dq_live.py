"""Defender karantinasi gercek testi (uygulamanin UAC akisiyla; 3 UAC penceresi).

Kullanim: python scripts/dq_live.py <geri_yukleme_klasoru>
Yapilanlar: listele -> bir EICAR ogesini ALTERNATIF klasore geri yukle -> Remove-MpThreat.
CEVRIMDISI TARAMA CALISTIRILMAZ (bilgisayari yeniden baslatir).
"""

import sys
import time
from pathlib import Path

from auxy.core import actions

dest = Path(sys.argv[1])
dest.mkdir(parents=True, exist_ok=True)

r = actions.defender_quarantine_op("list")
print("1) list:", r.ok, r.message)
items = r.data or []
for it in items:
    print("   -", it["threat"], "|", it["path"][-60:], "|", it["quarantined_at"])
eicar = [i for i in items if "EICAR" in i["threat"] and i["scheme"] == "file"]
if not eicar:
    print("EICAR ogesi yok, geri yukleme atlandi")
else:
    target = eicar[0]["path"]
    r2 = actions.defender_quarantine_op("restore", target, str(dest))
    print("2) restore:", r2.ok, r2.message)
    time.sleep(3)
    print("   hedef klasorde dosya var mi:", [p.name for p in dest.iterdir()])
    after = actions.defender_quarantine_op("list")
    print("   restore sonrasi listede ayni yol var mi:", any(i["path"] == target for i in (after.data or [])))

if "--no-clean" not in sys.argv:
    r3 = actions.defender_quarantine_op("clean")
    print("3) clean:", r3.ok, r3.message)
