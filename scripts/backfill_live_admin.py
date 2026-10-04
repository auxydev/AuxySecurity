"""Eksik tamamlama gercek makine testi (YONETICI gerekir; tek UAC). Her degisiklik geri alinir.

Kullanim: python scripts/backfill_live_admin.py <cikti.txt> <calisma_klasoru> [--firewall]

Yapilanlar:
  1) guvenlik duvari kurali (Wi-Fi Direct gelen) pasiflestir -> yeniden etkinlestir
  2) whoami.exe KOPYASI icin gecici engel kurali kur -> kaldir
  3) Genel ag gelen eylemi: Varsayilan -> Engelle -> Varsayilan (Windows varsayilani zaten engeller)
  4) Defender karantinasi: Turkce karakterli klasorde zararsiz EICAR -> listele (yol bozulmadan) -> alternatif klasore geri yukle
  5) (--firewall) Ozel profil guvenlik duvarini ~1.5 sn kapat -> ac
GUVENLIK DUVARINI KAPATAN adim yalnizca --firewall ile calisir. CEVRIMDISI TARAMA CALISTIRILMAZ.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

from auxy.core import backup, defender_quarantine, firewall, pshell, scan, system, winsec

out_path, work = sys.argv[1], Path(sys.argv[2])
work.mkdir(parents=True, exist_ok=True)
log = []


def say(m):
    log.append(m)


def ps(cmd):
    return pshell.run(cmd)[1].strip()


say(f"admin={system.is_admin()}")
rules_before = sorted(r.name for r in firewall.list_rules())
blocks_before = [r.name for r in firewall.list_blocks()]
svc = winsec.WinSecService()
state_before = svc.get_all()
say(f"baslangic: {len(rules_before)} kural, {len(blocks_before)} engel; {state_before}")

try:
    # ---- 1) kural pasiflestir / etkinlestir
    target = "WFDPRINT-SPOOL-In-Active" if "WFDPRINT-SPOOL-In-Active" in rules_before else rules_before[0]
    r = firewall.disable_rule(target)
    still = target in [x.name for x in firewall.list_rules()]
    say(f"1a) disable {target}: {r.message} | listede hala etkin mi: {still} | bizim pasiflerimiz: {firewall.disabled_by_us()}")
    say(f"    Get-NetFirewallRule.Enabled = {ps(f'(Get-NetFirewallRule -Name {chr(34)}{target}{chr(34)}).Enabled')}")
    r = firewall.enable_rule(target)
    say(f"1b) enable: {r.message} | listede mi: {target in [x.name for x in firewall.list_rules()]} | bizim pasiflerimiz: {firewall.disabled_by_us()}")

    # ---- 2) program engelle / kaldir
    prog = work / "engellenecek-program.exe"
    shutil.copy(Path(__import__('os').environ["SystemRoot"]) / "System32" / "whoami.exe", prog)
    r = firewall.block_program(str(prog))
    names = sorted(x.name for x in firewall.list_blocks())
    say(f"2a) block: {r.message} | kurallar: {names}")
    say(f"    gercek kural: {ps(f'(Get-NetFirewallRule -Name {chr(39)}AuxySecurity-*{chr(39)} | ForEach-Object {{ $_.Direction.ToString() + {chr(39)}/{chr(39)} + $_.Action.ToString() + {chr(39)}/{chr(39)} + $_.Enabled.ToString() }}) -join {chr(39)}, {chr(39)}')}")
    say(f"    tekrar block (idempotent): changed={firewall.block_program(str(prog)).changed}")
    r = firewall.unblock_program(str(prog))
    say(f"2b) unblock: {r.message} | kalan engeller: {[x.name for x in firewall.list_blocks()]}")

    # ---- 3) gelen baglanti eylemi
    r = svc.set("fw_in_public", "block")
    say(f"3a) fw_in_public block: {r.old}->{r.new} changed={r.changed} | Get-NetFirewallProfile: "
        f"{ps('[string](Get-NetFirewallProfile -Name Public).DefaultInboundAction')}")
    r = svc.revert("fw_in_public")[0]
    say(f"3b) geri: {r.old}->{r.new} | Get-NetFirewallProfile: {ps('[string](Get-NetFirewallProfile -Name Public).DefaultInboundAction')}")

    # ---- 4) Defender karantinasi, Turkce yol
    tr_dir = work / "Çalışma Klasörü"
    tr_dir.mkdir(exist_ok=True)
    tr_file = tr_dir / "kötü-eicar.txt"
    eicar = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-" + "TEST-FILE!$H+H*"
    pshell.run("[IO.File]::WriteAllText($env:AUXY_ARG, $env:AUXY_TXT)", {"AUXY_ARG": str(tr_file), "AUXY_TXT": eicar})
    time.sleep(6)
    items = defender_quarantine.list_items(defender_quarantine._mp)
    mine = [i for i in items if "kötü-eicar" in i.path]
    if not mine:  # gercek zamanli koruma yakalamadiysa taramayla yakalat
        scan.ScanManager().run(scan.CUSTOM, str(tr_dir))
        time.sleep(4)
        items = defender_quarantine.list_items(defender_quarantine._mp)
        mine = [i for i in items if "kötü-eicar" in i.path]
    say(f"4a) Turkce yollu oge Defender listesinde, yol bozulmadan okundu mu: {bool(mine)}"
        + (f" | yol: ...{mine[0].path[-32:]}" if mine else f" | listedeki yollar (son 40 krk): {[i.path[-40:] for i in items]}"))
    if mine:
        alt = work / "Geri Yüklenen"
        alt.mkdir(exist_ok=True)
        res = defender_quarantine.restore(mine[0].path, str(alt))
        say(f"4b) alternatif klasore geri yukleme: {res.message} | dosya: {[p.name for p in alt.iterdir()]}")

    # ---- 5) guvenlik duvari profili (yalnizca --firewall)
    if "--firewall" in sys.argv:
        try:
            r = svc.set("fw_private", "off")
            time.sleep(1.5)
            say(f"5a) fw_private off: changed={r.changed} | kayit defteri={svc.get_all()['fw_private']} | "
                f"Get-NetFirewallProfile.Enabled={ps('(Get-NetFirewallProfile -Name Private).Enabled')}")
        finally:
            svc.revert("fw_private")
            say(f"5b) geri: kayit defteri={svc.get_all()['fw_private']} | "
                f"Get-NetFirewallProfile.Enabled={ps('(Get-NetFirewallProfile -Name Private).Enabled')}")
    else:
        say("5) guvenlik duvari profili adimi atlandi (--firewall verilmedi)")
finally:
    # kalinti temizligi (hata olsa bile)
    for n in list(firewall.disabled_by_us()):
        try:
            firewall.enable_rule(n)
        except Exception as exc:  # noqa: BLE001
            say(f"TEMIZLIK HATASI enable {n}: {exc}")
    for b in firewall.list_blocks():
        try:
            firewall.unblock_program(b.name)
        except Exception as exc:  # noqa: BLE001
            say(f"TEMIZLIK HATASI unblock {b.name}: {exc}")
    after_state = svc.get_all()
    rules_after = sorted(r.name for r in firewall.list_rules())
    say(f"son: {len(rules_after)} kural, {len(firewall.list_blocks())} engel, bizim pasifler={firewall.disabled_by_us()}")
    same = after_state == state_before and rules_after == rules_before and not firewall.list_blocks()
    say("SONUC: " + ("BASLANGICLA AYNI" if same else f"FARKLI! once={state_before} sonra={after_state}"))
    say(f"yedek dosyasi: {backup.load()}")
    Path(out_path).write_text("\n".join(log), encoding="utf-8")
