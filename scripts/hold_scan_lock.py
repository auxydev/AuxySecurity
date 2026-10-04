"""Test yardimcisi: tarama kilidini N saniye tutar (surecler arasi kilit testi icin)."""

import sys
import time

from auxy.core import system

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 9
lock = system.ScanLock()
print("kilit alindi:", lock.acquire(), flush=True)
time.sleep(seconds)
lock.release()
print("kilit birakildi", flush=True)
