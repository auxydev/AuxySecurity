"""Defender ayarlarini okuyup yazan servis (UI'dan bagimsiz)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from auxy.core import backup, defender, system
from auxy.core.log import get_logger
from auxy.core.settings import SETTINGS, Setting


class AuxyError(RuntimeError):
    """Kullaniciya gosterilebilir hata."""


class NotAdminError(AuxyError):
    pass


class TamperBlockedError(AuxyError):
    pass


class UnknownSettingError(AuxyError):
    pass


@dataclass(frozen=True)
class SetResult:
    key: str
    old: str
    new: str
    changed: bool


def run_powershell(command: str) -> tuple[int, str, str]:
    from auxy.core import pshell

    return pshell.run(command, timeout=60)


def key_saved_equals(key: str, raw) -> bool:
    saved = backup.load()
    return key in saved and saved[key] == raw and type(saved[key]) is type(raw)


def _lookup(key: str) -> Setting:
    try:
        return SETTINGS[key]
    except KeyError:
        raise UnknownSettingError(
            f"Bilinmeyen ayar: {key!r}. Gecerli: {', '.join(SETTINGS)}"
        ) from None


class DefenderService:
    def __init__(
        self,
        read: Callable[[], defender.DefenderStatus] = defender.read_status,
        run: Callable[[str], tuple[int, str, str]] = run_powershell,
        is_admin: Callable[[], bool] = system.is_admin,
    ):
        self._read = read
        self._run = run
        self._is_admin = is_admin
        self._log = get_logger()

    def get_all(self) -> dict[str, str]:
        prefs = self._read().prefs
        return {k: s.name_of(prefs[s.pref_field]) for k, s in SETTINGS.items()}

    def set(self, key: str, name: str) -> SetResult:
        setting = _lookup(key)
        if name not in setting.choices:
            raise UnknownSettingError(
                f"{key} icin gecersiz deger {name!r}. Gecerli: {', '.join(setting.choices)}"
            )
        target = setting.choices[name]
        return self._apply(setting, target, track_backup=True)

    def revert(self, key: str | None = None) -> list[SetResult]:
        saved = backup.load()
        # yedek dosyasi baska ozelliklerin anahtarlarini da icerir (ws:..., fwrules): yalnizca Defender ayarlari
        keys = [key] if key else [k for k in saved if k in SETTINGS]
        results = []
        for k in keys:
            setting = _lookup(k)
            if k not in saved:
                raise AuxyError(f"{k} icin kayitli orijinal deger yok.")
            results.append(self._apply(setting, saved[k], track_backup=False))
            backup.forget(k)
        return results

    def _apply(self, setting: Setting, target, track_backup: bool) -> SetResult:
        if not self._is_admin():
            raise NotAdminError("Bu islem yonetici yetkisi gerektirir.")
        st = self._read()
        current = st.prefs[setting.pref_field]
        old_name, new_name = setting.name_of(current), setting.name_of(target)
        if current == target and type(current) is type(target):
            return SetResult(setting.key, old_name, new_name, changed=False)
        if st.tamper_protected and setting.tamper_guarded:
            raise TamperBlockedError(
                f"{setting.label} değiştirilemedi: Tamper Protection açık olduğu için Windows "
                "bu ayara dışarıdan müdahaleye izin vermiyor."
            )

        created = backup.remember_original(setting.key, current) if track_backup else False
        cmd = f"Set-MpPreference -{setting.ps_param} {setting.ps_literal(target)}"
        rc, _out, err = self._run(cmd)
        if rc != 0:
            if created:
                backup.forget(setting.key)
            self._log.error("set %s basarisiz rc=%s err=%s", setting.key, rc, err.strip())
            raise AuxyError(f"Set-MpPreference basarisiz: {err.strip() or rc}")

        after = self._read().prefs[setting.pref_field]
        if after != target or type(after) is not type(target):
            if created:
                backup.forget(setting.key)
            self._log.error("set %s uygulanmadi: %s -> istenen %s, okunan %s",
                            setting.key, old_name, new_name, setting.name_of(after))
            if setting.tamper_guarded:
                hint = (
                    "Windows bu ayara dışarıdan müdahaleyi, Tamper Protection kapalı "
                    "görünse bile komut hata vermeden yok sayarak engelliyor."
                )
            else:
                hint = "Bir grup ilkesi veya yönetim politikası engelliyor olabilir."
            raise TamperBlockedError(
                f"{setting.label} değiştirilemedi (değer hâlâ {setting.name_of(after)}). " + hint
            )
        if track_backup and key_saved_equals(setting.key, target):
            backup.forget(setting.key)  # kullanici orijinale elle dondu; bayat kayit kalmasin
        self._log.info("AYAR %s: %s -> %s", setting.key, old_name, new_name)
        return SetResult(setting.key, old_name, new_name, changed=True)
