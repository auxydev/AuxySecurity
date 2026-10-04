from auxy import __main__ as cli
from auxy.core import defender


def _fake(realtime=True, tamper=False):
    status = {k: None for k in defender.STATUS_FIELDS}
    status.update(
        AMServiceEnabled=True, AntivirusEnabled=True, RealTimeProtectionEnabled=realtime,
        BehaviorMonitorEnabled=True, IsTamperProtected=tamper,
        AntivirusSignatureVersion="1.0.0.0", AntivirusSignatureLastUpdated="x", AMProductVersion="4.18",
    )
    prefs = dict(MAPSReporting=2, PUAProtection=1, EnableControlledFolderAccess=0,
                 EnableNetworkProtection=0, DisableRealtimeMonitoring=not realtime,
                 SubmitSamplesConsent=1)
    return defender.DefenderStatus(status=status, prefs=prefs)


def test_status_ok(monkeypatch, capsys):
    monkeypatch.setattr(defender, "read_status", lambda: _fake())
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Gercek zamanli koruma     : ACIK" in out
    assert "Gelismis" in out


def test_status_tamper_note(monkeypatch, capsys):
    monkeypatch.setattr(defender, "read_status", lambda: _fake(tamper=True))
    cli.main(["status"])
    assert "Tamper Protection acik" in capsys.readouterr().out


def test_status_error(monkeypatch, capsys):
    def boom():
        raise defender.DefenderError("yok")

    monkeypatch.setattr(defender, "read_status", boom)
    assert cli.main(["status"]) == 1
    assert "HATA" in capsys.readouterr().err


def test_set_invalid_value_rejected_before_admin_check(monkeypatch, capsys):
    monkeypatch.setattr(cli.system, "is_admin", lambda: False)
    assert cli.main(["set", "pua", "x; calc"]) == 2
    assert "gecersiz deger" in capsys.readouterr().err


def test_set_requires_admin_without_elevate(monkeypatch, capsys):
    monkeypatch.setattr(cli.system, "is_admin", lambda: False)
    assert cli.main(["set", "pua", "off"]) == 3
    assert "Yonetici yetkisi gerekli" in capsys.readouterr().err


def test_set_elevate_relaunches_with_pause(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.system, "is_admin", lambda: False)
    monkeypatch.setattr(cli.system, "relaunch_as_admin", lambda a: calls.append(a) or True)
    assert cli.main(["set", "pua", "off", "--elevate"]) == 0
    assert calls == [["set", "pua", "off", "--pause"]]


def test_properties():
    assert _fake(realtime=False).realtime_on is False
    assert _fake(tamper=True).tamper_protected is True
