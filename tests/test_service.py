import json

import pytest

from auxy.core import backup, defender, paths
from auxy.core.service import (
    AuxyError,
    DefenderService,
    NotAdminError,
    TamperBlockedError,
    UnknownSettingError,
)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path))
    # log handler her testte yeni dizine yazsin
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield tmp_path
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


class FakeDefender:
    """Defender'in WMI + PowerShell davranisini taklit eder."""

    def __init__(self, tamper=False, apply=True):
        self.tamper = tamper
        self.apply = apply
        self.prefs = dict(
            DisableRealtimeMonitoring=False, MAPSReporting=1, PUAProtection=1,
            EnableControlledFolderAccess=0, EnableNetworkProtection=0, SubmitSamplesConsent=1,
        )
        self.commands = []
        self.rc = 0

    def read(self):
        status = {k: None for k in defender.STATUS_FIELDS}
        status["IsTamperProtected"] = self.tamper
        return defender.DefenderStatus(status=status, prefs=dict(self.prefs))

    def run(self, command):
        self.commands.append(command)
        if self.rc:
            return self.rc, "", "Erisim engellendi"
        if self.apply:
            _, param, literal = command.split()
            val = {"$true": True, "$false": False}.get(literal)
            self.prefs[param.lstrip("-")] = literal and (val if val is not None else int(literal))
        return 0, "", ""


def svc(fake, admin=True):
    return DefenderService(read=fake.read, run=fake.run, is_admin=lambda: admin)


def test_get_all_names():
    s = svc(FakeDefender())
    assert s.get_all() == {
        "realtime": "on", "maps": "basic", "pua": "on", "cfa": "off", "netprot": "off",
    }


def test_set_changes_value_and_saves_original():
    f = FakeDefender()
    res = svc(f).set("pua", "off")
    assert res.changed and (res.old, res.new) == ("on", "off")
    assert f.commands == ["Set-MpPreference -PUAProtection 0"]
    assert backup.load() == {"pua": 1}


def test_set_realtime_uses_inverted_bool():
    f = FakeDefender()
    svc(f).set("realtime", "off")
    assert f.commands == ["Set-MpPreference -DisableRealtimeMonitoring $true"]
    assert f.prefs["DisableRealtimeMonitoring"] is True
    assert backup.load() == {"realtime": False}


def test_noop_when_same_value():
    f = FakeDefender()
    res = svc(f).set("pua", "on")
    assert not res.changed and f.commands == [] and backup.load() == {}


def test_requires_admin():
    f = FakeDefender()
    with pytest.raises(NotAdminError):
        svc(f, admin=False).set("pua", "off")
    assert f.commands == []


def test_tamper_blocks_guarded_setting_before_running():
    f = FakeDefender(tamper=True)
    with pytest.raises(TamperBlockedError):
        svc(f).set("realtime", "off")
    assert f.commands == [] and backup.load() == {}


def test_tamper_does_not_block_unguarded_setting():
    f = FakeDefender(tamper=True)
    assert svc(f).set("cfa", "on").changed


def test_not_applied_is_detected_and_backup_dropped():
    f = FakeDefender(apply=False)
    with pytest.raises(TamperBlockedError):
        svc(f).set("maps", "off")
    assert backup.load() == {}


def test_powershell_failure_drops_backup():
    f = FakeDefender()
    f.rc = 1
    with pytest.raises(AuxyError, match="Erisim engellendi"):
        svc(f).set("pua", "off")
    assert backup.load() == {}


def test_original_not_overwritten_by_second_change():
    f = FakeDefender()
    s = svc(f)
    s.set("maps", "advanced")
    s.set("maps", "off")
    assert backup.load() == {"maps": 1}  # ilk orijinal (basic) korunur


def test_revert_restores_original_and_clears_backup():
    f = FakeDefender()
    s = svc(f)
    s.set("maps", "advanced")
    s.set("realtime", "off")
    results = s.revert()
    assert {r.key for r in results} == {"maps", "realtime"}
    assert f.prefs["MAPSReporting"] == 1
    assert f.prefs["DisableRealtimeMonitoring"] is False
    assert backup.load() == {}


def test_revert_single_key_keeps_others():
    f = FakeDefender()
    s = svc(f)
    s.set("pua", "off")
    s.set("cfa", "on")
    s.revert("pua")
    assert backup.load() == {"cfa": 0}


def test_revert_unknown_backup():
    with pytest.raises(AuxyError):
        svc(FakeDefender()).revert("pua")


def test_invalid_key_and_value():
    s = svc(FakeDefender())
    with pytest.raises(UnknownSettingError):
        s.set("nope", "on")
    with pytest.raises(UnknownSettingError):
        s.set("pua", "maybe; calc.exe")


def test_backup_file_is_valid_json_and_tolerates_corruption(home):
    backup.remember_original("pua", 1)
    assert json.loads(paths.backup_file().read_text()) == {"pua": 1}
    paths.backup_file().write_text("{bozuk", encoding="utf-8")
    assert backup.load() == {}
