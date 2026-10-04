"""M0 olcumu: WMI (pywin32) ve PowerShell ile durum okuma suresi ve bellek."""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psutil  # noqa: E402

from auxy.core import defender  # noqa: E402

N = 5


def timed(fn):
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def ps():
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-MpComputerStatus | Out-Null; Get-MpPreference | Out-Null"],
        check=True, capture_output=True,
    )


proc = psutil.Process()
rss0 = proc.memory_info().rss / 1e6
first = timed(defender.read_status)
wmi = [timed(defender.read_status) for _ in range(N)]
rss1 = proc.memory_info().rss / 1e6
pss = [timed(ps) for _ in range(3)]

print(f"WMI  ilk cagri : {first:7.0f} ms")
print(f"WMI  sonraki   : {sum(wmi)/len(wmi):7.0f} ms (ort, n={N})")
print(f"PS   cagri     : {sum(pss)/len(pss):7.0f} ms (ort, n=3, yeni surec)")
print(f"Surec RSS      : {rss0:.0f} MB -> {rss1:.0f} MB (WMI sonrasi)")
