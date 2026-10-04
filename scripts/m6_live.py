"""M6 gercek makine testi (YONETICI gerekir). Her degisiklik geri alinir; sonuc dosyaya yazilir.

Kullanim: python scripts/m6_live.py <cikti.txt> <dislama_test_klasoru> [--firewall]

Varsayilan olarak guvenlik duvarina DOKUNMAZ. --firewall: Ozel profil ~1.5 sn kapatilip geri acilir.
Yapilan degisiklikler: SmartScreen (Uyar->Engelle->geri), Store SmartScreen, gecici dislama klasoru
(eklenip kaldirilir), HVCI'ye ayni degeri yazma denemesi (degisiklik yapmaz), TPM okuma.
"""

import subprocess
import sys
import time
from pathlib import Path

from auxy.core import exclusions, system, winsec

out_path, excl_dir = sys.argv[1], sys.argv[2]
Path(excl_dir).mkdir(parents=True, exist_ok=True)
log = []


def say(msg):
    log.append(msg)


def fw_ps(name):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-NetFirewallProfile -Name {name}).Enabled"],
                       capture_output=True, text=True)
    return r.stdout.strip()


say(f"admin={system.is_admin()}")
svc = winsec.WinSecService()
before = svc.get_all()
say(f"baslangic: {before}")

try:
    # --- SmartScreen (HKLM): warn -> block -> geri al (deger yoktu -> silinmeli)
    r = svc.set("smartscreen_apps", "block")
    say(f"smartscreen_apps block: {r.old}->{r.new} changed={r.changed}; okunan={svc.get_all()['smartscreen_apps']}")
    r = svc.revert("smartscreen_apps")[0]
    key = winsec.WINSEC_SETTINGS["smartscreen_apps"].reg
    say(f"smartscreen_apps geri: {r.old}->{r.new}; kayit defteri degeri artik yok mu: "
        f"{winsec.WinEnv().get_reg(*key[:3]) is None}")

    # --- SmartScreen Store (HKCU)
    r = svc.set("smartscreen_store", "off")
    say(f"smartscreen_store off: changed={r.changed}; okunan={svc.get_all()['smartscreen_store']}")
    svc.revert("smartscreen_store")
    say(f"smartscreen_store geri: {svc.get_all()['smartscreen_store']}")

    # --- Guvenlik duvari Ozel profil: kapat (kisa sure) -> ac (yalnizca --firewall ile)
    if "--firewall" in sys.argv:
        try:
            r = svc.set("fw_private", "off")
            time.sleep(1.5)
            say(f"fw_private off: changed={r.changed}; kayit defteri={svc.get_all()['fw_private']}; "
                f"Get-NetFirewallProfile.Enabled={fw_ps('Private')}")
        finally:
            svc.revert("fw_private")
            say(f"fw_private geri: kayit defteri={svc.get_all()['fw_private']}; "
                f"Get-NetFirewallProfile.Enabled={fw_ps('Private')}")
    else:
        say("guvenlik duvari adimi atlandi (--firewall verilmedi)")

    # --- HVCI: zaten acik, ayni degeri istemek degisiklik YAPMAMALI (yeniden baslatma gerektirmesin)
    r = svc.set("hvci", "on")
    say(f"hvci on (zaten acik): changed={r.changed}")

    # --- Dislamalar
    before_ex = exclusions.list_all()
    say(f"dislama listesi (baslangic): {before_ex}")
    try:
        a = exclusions.run_op("add", "path", excl_dir)
        listed = exclusions.list_all()["path"]
        say(f"dislama add: {a.message} changed={a.changed}; listede: {any(excl_dir.lower() == p.lower() for p in listed)}")
        a2 = exclusions.run_op("add", "path", excl_dir)
        say(f"dislama tekrar add: changed={a2.changed} ({a2.message})")
    finally:
        rm = exclusions.run_op("remove", "path", excl_dir)
        say(f"dislama remove: {rm.message} changed={rm.changed}")
    say(f"dislama listesi (son) baslangicla ayni: {exclusions.list_all() == before_ex}")
    try:
        exclusions.run_op("add", "path", "C:\\")
        say("HATA: C:\\ dislamasi kabul edildi!")
    except exclusions.ExclusionError as exc:
        say(f"C:\\ reddedildi: {exc}")

    # --- TPM
    say(f"TPM: {winsec.read_tpm()}")
finally:
    after = svc.get_all()
    say(f"son: {after}")
    say("SONUC: " + ("BASLANGICLA AYNI" if after == before else f"FARKLI! once={before} sonra={after}"))
    Path(out_path).write_text("\n".join(log), encoding="utf-8")
