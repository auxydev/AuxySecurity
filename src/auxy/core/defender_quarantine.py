"""Defender'in KENDI karantinasi ve tehdit eylemleri (hepsi yonetici gerektirir).

- list_items   : `MpCmdRun -Restore -ListAll` ciktisini ayristirir
- restore      : `MpCmdRun -Restore -FilePath <yol> [-Path <klasor>]` (yol arguman olarak, kabuk yok)
- clean_active : `Remove-MpThreat` (etkin tehditleri temizler)
- offline_scan : `Start-MpWDOScan` (bilgisayari YENIDEN BASLATIR; yalnizca acik onayla, testlerde calistirilmaz)
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from auxy.core import pshell, scan
from auxy.core.actions import ActionResult
from auxy.core.log import get_logger
from auxy.core.service import AuxyError

_CONTROL = re.compile(r"[\x00-\x1f]")
_ITEM = re.compile(r"^\s+(?P<scheme>[A-Za-z]+):(?P<rest>.+?)\s+quarantined at\s+(?P<when>.+?)\s*$")
_THREAT = re.compile(r"^ThreatName\s*=\s*(?P<name>.+?)\s*$")


class DefenderQuarantineError(AuxyError):
    pass


@dataclass(frozen=True)
class QuarantinedItem:
    threat: str
    path: str  # 'file:' on eki olmadan
    scheme: str  # file / regkey / ...
    quarantined_at: str  # Defender'in yazdigi metin (yerel bicim; "(UTC)" son eki dahil)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_listall(text: str) -> list[QuarantinedItem]:
    """ThreatName = X satirlari ve altindaki 'file:<yol> quarantined at <tarih>' satirlari."""
    items: list[QuarantinedItem] = []
    threat = ""
    for line in text.splitlines():
        m = _THREAT.match(line)
        if m:
            threat = m.group("name")
            continue
        m = _ITEM.match(line)
        if m and threat:
            path = m.group("rest")
            if m.group("scheme").lower() == "file" and path.startswith("_"):
                path = path[1:]  # bazi surumlerde 'file:_C:\...'
            items.append(QuarantinedItem(threat, path, m.group("scheme").lower(), m.group("when")))
    return items


def _mp(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [str(scan.mpcmdrun_path()), *args], capture_output=True, timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return proc.returncode, pshell.decode_output(proc.stdout)  # yerel program: UTF-8 ya da OEM kod sayfasi


def _ps(command: str) -> tuple[int, str]:
    rc, out, err = pshell.run(command, timeout=300)
    return rc, out + err


def list_items(run: Callable[[list[str]], tuple[int, str]] = _mp) -> list[QuarantinedItem]:
    rc, out = run(["-Restore", "-ListAll"])
    if rc != 0:
        raise DefenderQuarantineError(f"Defender karantinası okunamadı (çıkış kodu {rc}): {out.strip()[-200:]}")
    return parse_listall(out)


def validate_restore_path(path: str) -> str:
    if not path or _CONTROL.search(path):
        raise DefenderQuarantineError("Geçersiz dosya yolu.")
    p = Path(path)
    if not p.is_absolute() or not p.drive or path.startswith("\\\\"):
        raise DefenderQuarantineError("Yalnızca yerel sürücüdeki tam yollar geri yüklenebilir.")
    return str(p)


def restore(path: str, to_dir: str | None = None, run: Callable = _mp,
            list_run: Callable | None = None) -> ActionResult:
    """Defender karantinasindaki bir dosyayi geri yukler. Yalnizca karantina LISTESINDE olan yollar kabul edilir."""
    clean = validate_restore_path(path)
    known = {i.path.lower() for i in list_items(list_run or run)}
    if clean.lower() not in known:
        raise DefenderQuarantineError("Bu dosya Defender karantina listesinde değil.")
    args = ["-Restore", "-FilePath", clean]
    if to_dir:
        target = Path(to_dir)
        if not target.is_absolute() or not target.is_dir():
            raise DefenderQuarantineError("Hedef klasör geçersiz.")
        args += ["-Path", str(target)]
    rc, out = run(args)
    get_logger().info("DEFENDER karantina geri yukle: %s -> %s (rc=%s)", clean, to_dir or "orijinal", rc)
    if rc != 0:
        raise DefenderQuarantineError(f"Geri yükleme başarısız (çıkış kodu {rc}): {out.strip()[-200:]}")
    # DOGRULAMA (gercek makine testinden): alternatif klasore geri yuklemede Defender oge karantina LISTESINDE KALIR
    # (kopyalar); bu yuzden o durumda listeye degil, hedef dosyanin varligina bakilir.
    if to_dir:
        landed = Path(to_dir) / Path(clean).name
        if not landed.exists():
            raise DefenderQuarantineError(
                "Geri yükleme uygulanmadı ya da dosya hemen yeniden karantinaya alındı (hedefte bulunamadı).")
        return ActionResult(True, f"Geri yüklendi: {landed}. Gerçek zamanlı koruma dosyayı yeniden "
                                  "karantinaya alabilir.", True)
    still = {i.path.lower() for i in list_items(list_run or run)}
    if clean.lower() in still and not Path(clean).exists():
        raise DefenderQuarantineError("Geri yükleme uygulanmadı: dosya hâlâ karantinada.")
    return ActionResult(True, "Orijinal konuma geri yüklendi. Gerçek zamanlı koruma dosyayı yeniden "
                              "karantinaya alabilir.", True)


def clean_active(run: Callable[[str], tuple[int, str]] = _ps) -> ActionResult:
    rc, out = run("Remove-MpThreat")
    if rc != 0:
        raise DefenderQuarantineError(f"Remove-MpThreat başarısız: {out.strip()[-200:] or rc}")
    get_logger().info("DEFENDER etkin tehditler temizlendi (Remove-MpThreat)")
    return ActionResult(True, "Etkin tehditler Defender tarafından temizlendi.", True)


def offline_scan(run: Callable[[str], tuple[int, str]] = _ps) -> ActionResult:
    """DIKKAT: Bilgisayar yeniden baslar ve Microsoft Defender Cevrimdisi taramasi acilista calisir."""
    rc, out = run("Start-MpWDOScan")
    if rc != 0:
        raise DefenderQuarantineError(f"Start-MpWDOScan başarısız: {out.strip()[-200:] or rc}")
    get_logger().warning("DEFENDER cevrimdisi tarama baslatildi (yeniden baslatma bekleniyor)")
    return ActionResult(True, "Çevrimdışı tarama başlatıldı; bilgisayar yeniden başlayacak.", True)


def run_op(op: str, path: str = "", to_dir: str = "") -> ActionResult:
    """CLI/yukseltilmis yardimci icin tek giris noktasi."""
    if op == "list":
        items = list_items()
        return ActionResult(True, f"{len(items)} öğe.", data=[i.to_dict() for i in items])
    if op == "restore":
        return restore(path, to_dir or None)
    if op == "clean":
        return clean_active()
    if op == "offline-scan":
        return offline_scan()
    raise DefenderQuarantineError(f"Geçersiz işlem: {op!r}")
