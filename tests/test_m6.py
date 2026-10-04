import json

import pytest

from auxy.core import actions, backup, exclusions, system, winsec
from auxy.core.service import AuxyError, NotAdminError, UnknownSettingError
from auxy.core.winsec import HKCU, HKLM, WinSecError, WinSecService


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path))
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


class FakeEnv(winsec.WinEnv):
    def __init__(self, apply=True):
        self.reg = {}
        self.fw = {"domain": True, "private": True, "public": True}
        self.inbound = {"domain": "NotConfigured", "private": "NotConfigured", "public": "NotConfigured"}
        self.apply = apply
        self.calls = []

    def get_reg(self, hive, path, name):
        return self.reg.get((hive, path, name))

    def set_reg(self, hive, path, name, value, kind):
        self.calls.append(("set", name, value))
        if self.apply:
            self.reg[(hive, path, name)] = value

    def delete_reg(self, hive, path, name):
        self.calls.append(("del", name))
        self.reg.pop((hive, path, name), None)

    def firewall_enabled(self, profile):
        return self.fw[profile]

    def firewall_inbound_all(self):
        return dict(self.inbound)

    def firewall_inbound(self, profile):
        return self.inbound[profile]

    def set_firewall_inbound(self, profile, value):
        self.calls.append(("fw_in", profile, value))
        if self.apply:
            self.inbound[profile] = value

    def set_firewall(self, profile, enabled):
        self.calls.append(("fw", profile, enabled))
        if self.apply:
            self.fw[profile] = enabled


def svc(env, admin=True):
    return WinSecService(env, is_admin=lambda: admin)


# ---- okuma ----
def test_defaults_when_values_absent():
    got = svc(FakeEnv()).get_all()
    assert got == {"fw_domain": "on", "fw_private": "on", "fw_public": "on",
                   "fw_in_domain": "default", "fw_in_private": "default", "fw_in_public": "default",
                   "smartscreen_apps": "warn", "smartscreen_store": "on", "hvci": "off"}


def test_reads_explicit_values():
    env = FakeEnv()
    s = winsec.WINSEC_SETTINGS["smartscreen_apps"]
    env.reg[(*s.reg[:3],)] = "RequireAdmin"
    hv = winsec.WINSEC_SETTINGS["hvci"]
    env.reg[(*hv.reg[:3],)] = 1
    env.fw["public"] = False
    got = svc(env).get_all()
    assert got["smartscreen_apps"] == "block" and got["hvci"] == "on" and got["fw_public"] == "off"


# ---- yazma / geri alma ----
def test_firewall_toggle_and_revert():
    env = FakeEnv()
    r = svc(env).set("fw_private", "off")
    assert r.changed and env.fw["private"] is False and env.calls == [("fw", "private", False)]
    assert backup.load() == {"ws:fw_private": True}
    out = svc(env).revert("fw_private")
    assert out[0].new == "on" and env.fw["private"] is True and backup.load() == {}


def test_absent_registry_value_is_restored_by_deleting():
    env = FakeEnv()
    s = svc(env)
    s.set("smartscreen_apps", "off")
    key = winsec.WINSEC_SETTINGS["smartscreen_apps"].reg[:3]
    assert env.reg[key] == "Off" and backup.load() == {"ws:smartscreen_apps": None}
    s.revert("smartscreen_apps")
    assert key not in env.reg  # orijinal "deger yok" idi -> silindi
    assert env.calls[-1] == ("del", "SmartScreenEnabled")


def test_setting_default_value_when_absent_is_noop():
    env = FakeEnv()
    r = svc(env).set("smartscreen_apps", "warn")
    assert not r.changed and env.calls == [] and backup.load() == {}


def test_original_preserved_across_changes():
    env = FakeEnv()
    s = svc(env)
    s.set("smartscreen_apps", "block")
    s.set("smartscreen_apps", "off")
    assert backup.load() == {"ws:smartscreen_apps": None}


def test_manual_return_to_original_clears_backup():
    env = FakeEnv()
    s = svc(env)
    s.set("fw_public", "off")
    s.set("fw_public", "on")
    assert backup.load() == {}


def test_admin_required_except_hkcu_store():
    env = FakeEnv()
    with pytest.raises(NotAdminError):
        svc(env, admin=False).set("fw_public", "off")
    with pytest.raises(NotAdminError):
        svc(env, admin=False).set("hvci", "on")
    assert env.calls == []
    assert svc(env, admin=False).set("smartscreen_store", "off").changed  # HKCU: yonetici gerekmez
    assert (HKCU, winsec.WINSEC_SETTINGS["smartscreen_store"].reg[1], "EnableWebContentEvaluation") in env.reg


def test_not_applied_is_detected_and_backup_dropped():
    env = FakeEnv(apply=False)
    with pytest.raises(WinSecError, match="değiştirilemedi"):
        svc(env).set("hvci", "on")
    assert backup.load() == {}


def test_write_exception_drops_backup():
    env = FakeEnv()

    def boom(*a, **k):
        raise PermissionError("erisim")

    env.set_reg = boom
    with pytest.raises(WinSecError, match="değiştirilemedi"):
        svc(env).set("hvci", "on")
    assert backup.load() == {}


def test_hvci_marks_reboot_and_uses_hklm():
    s = winsec.WINSEC_SETTINGS["hvci"]
    assert s.reboot and s.reg[0] == HKLM and s.reg[2] == "Enabled"
    env = FakeEnv()
    svc(env).set("hvci", "on")
    assert env.reg[(HKLM, s.reg[1], "Enabled")] == 1


def test_invalid_key_value():
    with pytest.raises(UnknownSettingError):
        svc(FakeEnv()).set("nope", "on")
    with pytest.raises(UnknownSettingError):
        svc(FakeEnv()).set("fw_public", "belki")


def test_winsec_and_defender_backups_do_not_clash():
    backup.remember_original("pua", 1)
    env = FakeEnv()
    svc(env).set("fw_public", "off")
    svc(env).revert()  # yalnizca "ws:" anahtarlarini geri alir
    assert backup.load() == {"pua": 1}


def test_revert_without_saved_value():
    with pytest.raises(AuxyError):
        svc(FakeEnv()).revert("hvci")


# ---- guvenlik merkezi / exploit / tpm ----
def test_decode_product_state():
    assert winsec.decode_product_state(0x061100) == (True, True)    # etkin, guncel
    assert winsec.decode_product_state(0x061110) == (True, False)   # etkin, eski imza
    assert winsec.decode_product_state(0x060000) == (False, True)   # kapali


def test_exploit_protection_parsing_and_error():
    ok = winsec.read_exploit_protection(lambda c: json.dumps({"DEP": "NOTSET", "CFG": "ON"}))
    assert ok == {"DEP": "NOTSET", "CFG": "ON"}
    with pytest.raises(WinSecError):
        winsec.read_exploit_protection(lambda c: "bozuk")
    assert "HighEntropy" in [n for n, *_ in winsec.EXPLOIT_ITEMS]


def test_tpm_parse():
    assert winsec.read_tpm(lambda c: '{"TpmPresent":true}') == {"TpmPresent": True}
    # gercek makinede gorulen NUL dolgusu temizlenir
    got = winsec.read_tpm(lambda c: '{"ManufacturerVersion":"600.18.25.2027\\u0000\\u0000\\u0000"}')
    assert got == {"ManufacturerVersion": "600.18.25.2027"}
    with pytest.raises(WinSecError):
        winsec.read_tpm(lambda c: "x")


# ---- dislamalar ----
@pytest.mark.parametrize("path", [
    "C:\\", "C:", "relative\\path", "\\\\sunucu\\paylasim", "C:\\Windows", "C:\\Windows\\System32",
    "C:\\Users", "C:\\a\\*.exe", "C:\\a?b", "", "C:\\x\ny",
])
def test_bad_paths_rejected(path):
    with pytest.raises(exclusions.ExclusionError):
        exclusions.validate_op("add", "path", path)


def test_good_path_accepted():
    assert exclusions.validate_op("add", "path", "C:\\Projeler\\derleme") == "C:\\Projeler\\derleme"


@pytest.mark.parametrize("ext", ["exe", ".dll", "PS1", "bat", "js", "py", "a b", "", "x" * 11, "a;b"])
def test_bad_extensions_rejected(ext):
    with pytest.raises(exclusions.ExclusionError):
        exclusions.validate_op("add", "extension", ext)


def test_good_extension_normalized():
    assert exclusions.validate_op("add", "extension", ".LOG") == "log"


@pytest.mark.parametrize("proc", ["x", "a.dll", "a;b.exe", "..\\x.exe", "$(calc).exe", "a" * 70 + ".exe"])
def test_bad_process_rejected(proc):
    with pytest.raises(exclusions.ExclusionError):
        exclusions.validate_op("add", "process", proc)


def test_remove_allows_foreign_values_but_not_garbage():
    assert exclusions.validate_op("remove", "path", "C:\\Eski\\*.tmp") == "C:\\Eski\\*.tmp"
    with pytest.raises(exclusions.ExclusionError):
        exclusions.validate_op("remove", "path", "")


def test_bad_op_and_kind():
    with pytest.raises(exclusions.ExclusionError):
        exclusions.validate_op("drop", "path", "C:\\x")
    with pytest.raises(exclusions.ExclusionError):
        exclusions.validate_op("add", "registry", "x")


class FakePS:
    def __init__(self):
        self.state = {"ExclusionPath": [], "ExclusionExtension": [], "ExclusionProcess": []}
        self.cmds = []

    def __call__(self, command, arg=""):
        self.cmds.append((command, arg))
        if command.startswith("Get-MpPreference"):
            return 0, json.dumps({k: (v[0] if len(v) == 1 else v or None) for k, v in self.state.items()}), ""
        verb, param = command.split()[0], command.split()[1].lstrip("-")
        if verb == "Add-MpPreference":
            self.state[param].append(arg)
        else:
            self.state[param].remove(arg)
        return 0, "", ""


def test_add_list_remove_flow_and_values_not_in_command_text():
    ps = FakePS()
    r = exclusions.run_op("add", "path", "C:\\Projeler\\derleme", run=ps)
    assert r.ok and r.changed
    # deger komut metnine GOMULMEZ, ortam degiskeniyle gider
    cmds = [c for c, _ in ps.cmds if c.startswith("Add-")]
    assert cmds == ["Add-MpPreference -ExclusionPath $env:AUXY_ARG"]
    assert "Projeler" not in cmds[0]
    assert exclusions.run_op("add", "path", "C:\\Projeler\\derleme", run=ps).changed is False
    listed = exclusions.run_op("list", "path", run=ps).data
    assert listed["path"] == ["C:\\Projeler\\derleme"]
    assert exclusions.run_op("remove", "path", "C:\\Projeler\\derleme", run=ps).changed
    assert exclusions.run_op("remove", "path", "C:\\Projeler\\derleme", run=ps).changed is False


def test_exclusion_not_applied_detected():
    ps = FakePS()
    real = ps.__call__

    def noop(command, arg=""):
        if command.startswith("Add-"):
            return 0, "", ""  # sessizce yok say
        return real(command, arg)

    with pytest.raises(exclusions.ExclusionError, match="uygulanmadı"):
        exclusions.run_op("add", "extension", "log", run=noop)


def test_list_requires_admin_message():
    def na(command, arg=""):
        return 0, json.dumps({"ExclusionPath": "N/A: Must be an administrator to view exclusions",
                              "ExclusionExtension": None, "ExclusionProcess": None}), ""

    with pytest.raises(exclusions.ExclusionError, match="yönetici"):
        exclusions.list_all(na)


# ---- UAC yardimci akisi ----
def test_apply_winsec_elevates_when_needed_and_not_for_hkcu(monkeypatch):
    seen = []

    def fake(args, timeout_s=120):
        seen.append(args)
        actions.write_result(args[args.index("--result") + 1], True, "on → off", True)
        return 0

    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", fake)
    r = actions.apply_winsec("fw_public", "off")
    assert r.ok and seen[0][:3] == ["winsec-set", "fw_public", "off"]

    class FakeSvc:
        def set(self, k, v):
            return winsec.WinSetResult(k, "on", "off", True)

    monkeypatch.setattr(winsec, "WinSecService", FakeSvc)
    seen.clear()
    r2 = actions.apply_winsec("smartscreen_store", "off")  # yonetici gerekmez
    assert r2.ok and seen == []


def test_apply_winsec_reboot_note(monkeypatch):
    class FakeSvc:
        def set(self, k, v):
            return winsec.WinSetResult(k, "off", "on", True)

    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(winsec, "WinSecService", FakeSvc)
    assert "yeniden başlatma" in actions.apply_winsec("hvci", "on").message


def test_exclusion_op_validates_before_uac(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    called = []
    monkeypatch.setattr(system, "run_elevated_and_wait", lambda *a, **k: called.append(1))
    with pytest.raises(exclusions.ExclusionError):
        actions.exclusion_op("add", "path", "C:\\")
    assert called == []  # gecersiz girdi icin UAC penceresi acilmaz


def test_result_carries_data(monkeypatch):
    def fake(args, timeout_s=120):
        actions.write_result(args[args.index("--result") + 1], True, "ok", False, {"a": [1]})
        return 0

    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", fake)
    assert actions.read_tpm().data == {"a": [1]}


# ---------------- gelen baglanti eylemi + yedek anahtarlarinin karismamasi (eksik tamamlama) ----------------
def test_inbound_action_set_verify_and_revert():
    env = FakeEnv()
    s = svc(env)
    r = s.set("fw_in_public", "block")
    assert r.changed and (r.old, r.new) == ("default", "block")
    assert env.calls == [("fw_in", "public", "Block")] and env.inbound["public"] == "Block"
    assert backup.load() == {"ws:fw_in_public": "NotConfigured"}
    assert s.get_all()["fw_in_public"] == "block"
    s.revert("fw_in_public")
    assert env.inbound["public"] == "NotConfigured" and backup.load() == {}


def test_inbound_noop_not_applied_and_admin():
    env = FakeEnv()
    assert not svc(env).set("fw_in_private", "default").changed and env.calls == []
    with pytest.raises(NotAdminError):
        svc(env, admin=False).set("fw_in_private", "allow")
    bad = FakeEnv(apply=False)
    with pytest.raises(WinSecError, match="değiştirilemedi"):
        svc(bad).set("fw_in_domain", "allow")
    assert backup.load() == {}


def test_inbound_prefetch_is_single_call_and_falls_back():
    env = FakeEnv()
    calls = {"all": 0, "one": 0}
    env.firewall_inbound_all = lambda: calls.__setitem__("all", calls["all"] + 1) or dict(env.inbound)
    env.firewall_inbound = lambda p: calls.__setitem__("one", calls["one"] + 1) or "NotConfigured"
    svc(env).get_all()
    assert calls == {"all": 1, "one": 0}  # 3 profil icin TEK sorgu
    def boom():
        raise RuntimeError("ps yok")
    env.firewall_inbound_all = boom
    assert svc(env).get_all()["fw_in_domain"] == "default"  # onbellek yoksa profil basina okuma


def test_defender_revert_all_ignores_winsec_and_other_backup_keys():
    """GERCEK HATA: yedekte 'ws:...' / 'fwrules' varken `revert()` UnknownSettingError ile cokuyordu."""
    from auxy.core.service import DefenderService

    backup.remember_original("ws:fw_public", True)
    backup.set_value("fwrules", ["Kural-1"])
    backup.remember_original("pua", 1)
    calls = []

    class St:
        tamper_protected = False
        prefs = {"PUAProtection": 0}

    DefenderService(read=lambda: St(), run=lambda c: calls.append(c) or (0, "", ""), is_admin=lambda: True)
    # PUAProtection 0 -> 1 geri alma: okuma sahte oldugundan dogrulama gecmez; amac sadece anahtar filtresi
    try:
        DefenderService(read=lambda: St(), run=lambda c: (0, "", ""), is_admin=lambda: True).revert()
    except AuxyError as exc:
        assert "Bilinmeyen ayar" not in str(exc)  # eski hata: UnknownSettingError('ws:fw_public')
    assert backup.load().get("ws:fw_public") is True and backup.load().get("fwrules") == ["Kural-1"]  # dokunulmadi
