import ctypes
import subprocess
import sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import actions, defender, scan, system, threats
from auxy.core.service import AuxyError, DefenderService


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUXY_INSTANCE", "_m8cli")
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def fake_status(realtime=True, tamper=False):
    status = {k: None for k in defender.STATUS_FIELDS}
    status.update(AMServiceEnabled=True, AntivirusEnabled=True, RealTimeProtectionEnabled=realtime,
                  BehaviorMonitorEnabled=True, IsTamperProtected=tamper, AntivirusSignatureVersion="1.2.3.4",
                  AntivirusSignatureLastUpdated=datetime(2026, 10, 5), AMProductVersion="4.18")
    prefs = dict(MAPSReporting=1, PUAProtection=1, EnableControlledFolderAccess=0, EnableNetworkProtection=0,
                 DisableRealtimeMonitoring=False, SubmitSamplesConsent=1)
    return defender.DefenderStatus(status=status, prefs=prefs)


# ---------------- CLI: Defender ayarlari ----------------
def test_cli_get_all_single_and_unknown(monkeypatch, capsys):
    monkeypatch.setattr(defender, "read_status", lambda: fake_status())
    assert cli.main(["get"]) == 0
    out = capsys.readouterr().out
    assert "realtime" in out and "pua" in out and ": on" in out
    assert cli.main(["get", "pua"]) == 0 and capsys.readouterr().out.strip() == "on"


def test_cli_set_success_noop_and_service_error(monkeypatch, capsys):
    monkeypatch.setattr(system, "is_admin", lambda: True)

    class Svc:
        def set(self, k, v):
            if v == "off":
                raise AuxyError("Tamper engeli")
            return type("R", (), {"key": k, "old": "on", "new": v, "changed": v != "on"})()

    monkeypatch.setattr(cli, "DefenderService", Svc)
    assert cli.main(["set", "pua", "audit"]) == 0 and "on -> audit" in capsys.readouterr().out
    assert cli.main(["set", "pua", "on"]) == 0 and "zaten on" in capsys.readouterr().out
    assert cli.main(["set", "pua", "off"]) == 1 and "Tamper engeli" in capsys.readouterr().err


def test_cli_set_writes_result_file_for_helper_mode(monkeypatch):
    import tempfile

    out = Path(tempfile.gettempdir()) / "auxy-result-cli-set.json"
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(cli, "DefenderService", lambda: type("S", (), {"set": lambda s, k, v: type(
        "R", (), {"key": k, "old": "on", "new": "off", "changed": True})()})())
    try:
        assert cli.main(["set", "pua", "off", "--result", str(out)]) == 0
        import json

        assert json.loads(out.read_text(encoding="utf-8"))["changed"] is True
    finally:
        out.unlink(missing_ok=True)


def test_cli_revert_paths(monkeypatch, capsys):
    monkeypatch.setattr(system, "is_admin", lambda: True)

    class Svc:
        def revert(self, key=None):
            if key == "cfa":
                raise AuxyError("kayit yok")
            return [type("R", (), {"key": "pua", "old": "off", "new": "on"})()] if key != "none" else []

    monkeypatch.setattr(cli, "DefenderService", Svc)
    assert cli.main(["revert"]) == 0 and "orijinale donuldu" in capsys.readouterr().out
    assert cli.main(["revert", "cfa"]) == 1 and "kayit yok" in capsys.readouterr().err


def test_cli_set_requires_admin_without_elevate_and_elevate_relaunches(monkeypatch, capsys):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    assert cli.main(["revert"]) == 3 and "Yonetici yetkisi gerekli" in capsys.readouterr().err
    calls = []
    monkeypatch.setattr(system, "relaunch_as_admin", lambda args, windowless=False: calls.append(args) or True)
    assert cli.main(["revert", "--elevate"]) == 0 and calls == [["revert", "--pause"]]
    monkeypatch.setattr(system, "relaunch_as_admin", lambda args, windowless=False: False)
    assert cli.main(["revert", "--elevate"]) == 1 and "UAC reddedildi" in capsys.readouterr().out


# ---------------- CLI: tarama / tehdit / imza ----------------
def test_cli_scan_kinds_and_errors(monkeypatch, capsys):
    runs = []

    class Mgr:
        def run(self, kind, path=None, quiet=False):
            runs.append((kind, path))
            return scan.ScanResult(kind, path or "", "2026-10-05T10:00:00", 61.0, scan.COMPLETED, 0, [])

    monkeypatch.setattr(scan, "ScanManager", Mgr)
    assert cli.main(["scan", "quick"]) == 0 and "tehdit bulunamadı" in capsys.readouterr().out
    assert cli.main(["scan", "full"]) == 0
    assert runs == [(scan.QUICK, None), (scan.FULL, None)]
    assert cli.main(["scan", "custom"]) == 2 and "yol ver" in capsys.readouterr().err
    monkeypatch.setattr(scan, "ScanManager", lambda: type("M", (), {"run": lambda s, k, p=None: (_ for _ in ()).throw(
        scan.ScanBusyError("mesgul"))})())
    assert cli.main(["scan", "quick"]) == 1 and "mesgul" in capsys.readouterr().err


def test_cli_scan_failed_status_returns_nonzero(monkeypatch):
    monkeypatch.setattr(scan, "ScanManager", lambda: type("M", (), {"run": lambda s, k, p=None: scan.ScanResult(
        k, "", "2026-10-05T10:00:00", 1.0, scan.FAILED, 2, [])})())
    assert cli.main(["scan", "quick"]) == 1


def test_cli_threats_and_signatures(monkeypatch, capsys):
    monkeypatch.setattr(threats, "read_detections", lambda: [])
    assert cli.main(["threats"]) == 0 and "Kayıtlı tehdit tespiti yok" in capsys.readouterr().out
    monkeypatch.setattr(threats, "read_detections", lambda: [
        threats.Detection(1, "Virus:X", "Yüksek", [r"C:\a.exe"], datetime(2026, 10, 5, 9, 30), True, False),
        threats.Detection(2, "Trojan:Y", "Orta", [], None, False, True)])
    assert cli.main(["threats"]) == 0
    out = capsys.readouterr().out
    assert "Virus:X" in out and "işlem uygulandı" in out and r"C:\a.exe" in out and "beklemede" in out
    monkeypatch.setattr(scan, "update_signatures", lambda: (True, "İmzalar güncel (sürüm 1.2)."))
    assert cli.main(["update-signatures"]) == 0 and "güncel" in capsys.readouterr().out
    monkeypatch.setattr(scan, "update_signatures", lambda: (False, "başarısız"))
    assert cli.main(["update-signatures"]) == 1


def test_cli_status_shows_tamper_note(monkeypatch, capsys):
    monkeypatch.setattr(defender, "read_status", lambda: fake_status(tamper=True))
    assert cli.main(["status"]) == 0 and "Tamper Protection acik" in capsys.readouterr().out


def test_cli_scan_cancel_requires_admin(monkeypatch, capsys):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    assert cli.main(["scan-cancel"]) == 3
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(actions, "cancel_scan", lambda: actions.ActionResult(True, "Tarama iptal edildi."))
    assert cli.main(["scan-cancel"]) == 0 and "iptal edildi" in capsys.readouterr().out


# ---------------- CLI: Windows guvenlik ----------------
def test_cli_winsec_set_validation_and_flow(monkeypatch, capsys):
    assert cli.main(["winsec-set", "yok", "on"]) == 2 and "geçersiz ayar/değer" in capsys.readouterr().err
    assert cli.main(["winsec-set", "fw_public", "belki"]) == 2
    monkeypatch.setattr(actions, "apply_winsec", lambda k, v: actions.ActionResult(True, "on → off", True))
    assert cli.main(["winsec-set", "fw_public", "off"]) == 0 and "on → off" in capsys.readouterr().out
    monkeypatch.setattr(actions, "apply_winsec", lambda k, v: actions.ActionResult(False, "engellendi"))
    assert cli.main(["winsec-set", "fw_public", "off"]) == 1 and "engellendi" in capsys.readouterr().err


def test_cli_winsec_revert(monkeypatch, capsys):
    from auxy.core import winsec

    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(winsec.WinSecService, "revert", lambda self, key=None: [
        winsec.WinSetResult("fw_public", "off", "on", True)])
    assert cli.main(["winsec-revert"]) == 0 and "fw_public" in capsys.readouterr().out
    monkeypatch.setattr(winsec.WinSecService, "revert", lambda self, key=None: [])
    assert cli.main(["winsec-revert"]) == 0 and "Geri alınacak değişiklik yok" in capsys.readouterr().out
    monkeypatch.setattr(winsec.WinSecService, "revert", lambda self, key=None: (_ for _ in ()).throw(AuxyError("yok")))
    assert cli.main(["winsec-revert", "hvci"]) == 1


def test_cli_exclusion_and_tpm(monkeypatch, capsys):
    data = {"path": [r"C:\proje"], "extension": ["log"], "process": []}
    monkeypatch.setattr(actions, "exclusion_op", lambda op, kind, value="": actions.ActionResult(True, "2 dışlama.", data=data))
    assert cli.main(["exclusion", "list", "path"]) == 0
    out = capsys.readouterr().out
    assert "[path] C:\\proje" in out and "[extension] log" in out
    monkeypatch.setattr(actions, "exclusion_op", lambda op, kind, value="": actions.ActionResult(True, "Eklendi.", True))
    assert cli.main(["exclusion", "add", "path", r"C:\x"]) == 0 and "Eklendi" in capsys.readouterr().out
    monkeypatch.setattr(actions, "exclusion_op", lambda op, kind, value="": (_ for _ in ()).throw(AuxyError("gecersiz")))
    assert cli.main(["exclusion", "add", "path", "C:\\"]) == 1
    monkeypatch.setattr(actions, "exclusion_op", lambda op, kind, value="": actions.ActionResult(False, "reddedildi"))
    assert cli.main(["exclusion", "remove", "path", r"C:\x"]) == 1
    monkeypatch.setattr(actions, "read_tpm", lambda: actions.ActionResult(True, "ok", data={"TpmPresent": True}))
    assert cli.main(["tpm-info"]) == 0 and "TpmPresent" in capsys.readouterr().out
    monkeypatch.setattr(actions, "read_tpm", lambda: actions.ActionResult(False, "yetki"))
    assert cli.main(["tpm-info"]) == 1


def test_cli_context_menu_and_autostart_status(monkeypatch, capsys):
    from auxy.core import autostart, contextmenu

    seen = []
    monkeypatch.setattr(contextmenu, "install", lambda: seen.append("i"))
    monkeypatch.setattr(contextmenu, "remove", lambda: seen.append("r"))
    monkeypatch.setattr(contextmenu, "is_installed", lambda: True)
    assert cli.main(["context-menu", "install"]) == 0 and cli.main(["context-menu", "remove"]) == 0
    assert cli.main(["context-menu", "status"]) == 0 and "Kurulu: evet" in capsys.readouterr().out
    assert seen == ["i", "r"]
    monkeypatch.setattr(autostart, "status", lambda: autostart.AutostartStatus(True, "0"))
    assert cli.main(["autostart", "status"]) == 0 and "Kurulu: evet" in capsys.readouterr().out
    monkeypatch.setattr(autostart, "status", lambda: autostart.AutostartStatus(False))
    assert cli.main(["autostart", "status"]) == 0 and "Kurulu: hayir" in capsys.readouterr().out


def test_cli_firewall_rule_and_vault_basic(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(actions, "firewall_op", lambda op, v="": actions.ActionResult(False, "yetki yok"))
    assert cli.main(["firewall-rule", "disable", "R1"]) == 1 and "yetki yok" in capsys.readouterr().err
    f = tmp_path / "a.exe"
    f.write_bytes(b"MZ" + b"1" * 30)
    assert cli.main(["vault", "add", str(f)]) == 0 and not f.exists()
    capsys.readouterr()  # "Kasaya alindi" ciktisini at; yalniz liste ciktisini oku
    assert cli.main(["vault", "list"]) == 0
    listed = capsys.readouterr().out
    item_id = [ln for ln in listed.splitlines() if "a.exe" in ln][0].split()[0]
    assert cli.main(["vault", "restore", item_id]) == 0 and f.exists()
    assert cli.main(["vault", "delete", "zzzzzzzz", "--yes"]) == 1  # olmayan id
    assert cli.main(["vault", "restore"]) == 2


def test_cli_vault_delete_requires_yes(tmp_path, capsys):
    f = tmp_path / "b.exe"
    f.write_bytes(b"MZ" + b"2" * 30)
    cli.main(["vault", "add", str(f)])
    capsys.readouterr()
    cli.main(["vault", "list"])
    item_id = capsys.readouterr().out.split()[0]
    assert cli.main(["vault", "delete", item_id]) == 2 and "--yes" in capsys.readouterr().err
    assert cli.main(["vault", "delete", item_id, "--yes"]) == 0


def test_cli_find_vault_item_ambiguity(tmp_path):
    from auxy.core.vault import Vault

    vault = Vault.default()
    ids = []
    for i in range(2):
        f = tmp_path / f"{i}.bin"
        f.write_bytes(bytes([i]) * 20)
        ids.append(vault.add(f).id)
    with pytest.raises(AuxyError, match="eşleşen 2 kayıt"):
        cli._find_vault_item(vault, "")  # bos onek: ikisi de eslesir
    assert cli._find_vault_item(vault, ids[0][:8]).id == ids[0]


# ---------------- system: UAC yardimci akisi (gercek ctypes, sahte ShellExecuteExW) ----------------
@pytest.fixture
def fake_shell(monkeypatch):
    """ShellExecuteExW'yi sahtele: gercek bir alt surec baslat ve onun handle'ini hProcess olarak ver (UAC penceresi YOK)."""
    state = {"proc": None, "params": None, "verb": None}
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    def make(code: int, sleep_s: float = 0.0, ok: bool = True):
        def fake(byref_obj):
            info = byref_obj._obj
            state["params"], state["verb"] = info.lpParameters, info.lpVerb
            if not ok:
                return 0
            state["proc"] = subprocess.Popen(
                [sys.executable, "-c", f"import time,sys; time.sleep({sleep_s}); sys.exit({code})"])
            info.hProcess = k32.OpenProcess(0x100000 | 0x1000, False, state["proc"].pid)  # SYNCHRONIZE|QUERY_LIMITED
            return 1

        monkeypatch.setattr(system.ctypes.windll.shell32, "ShellExecuteExW", fake, raising=False)

    state["make"] = make
    yield state
    if state["proc"] is not None:
        state["proc"].kill()


def test_run_elevated_and_wait_returns_exit_code_and_uses_runas(fake_shell):
    fake_shell["make"](code=7)
    assert system.run_elevated_and_wait(["set", "pua", "off", "--result", r"C:\t\x y.json"], timeout_s=20) == 7
    assert fake_shell["verb"] == "runas"
    assert "-m auxy set pua off --result" in fake_shell["params"] and '"C:\\t\\x y.json"' in fake_shell["params"]  # bosluklu yol tirnakli


def test_run_elevated_and_wait_uac_denied_and_timeout(fake_shell):
    fake_shell["make"](code=0, ok=False)
    assert system.run_elevated_and_wait(["x"], timeout_s=5) is None  # UAC reddedildi
    fake_shell["make"](code=0, sleep_s=5)
    assert system.run_elevated_and_wait(["x"], timeout_s=0.3) is None  # sure asimi


def test_python_exe_windowless_prefers_pythonw():
    assert system.python_exe(False) == sys.executable
    w = system.python_exe(True)
    assert w.lower().endswith("pythonw.exe") or w == sys.executable  # pythonw yoksa yorumlayiciya duser


def test_relaunch_as_admin_result_codes(monkeypatch):
    monkeypatch.setattr(system.ctypes.windll.shell32, "ShellExecuteW", lambda *a: 42, raising=False)
    assert system.relaunch_as_admin(["x"]) is True
    monkeypatch.setattr(system.ctypes.windll.shell32, "ShellExecuteW", lambda *a: 5, raising=False)  # ERROR_ACCESS_DENIED
    assert system.relaunch_as_admin(["x"], windowless=True) is False


def test_single_instance_and_focus_window(monkeypatch):
    name = "AuxyTestSingle" + str(id(object()))
    assert system.acquire_single_instance(name) is True
    assert system.acquire_single_instance(name) is False  # ayni sureclerde ikinci alinamaz
    assert system.focus_window("Var Olmayan Pencere Basligi 123") is False
    assert isinstance(system.is_agent_running(), bool)
