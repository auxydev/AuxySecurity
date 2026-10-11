"""Gizlilik ayarlari: reklam kimligi, kisisellestirilmis deneyimler (HKCU, yonetici gerekmez) ve Wi-Fi MAC adresi
rastgelelestirme (netsh, yonetici gerekir).

MAC rastgelelestirme neden: acik/yurt/kampus Wi-Fi aglarinda cihazinin gercek donanim adresi (MAC) her baglantida
ayni gorunur ve cihazi aglar arasinda takip etmeye yarar. Rastgele adres bunu zorlastirir.
"""

from __future__ import annotations

import re
import subprocess
import winreg
from collections.abc import Callable

from auxy.core import pshell
from auxy.core.service import AuxyError

FLAGS = {  # anahtar -> (HKCU alt yolu, deger adi, etiket, aciklama)
    "ad_id": (r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", "Reklam kimliği",
              "Uygulamaların seni reklamlar için takip etmesine yarayan benzersiz kimlik."),
    "tailored": (r"Software\Microsoft\Windows\CurrentVersion\Privacy", "TailoredExperiencesWithDiagnosticDataEnabled",
                 "Kişiselleştirilmiş deneyimler", "Tanılama verinle sana özel öneri ve reklam gösterilmesine izin verir."),
}
MAC_RE = re.compile(r"MAC randomization\s+(enabled|disabled)\s+on interface\s+(.+)$", re.I | re.M)


def get_flag(key: str) -> bool | None:
    """Ayar acik mi? (deger yoksa Windows varsayilani: acik -> None doner)."""
    path, name, _label, _hint = FLAGS[key]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return bool(winreg.QueryValueEx(k, name)[0])
    except FileNotFoundError:
        return None


def set_flag(key: str, enabled: bool) -> str:
    if key not in FLAGS:
        raise AuxyError(f"Bilinmeyen gizlilik ayarı: {key!r}")
    path, name, label, _hint = FLAGS[key]
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 1 if enabled else 0)
    except OSError as exc:
        raise AuxyError(f"{label} değiştirilemedi: {exc}") from exc
    return f"{label}: {'açık' if enabled else 'kapalı'}"


def parse_mac_randomization(text: str) -> dict[str, bool]:
    return {m.group(2).strip(): m.group(1).lower() == "enabled" for m in MAC_RE.finditer(text)}


def _netsh(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(["netsh", *args], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return proc.returncode, pshell.decode_output(proc.stdout or b"") + pshell.decode_output(proc.stderr or b"")


def read_mac_randomization(run: Callable = _netsh) -> dict[str, bool]:
    """Wi-Fi arayuzu -> rastgele MAC acik mi. Yonetici gerekmez. Wi-Fi yoksa bos sozluk."""
    rc, out = run(["wlan", "show", "randomization"])
    return parse_mac_randomization(out) if rc == 0 else {}


def set_mac_randomization(enabled: bool, interface: str, run: Callable = _netsh) -> str:
    """Yonetici gerekir. Degisiklik bir sonraki baglantida gecerli olur."""
    if not interface or any(c in interface for c in '"\r\n'):
        raise AuxyError("Geçersiz arayüz adı.")
    rc, out = run(["wlan", "set", "randomization", f"enabled={'yes' if enabled else 'no'}", f"interface={interface}"])
    if rc != 0:
        raise AuxyError(f"MAC rastgeleleştirme değiştirilemedi: {out.strip()[-200:]}")
    return (f"{interface}: rastgele MAC {'açıldı' if enabled else 'kapatıldı'} "
            "(Wi-Fi'ye yeniden bağlanınca etkinleşir).")
