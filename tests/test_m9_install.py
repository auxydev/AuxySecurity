import os
import sys
import winreg
import zipfile
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy import __version__
from auxy.core import autostart, cleanup, contextmenu, install, system

TEST_KEY = r"Software\AuxyTestM9\Uninstall"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUXY_INSTANCE", "_m9inst")
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    for key in (TEST_KEY, r"Software\AuxyTestM9"):
        try:
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, key, winreg.KEY_WOW64_64KEY)
        except OSError:
            pass
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def make_payload(tmp_path, with_exes=True, extra=None) -> Path:
    z = tmp_path / "payload.zip"
    with zipfile.ZipFile(z, "w") as zf:
        if with_exes:
            zf.writestr("AuxySecurity.exe", b"MZ-gui")
            zf.writestr("auxy.exe", b"MZ-cli")
        zf.writestr("_internal/lib/x.dll", b"dll")
        zf.writestr("_internal/data/a.json", "{}")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return z


def opts(tmp_path, **kw) -> install.InstallOptions:
    return install.InstallOptions(
        dest=tmp_path / "Program Files" / "AuxySecurity", start_menu_path=tmp_path / "StartMenu",
        desktop_path=tmp_path / "Desktop", hive=winreg.HKEY_CURRENT_USER, reg_key=TEST_KEY, **kw)


@pytest.fixture
def no_side_effects(monkeypatch):
    """Gercek surec oldurme / gorev / sag tik / silme zamanlamasi YOK."""
    calls = {"stopped": [], "scheduled": [], "task": [], "ctx": []}
    monkeypatch.setattr(install, "stop_running_instances", lambda d: calls["stopped"].append(d) or [])
    monkeypatch.setattr(install, "schedule_delete", lambda d, delay_s=3: calls["scheduled"].append(d))
    monkeypatch.setattr(autostart, "install", lambda **k: calls["task"].append(("install", k)))
    monkeypatch.setattr(autostart, "remove", lambda: calls["task"].append("remove"))
    monkeypatch.setattr(autostart, "is_installed", lambda: bool(calls["task"]) and calls["task"][-1] != "remove")
    monkeypatch.setattr(contextmenu, "install", lambda **k: calls["ctx"].append(("install", k)))
    monkeypatch.setattr(contextmenu, "remove", lambda: calls["ctx"].append("remove"))
    monkeypatch.setattr(contextmenu, "is_installed", lambda: bool(calls["ctx"]) and calls["ctx"][-1] != "remove")
    from auxy.core import netservices

    monkeypatch.setattr(netservices, "read_service", lambda name=netservices.GDPI_SERVICE: netservices.ServiceInfo(False))
    monkeypatch.setattr(netservices, "remove_service", lambda *a, **k: netservices.NetResult(True, "Hizmet zaten yok."))
    # kayitli komut: son kurulumun exe'si (testte kurulum klasorunun icinde)
    monkeypatch.setattr(autostart, "registered_command", lambda: str(calls["task"][0][1].get("exe", "")) if calls["task"] else "")
    monkeypatch.setattr(contextmenu, "registered_command", lambda: str(calls["ctx"][0][1].get("exe", "")) if calls["ctx"] else "")
    return calls


# ---------------- dosyalar ----------------
def test_extract_payload_and_verify(tmp_path):
    z = make_payload(tmp_path)
    dest = tmp_path / "hedef"
    assert install.extract_payload(z, dest) == 4
    assert (dest / "_internal" / "lib" / "x.dll").read_bytes() == b"dll"
    install.verify_install(dest)
    assert install.installed_size_kb(dest) >= 0


def test_extract_payload_blocks_zip_slip(tmp_path):
    z = make_payload(tmp_path, extra={"../../kaçak.txt": b"x"})
    dest = tmp_path / "a" / "b" / "hedef"
    with pytest.raises(install.InstallError, match="zip-slip"):
        install.extract_payload(z, dest)
    assert not (tmp_path / "kaçak.txt").exists() and not (tmp_path / "a" / "kaçak.txt").exists()


def test_verify_install_detects_missing_exe(tmp_path):
    z = make_payload(tmp_path, with_exes=False)
    dest = tmp_path / "hedef"
    install.extract_payload(z, dest)
    with pytest.raises(install.InstallError, match="AuxySecurity.exe"):
        install.verify_install(dest)


# ---------------- kisayollar (gercek WScript.Shell COM) ----------------
def test_real_shortcuts_created_and_point_to_installed_exe(tmp_path):
    import win32com.client

    o = opts(tmp_path, desktop=True)
    o.dest.mkdir(parents=True)
    (o.dest / "AuxySecurity.exe").write_bytes(b"MZ")
    made = install.create_shortcuts(o)
    assert len(made) == 3 and all(p.exists() for p in made)
    sh = win32com.client.Dispatch("WScript.Shell")
    main = sh.CreateShortcut(str(tmp_path / "StartMenu" / "AuxySecurity.lnk"))
    agent = sh.CreateShortcut(str(tmp_path / "StartMenu" / "AuxySecurity tray ajanı.lnk"))
    assert Path(main.TargetPath) == o.dest / "AuxySecurity.exe" and main.Arguments == ""
    assert agent.Arguments == "agent" and Path(agent.WorkingDirectory) == o.dest
    install.remove_shortcuts(o)
    assert not (tmp_path / "StartMenu").exists() and not (tmp_path / "Desktop" / "AuxySecurity.lnk").exists()


# ---------------- Uygulamalar ve ozellikler kaydi (gercek kayit defteri, test alt anahtari) ----------------
def test_uninstall_registration_values_and_removal(tmp_path):
    o = opts(tmp_path)
    o.dest.mkdir(parents=True)
    (o.dest / "AuxySecurity.exe").write_bytes(b"MZ" * 500)
    install.register_uninstall(o)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
        get = lambda n: winreg.QueryValueEx(k, n)[0]  # noqa: E731
        assert get("DisplayName") == "AuxySecurity" and get("DisplayVersion") == __version__
        assert get("InstallLocation") == str(o.dest)
        assert get("UninstallString") == f'"{o.dest / "AuxySecurity.exe"}" uninstall'
        assert get("QuietUninstallString").endswith("uninstall --quiet")
        assert get("NoModify") == 1 and get("EstimatedSize") >= 0
    assert install.read_install_location(winreg.HKEY_CURRENT_USER, TEST_KEY) == o.dest
    install.unregister_uninstall(o)
    assert install.read_install_location(winreg.HKEY_CURRENT_USER, TEST_KEY) is None
    install.unregister_uninstall(o)  # yokken de sorun yok


# ---------------- tam kurulum / kaldirma akisi ----------------
def test_install_full_flow_with_all_options(tmp_path, no_side_effects):
    z = make_payload(tmp_path)
    o = opts(tmp_path, desktop=True, autostart=True, context_menu=True)
    log = []
    steps = install.install(z, o, log=log.append)
    assert (o.dest / "auxy.exe").exists() and (tmp_path / "StartMenu" / "AuxySecurity.lnk").exists()
    assert no_side_effects["stopped"] == [o.dest]  # once calisan ornekler kapatilir
    kind, kw = no_side_effects["task"][0]
    assert kw["exe"] == str(o.dest / "AuxySecurity.exe") and kw["arguments"] == "agent" and kw["workdir"] == str(o.dest)
    assert no_side_effects["ctx"][0][1]["exe"] == str(o.dest / "AuxySecurity.exe")  # KURULAN exe, installer'in kendisi degil
    assert any("başlangıç görevi" in s for s in steps) and any("sağ tık" in s for s in steps)
    assert len(log) >= 5
    assert install.read_install_location(winreg.HKEY_CURRENT_USER, TEST_KEY) == o.dest


def test_install_minimal_options_skip_optional_steps(tmp_path, no_side_effects):
    o = opts(tmp_path, start_menu=False)
    install.install(make_payload(tmp_path), o, log=lambda m: None)
    assert no_side_effects["task"] == [] and no_side_effects["ctx"] == []
    assert not (tmp_path / "StartMenu").exists()


def test_install_aborts_on_incomplete_payload(tmp_path, no_side_effects):
    o = opts(tmp_path)
    with pytest.raises(install.InstallError):
        install.install(make_payload(tmp_path, with_exes=False), o, log=lambda m: None)
    assert install.read_install_location(winreg.HKEY_CURRENT_USER, TEST_KEY) is None  # kayit yazilmadi


def test_upgrade_over_existing_install_keeps_working(tmp_path, no_side_effects):
    o = opts(tmp_path)
    install.install(make_payload(tmp_path), o, log=lambda m: None)
    (o.dest / "eski-artik-dosya.txt").write_text("x")
    install.install(make_payload(tmp_path), o, log=lambda m: None)  # ayni hedefe yeniden kurulum
    install.verify_install(o.dest)
    assert install.read_install_location(winreg.HKEY_CURRENT_USER, TEST_KEY) == o.dest


def test_uninstall_removes_system_entries_keeps_data_and_defers_file_deletion(tmp_path, no_side_effects):
    from auxy.core import paths

    o = opts(tmp_path, autostart=True, context_menu=True)
    install.install(make_payload(tmp_path), o, log=lambda m: None)
    (paths.home() / "vault").mkdir(parents=True)
    (paths.home() / "vault" / "vault.db").write_bytes(b"db")
    steps = install.uninstall(o, log=lambda m: None)
    assert "remove" in no_side_effects["task"] and "remove" in no_side_effects["ctx"]
    assert not (tmp_path / "StartMenu").exists() and install.read_install_location(winreg.HKEY_CURRENT_USER, TEST_KEY) is None
    assert (paths.home() / "vault" / "vault.db").exists()  # VERI KORUNDU
    assert no_side_effects["scheduled"] == [o.dest] and any("veri korundu" in s for s in steps)
    assert o.dest.exists()  # dosyalar cikistan SONRA silinir (calisan exe kendini silemez)


def test_schedule_delete_passes_one_string_not_a_list(tmp_path, monkeypatch):
    # liste verilirse subprocess tirnaklari kacirir, cmd bozuk okur ve klasor silinmez (gercek testte bulundu)
    seen = []
    monkeypatch.setattr(install.subprocess, "Popen", lambda *a, **k: seen.append(a[0]))
    install.schedule_delete(tmp_path / "AuxySecurity")
    assert isinstance(seen[0], str) and seen[0].startswith("cmd.exe /d /c ") and "rmdir /s /q" in seen[0]


def test_stop_running_instances_excludes_own_process(monkeypatch):
    # kaldirici kurulu exe'den calisir: taskkill kendini oldurmemeli (gercek testte exit 1 ile bulundu)
    cmds = []
    monkeypatch.setattr(install.subprocess, "run", lambda c, **k: cmds.append(c) or type("R", (), {"returncode": 1})())
    install.stop_running_instances(Path("x"))
    assert cmds and all(f"PID ne {os.getpid()}" in c for c in cmds)


def test_uninstall_leaves_entries_pointing_to_other_installs(tmp_path, no_side_effects, monkeypatch):
    o = opts(tmp_path)
    install.install(make_payload(tmp_path), o, log=lambda m: None)
    monkeypatch.setattr(autostart, "is_installed", lambda: True)
    monkeypatch.setattr(contextmenu, "is_installed", lambda: True)
    monkeypatch.setattr(autostart, "registered_command", lambda: r"C:\dev\.venv\Scripts\pythonw.exe")
    monkeypatch.setattr(contextmenu, "registered_command", lambda: r"C:\dev\.venv\Scripts\pythonw.exe -m auxy")
    steps = install.uninstall(o, log=lambda m: None)
    assert "remove" not in no_side_effects["task"] and "remove" not in no_side_effects["ctx"]
    assert sum("dokunulmadı" in s for s in steps) == 2


def test_uninstall_remove_data_refuses_when_vault_has_items(tmp_path, no_side_effects, monkeypatch):
    from auxy.core import paths

    monkeypatch.setattr(system, "is_agent_running", lambda: False)
    o = opts(tmp_path)
    install.install(make_payload(tmp_path), o, log=lambda m: None)
    import sqlite3

    (paths.home() / "vault").mkdir(parents=True)
    db = sqlite3.connect(paths.home() / "vault" / "vault.db")
    db.execute("CREATE TABLE items (id TEXT)")
    db.execute("INSERT INTO items VALUES ('1')")
    db.commit()
    db.close()
    steps = install.uninstall(o, remove_data=True, log=lambda m: None)
    assert any("kasada dosya" in s and "KALICI" in s for s in steps)
    assert (paths.home() / "vault" / "vault.db").exists()


def test_acl_of_program_files_style_dest_is_not_writable_by_standard_users_documented():
    """Gercek Program Files'in varsayilan ACL'i yalnizca yonetici/TrustedInstaller yazar; kurulum bunu MIRAS alir (T1)."""
    pf = Path(os.environ["ProgramFiles"])
    import subprocess

    out = subprocess.run(["icacls", str(pf)], capture_output=True, text=True, errors="replace",
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    users_line = [ln for ln in out.splitlines() if "Users" in ln or "Kullanıcılar" in ln]
    assert users_line and all("(F)" not in ln and "(M)" not in ln and "(W)" not in ln for ln in users_line)  # yalniz okuma/yurutme


# ---------------- CLI uninstall ----------------
def test_cli_uninstall_only_in_installed_version(capsys):
    assert cli.main(["uninstall", "--quiet"]) == 2 and "yalnızca kurulu" in capsys.readouterr().err


def test_cli_uninstall_relaunches_as_admin_when_needed(tmp_path, monkeypatch):
    d = tmp_path / "AuxySecurity"
    d.mkdir()
    (d / "AuxySecurity.exe").write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(d / "AuxySecurity.exe"))
    monkeypatch.setattr(system, "is_admin", lambda: False)
    seen = []
    monkeypatch.setattr(system, "relaunch_as_admin", lambda a, windowless=False: seen.append(a) or True)
    assert cli.main(["uninstall", "--quiet", "--remove-data"]) == 0
    assert seen == [["uninstall", "--quiet", "--remove-data"]]


def test_cli_uninstall_runs_steps_when_admin_and_quiet(tmp_path, monkeypatch, capsys):
    d = tmp_path / "AuxySecurity"
    d.mkdir()
    (d / "AuxySecurity.exe").write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(d / "AuxySecurity.exe"))
    monkeypatch.setattr(system, "is_admin", lambda: True)
    got = {}
    monkeypatch.setattr(install, "uninstall", lambda o, **k: got.update(opts=o, k=k) or ["adım bir", "adım iki"])
    assert cli.main(["uninstall", "--quiet"]) == 0
    assert got["opts"].dest == d.resolve() and got["k"]["remove_data"] is False
    assert "adım bir" in capsys.readouterr().out
    monkeypatch.setattr(install, "uninstall", lambda o, **k: (_ for _ in ()).throw(RuntimeError("kilitli")))
    assert cli.main(["uninstall", "--quiet"]) == 1
