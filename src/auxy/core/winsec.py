"""Windows Security'nin Defender disindaki bolumleri: guvenlik duvari, SmartScreen, cekirdek yalitimi
(Memory Integrity), cihaz guvenligi, Guvenlik Merkezi ve exploit protection (salt-okunur).

Yazilabilen her ayar GERI ALINABILIR: ilk degisiklikte orijinal deger (yoksa 'yok') yedeklenir.
Exploit protection bilerek salt-okunurdur: Windows tek tek "varsayilana don" sunmaz, yani yazma geri alinamaz.
"""

from __future__ import annotations

import json
import subprocess
import winreg
from collections.abc import Callable
from dataclasses import dataclass

from auxy.core import backup, system
from auxy.core.defender import com_apartment
from auxy.core.log import get_logger
from auxy.core.service import AuxyError, NotAdminError, UnknownSettingError

HKLM, HKCU = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER
FW_BASE = r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy"
FW_PROFILES = {"domain": ("Domain", "DomainProfile"), "private": ("Private", "StandardProfile"),
               "public": ("Public", "PublicProfile")}
BACKUP_PREFIX = "ws:"


class WinSecError(AuxyError):
    pass


@dataclass(frozen=True)
class WinSetting:
    key: str
    label: str
    group: str
    choices: dict[str, object]  # kullanici adi -> ham deger
    default_raw: object  # deger YOKKEN gecerli sayilan ham deger
    needs_admin: bool = True
    reboot: bool = False
    hint: str = ""
    # kayit defteri ayari (guvenlik duvari icin None)
    reg: tuple | None = None  # (hive, yol, ad, tur: "str"|"dword")
    firewall: str | None = None  # "domain" | "private" | "public"

    def name_of(self, raw) -> str:
        eff = self.default_raw if raw is None else raw
        for name, value in self.choices.items():
            if value == eff and type(value) is type(eff):
                return name
        return f"?({raw})"


WINSEC_SETTINGS: dict[str, WinSetting] = {
    s.key: s
    for s in (
        WinSetting("fw_domain", "Güvenlik duvarı: Etki alanı ağı", "firewall",
                   {"on": True, "off": False}, True, firewall="domain"),
        WinSetting("fw_private", "Güvenlik duvarı: Özel ağ", "firewall",
                   {"on": True, "off": False}, True, firewall="private"),
        WinSetting("fw_public", "Güvenlik duvarı: Genel ağ", "firewall",
                   {"on": True, "off": False}, True, firewall="public"),
        WinSetting("smartscreen_apps", "SmartScreen: uygulamalar ve dosyalar", "smartscreen",
                   {"off": "Off", "warn": "Warn", "block": "RequireAdmin"}, "Warn",
                   reg=(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer",
                        "SmartScreenEnabled", "str")),
        WinSetting("smartscreen_store", "SmartScreen: Microsoft Store uygulamaları", "smartscreen",
                   {"on": 1, "off": 0}, 1, needs_admin=False,
                   reg=(HKCU, r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppHost",
                        "EnableWebContentEvaluation", "dword")),
        WinSetting("hvci", "Çekirdek yalıtımı: Bellek bütünlüğü", "device",
                   {"on": 1, "off": 0}, 0, reboot=True,
                   hint="Uyumsuz sürücüler yüklenemeyebilir; değişiklik yeniden başlatınca etkinleşir.",
                   reg=(HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios"
                              r"\HypervisorEnforcedCodeIntegrity", "Enabled", "dword")),
    )
}


# ---------------- ortam (gercek / test) ----------------
class WinEnv:
    """Kayit defteri ve guvenlik duvari islemleri. Testlerde taklit edilir."""

    def get_reg(self, hive, path: str, name: str):
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                return winreg.QueryValueEx(k, name)[0]
        except FileNotFoundError:
            return None

    def set_reg(self, hive, path: str, name: str, value, kind: str) -> None:
        with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ if kind == "str" else winreg.REG_DWORD, value)

    def delete_reg(self, hive, path: str, name: str) -> None:
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass

    def firewall_enabled(self, profile: str) -> bool:
        raw = self.get_reg(HKLM, f"{FW_BASE}\\{FW_PROFILES[profile][1]}", "EnableFirewall")
        return bool(raw) if raw is not None else True

    def set_firewall(self, profile: str, enabled: bool) -> None:
        name = FW_PROFILES[profile][0]  # izinli listeden: Domain/Private/Public
        cmd = f"Set-NetFirewallProfile -Name {name} -Enabled {'True' if enabled else 'False'}"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            raise WinSecError(f"Set-NetFirewallProfile başarısız: "
                              f"{proc.stderr.decode('utf-8', 'replace').strip() or proc.returncode}")


@dataclass(frozen=True)
class WinSetResult:
    key: str
    old: str
    new: str
    changed: bool


class WinSecService:
    def __init__(self, env: WinEnv | None = None, is_admin: Callable[[], bool] = system.is_admin):
        self._env = env or WinEnv()
        self._is_admin = is_admin
        self._log = get_logger()

    # ---- okuma ----
    def read_raw(self, s: WinSetting):
        if s.firewall:
            return self._env.firewall_enabled(s.firewall)
        hive, path, name, _kind = s.reg
        return self._env.get_reg(hive, path, name)

    def get_all(self) -> dict[str, str]:
        return {k: s.name_of(self.read_raw(s)) for k, s in WINSEC_SETTINGS.items()}

    # ---- yazma ----
    def set(self, key: str, name: str) -> WinSetResult:
        s = self._lookup(key)
        if name not in s.choices:
            raise UnknownSettingError(f"{key} için geçersiz değer {name!r}. Geçerli: {', '.join(s.choices)}")
        return self._apply(s, s.choices[name], track_backup=True)

    def revert(self, key: str | None = None) -> list[WinSetResult]:
        saved = {k[len(BACKUP_PREFIX):]: v for k, v in backup.load().items() if k.startswith(BACKUP_PREFIX)}
        keys = [key] if key else list(saved)
        out = []
        for k in keys:
            s = self._lookup(k)
            if k not in saved:
                raise AuxyError(f"{k} için kayıtlı orijinal değer yok.")
            out.append(self._apply(s, saved[k], track_backup=False))
            backup.forget(BACKUP_PREFIX + k)
        return out

    @staticmethod
    def _lookup(key: str) -> WinSetting:
        try:
            return WINSEC_SETTINGS[key]
        except KeyError:
            raise UnknownSettingError(f"Bilinmeyen ayar: {key!r}. Geçerli: {', '.join(WINSEC_SETTINGS)}") from None

    @staticmethod
    def _same(a, b) -> bool:
        return a == b and type(a) is type(b)

    def _apply(self, s: WinSetting, target, track_backup: bool) -> WinSetResult:
        if s.needs_admin and not self._is_admin():
            raise NotAdminError("Bu işlem yönetici yetkisi gerektirir.")
        current = self.read_raw(s)
        effective_now = s.default_raw if current is None else current
        effective_target = s.default_raw if target is None else target
        old_name, new_name = s.name_of(current), s.name_of(target)
        restoring_absent = target is None and current is not None  # orijinal "deger yok" idi
        if self._same(effective_now, effective_target) and not restoring_absent:
            return WinSetResult(s.key, old_name, new_name, False)

        bkey = BACKUP_PREFIX + s.key
        created = backup.remember_original(bkey, current) if track_backup else False
        try:
            self._write(s, target)
        except Exception as exc:
            if created:
                backup.forget(bkey)
            self._log.error("winsec %s yazilamadi: %s", s.key, exc)
            if isinstance(exc, AuxyError):
                raise
            raise WinSecError(f"{s.label} değiştirilemedi: {exc}") from exc

        after = self.read_raw(s)
        if not self._same(s.default_raw if after is None else after, effective_target):
            if created:
                backup.forget(bkey)
            raise WinSecError(f"{s.label} değiştirilemedi (değer hâlâ {s.name_of(after)}). "
                              "Bir grup ilkesi ya da Windows koruması engelliyor olabilir.")
        if track_backup and self._saved_equals(bkey, target):
            backup.forget(bkey)  # kullanici orijinale elle dondu
        self._log.info("WINSEC %s: %s -> %s", s.key, old_name, new_name)
        return WinSetResult(s.key, old_name, new_name, True)

    @staticmethod
    def _saved_equals(bkey: str, raw) -> bool:
        saved = backup.load()
        return bkey in saved and saved[bkey] == raw and type(saved[bkey]) is type(raw)

    def _write(self, s: WinSetting, target) -> None:
        if s.firewall:
            self._env.set_firewall(s.firewall, bool(target))
            return
        hive, path, name, kind = s.reg
        if target is None:
            self._env.delete_reg(hive, path, name)
        else:
            self._env.set_reg(hive, path, name, target, kind)


# ---------------- salt-okunur bilgiler ----------------
@dataclass(frozen=True)
class SecurityProduct:
    category: str  # Antivirus / Güvenlik duvarı / Casus yazılımdan koruma
    name: str
    enabled: bool
    up_to_date: bool


def decode_product_state(state: int) -> tuple[bool, bool]:
    """Guvenlik Merkezi productState: (etkin mi, imzalar guncel mi)."""
    return ((state >> 12) & 0xF) == 1, ((state >> 4) & 0xF) == 0


def read_security_center() -> list[SecurityProduct]:
    import win32com.client

    out = []
    with com_apartment():
        svc = win32com.client.GetObject(r"winmgmts:\\.\root\SecurityCenter2")
        for cls, cat in (("AntiVirusProduct", "Antivirüs"), ("FirewallProduct", "Güvenlik duvarı"),
                         ("AntiSpywareProduct", "Casus yazılımdan koruma")):
            try:
                for p in svc.ExecQuery(f"SELECT * FROM {cls}"):
                    enabled, fresh = decode_product_state(int(p.productState))
                    out.append(SecurityProduct(cat, str(p.displayName), enabled, fresh))
            except Exception:  # sinif yok / erisim yok
                continue
    return out


@dataclass(frozen=True)
class DeviceSecurity:
    secure_boot: bool | None
    vbs_running: bool | None
    hvci_running: bool | None


def read_device_security(env: WinEnv | None = None) -> DeviceSecurity:
    env = env or WinEnv()
    sb = env.get_reg(HKLM, r"SYSTEM\CurrentControlSet\Control\SecureBoot\State", "UEFISecureBootEnabled")
    vbs = hvci = None
    try:
        import win32com.client

        with com_apartment():
            svc = win32com.client.GetObject(r"winmgmts:\\.\root\Microsoft\Windows\DeviceGuard")
            for dg in svc.ExecQuery("SELECT * FROM Win32_DeviceGuard"):
                vbs = int(dg.VirtualizationBasedSecurityStatus) == 2
                hvci = 2 in [int(x) for x in (dg.SecurityServicesRunning or [])]
    except Exception:
        pass
    return DeviceSecurity(None if sb is None else bool(sb), vbs, hvci)


EXPLOIT_ITEMS = (
    ("DEP", "Dep", "Enable", "Veri yürütme engelleme (DEP)"),
    ("SEHOP", "Sehop", "Enable", "SEHOP"),
    ("CFG", "Cfg", "Enable", "Denetim akışı koruması (CFG)"),
    ("ForceRelocateImages", "Aslr", "ForceRelocateImages", "Zorunlu ASLR"),
    ("BottomUp", "Aslr", "BottomUp", "Aşağıdan yukarı ASLR"),
    ("HighEntropy", "Aslr", "HighEntropy", "Yüksek entropili ASLR"),
)
EXPLOIT_STATES = {"ON": "Açık", "OFF": "Kapalı", "NOTSET": "Varsayılan (Windows)"}


def read_exploit_protection(run: Callable | None = None) -> dict[str, str]:
    """Sistem duzeyi exploit protection (SALT-OKUNUR). {ad: ON/OFF/NOTSET}"""
    props = "; ".join(f"'{n}'=[string]$m.{grp}.{prop}" for n, grp, prop, _ in EXPLOIT_ITEMS)
    cmd = f"$m = Get-ProcessMitigation -System; [pscustomobject]@{{{props}}} | ConvertTo-Json -Compress"
    proc = (run or _ps)(cmd)
    try:
        return {k: str(v) for k, v in json.loads(proc).items()}
    except (json.JSONDecodeError, AttributeError):
        raise WinSecError("Exploit protection durumu okunamadı.") from None


def _ps(command: str) -> str:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise WinSecError(proc.stderr.decode("utf-8", "replace").strip() or f"çıkış kodu {proc.returncode}")
    return proc.stdout.decode("utf-8", "replace")


def read_tpm(run: Callable[[str], str] | None = None) -> dict:
    """TPM durumu (yonetici gerekir)."""
    out = (run or _ps)(
        "Get-Tpm | Select-Object TpmPresent,TpmReady,TpmEnabled,TpmActivated,ManufacturerVersion "
        "| ConvertTo-Json -Compress"
    )
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise WinSecError("TPM bilgisi ayrıştırılamadı.") from None
    # Get-Tpm bazi alanlari sabit uzunlukta NUL ile doldurulmus dondurur
    return {k: v.replace("\x00", "").strip() if isinstance(v, str) else v for k, v in data.items()}

