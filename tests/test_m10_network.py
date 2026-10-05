"""Ag guvenligi: GoodbyeDPI hizmeti + Cloudflare WARP + sayfa + kurucu entegrasyonu.

Gercek hizmetlere/WARP'a DOKUNULMAZ: hizmet kaydi ve warp-cli enjekte edilen sahte nesnelerle test edilir.
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import actions, doctor, install, netservices as ns, system
from auxy.core.actions import ActionResult
from auxy.core.service import AuxyError

REAL_SLEEP = time.sleep


def pump(a, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if cond():
            return True
        REAL_SLEEP(0.05)
    return False


# ---------------- saf yardimcilar ----------------
def test_split_command_line_handles_quotes_and_spaces():
    assert ns.split_command_line('"C:\\Program Files\\A B\\g.exe" -5 --set-ttl 5') == ("C:\\Program Files\\A B\\g.exe", "-5 --set-ttl 5")
    assert ns.split_command_line("C:\\x\\g.exe -5 --a b") == ("C:\\x\\g.exe", "-5 --a b")
    assert ns.split_command_line('"C:\\x\\g.exe"') == ("C:\\x\\g.exe", "")
    assert ns.split_command_line("") == ("", "")


def test_validate_args_accepts_real_presets_and_rejects_injection():
    assert ns.validate_args(ns.GDPI_DEFAULT_ARGS) == ns.GDPI_DEFAULT_ARGS
    assert ns.validate_args("  -5   --set-ttl   5 ") == "-5 --set-ttl 5"
    for bad in ("-5 & calc", "-5 ; del x", '-5 "x"', "-5 | more", "%PATH%"):
        with pytest.raises(AuxyError):
            ns.validate_args(bad)


def test_trusted_location_program_files_yes_user_folders_no(monkeypatch, tmp_path):
    pf = tmp_path / "Program Files"
    desktop = tmp_path / "Users" / "k" / "Desktop"
    for d in (pf / "A", desktop):
        d.mkdir(parents=True)
    monkeypatch.setenv("ProgramFiles", str(pf))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    monkeypatch.setattr(system, "install_dir", lambda: None)
    assert ns.trusted_location(str(pf / "A" / "g.exe"))
    assert not ns.trusted_location(str(desktop / "goodbyedpi" / "g.exe"))
    assert not ns.trusted_location("")
    assert ns.trusted_location(str(desktop / "g.exe"), extra_roots=(desktop,))  # acik izin (yalnizca testlerde)


def test_missing_service_is_reported_not_installed_without_admin():
    info = ns.read_service("AuxyNoSuchService_xyz")
    assert info.installed is False and info.state == "missing"


def test_normalize_mode_and_protocol():
    assert ns.normalize_mode("doh") == "doh" and ns.normalize_mode("warp_doh") == "warp+doh"
    assert ns.normalize_mode("tunnel_only") == "tunnel_only" and ns.normalize_mode("bilinmeyen") == "bilinmeyen"
    assert ns.normalize_protocol("masque") == "MASQUE" and ns.normalize_protocol("wireguard") == "WireGuard"


def test_arch_exe_and_untrusted_install_refused(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    (tools / "x86_64").mkdir(parents=True)
    (tools / "x86_64" / "goodbyedpi.exe").write_bytes(b"MZ")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    assert ns.arch_exe(tools) == tools / "x86_64" / "goodbyedpi.exe"
    monkeypatch.setattr(system, "install_dir", lambda: None)
    with pytest.raises(AuxyError, match="yönetici-yazılabilir"):  # tmp: kullanici yazabilir -> SISTEM hizmeti olarak kaydedilmez
        ns.install_service(tools)
    with pytest.raises(AuxyError, match="bulunamadı"):
        ns.arch_exe(tmp_path / "bos")


# ---------------- WARP (sahte warp-cli) ----------------
class FakeWarp:
    def __init__(self, status="Connected", mode="doh", proto="masque", fail=False):
        self.calls = []
        self.status, self.mode, self.proto, self.fail = status, mode, proto, fail

    def __call__(self, cmd, **kw):
        args = cmd[2:]  # [exe, --accept-tos, ...]
        self.calls.append(args)
        if self.fail:
            return subprocess.CompletedProcess(cmd, 1, "", "Error: permission denied")
        if args[:2] == ["-j", "status"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"status": self.status, "reason": "NetworkHealthy"}), "")
        if args[:2] == ["-j", "settings"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(
                {"settings": {"operation_mode": self.mode, "warp_tunnel_protocol": self.proto}}), "")
        return subprocess.CompletedProcess(cmd, 0, "Success\n", "")


@pytest.fixture
def warp(monkeypatch, tmp_path):
    exe = tmp_path / "warp-cli.exe"
    exe.write_bytes(b"MZ")
    fake = FakeWarp()
    monkeypatch.setattr(ns, "warp_cli_path", lambda: exe)
    monkeypatch.setattr(ns.subprocess, "run", fake)
    monkeypatch.setattr(ns, "read_service", lambda name=ns.GDPI_SERVICE: ns.ServiceInfo(True, "running", "auto", "x.exe", ""))
    return fake


def test_read_warp_parses_status_mode_protocol(warp):
    w = ns.read_warp()
    assert (w.installed, w.status, w.mode, w.protocol, w.service_running) == (True, "Connected", "doh", "MASQUE", True)
    warp.mode, warp.proto = "warp_doh", "wireguard"
    w = ns.read_warp()
    assert w.mode == "warp+doh" and w.protocol == "WireGuard"


def test_read_warp_not_installed(monkeypatch):
    monkeypatch.setattr(ns, "warp_cli_path", lambda: None)
    w = ns.read_warp()
    assert w.installed is False and w.status == "missing"


def test_warp_ops_build_exact_commands_and_validate(warp):
    assert ns.warp_op("connect").ok and warp.calls[-1] == ["connect"]
    assert ns.warp_op("disconnect").ok and warp.calls[-1] == ["disconnect"]
    assert ns.warp_op("protocol", "WireGuard").ok and warp.calls[-1] == ["tunnel", "protocol", "set", "WireGuard"]
    assert ns.warp_op("mode", "warp+doh").ok and warp.calls[-1] == ["mode", "warp+doh"]
    n = len(warp.calls)
    for op, val in (("protocol", "OpenVPN"), ("mode", "x; calc"), ("bilinmeyen", "")):
        with pytest.raises(AuxyError):
            ns.warp_op(op, val)
    assert len(warp.calls) == n  # gecersiz girdi warp-cli'ye HIC gitmez


def test_warp_op_reports_failure_and_timeout(warp, monkeypatch):
    warp.fail = True
    r = ns.warp_op("connect")
    assert not r.ok and "permission denied" in r.message or "hata" in r.message.lower()

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("warp-cli", 30)

    monkeypatch.setattr(ns.subprocess, "run", boom)
    assert "zaman aşımı" in ns.warp_op("connect").message


def test_install_warp_skips_when_present_and_handles_missing_winget(monkeypatch):
    monkeypatch.setattr(ns, "warp_cli_path", lambda: Path("x"))
    assert ns.install_warp().message == "WARP zaten kurulu."
    monkeypatch.setattr(ns, "warp_cli_path", lambda: None)

    def nowinget(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(ns.subprocess, "run", nowinget)
    r = ns.install_warp()
    assert not r.ok and "winget" in r.message


def test_install_warp_uses_official_winget_id_silently(monkeypatch):
    seen, state = [], {"installed": False}

    def run(cmd, **k):
        seen.append(cmd)
        state["installed"] = True
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(ns, "warp_cli_path", lambda: Path("x") if state["installed"] else None)
    monkeypatch.setattr(ns.subprocess, "run", run)
    r = ns.install_warp()
    assert r.ok and r.changed
    assert seen[0][:4] == ["winget", "install", "--id", "Cloudflare.Warp"] and "--silent" in seen[0] and "-e" in seen[0]


# ---------------- eylem katmani ----------------
def test_net_op_routing_warp_direct_gdpi_elevated(monkeypatch):
    direct, elevated = [], []
    monkeypatch.setattr(actions, "run_net_op", lambda op, value="": direct.append((op, value)) or ActionResult(True, "ok"))
    monkeypatch.setattr(actions, "run_elevated", lambda args, *a, **k: elevated.append(args) or ActionResult(True, "uac"))
    monkeypatch.setattr(system, "is_admin", lambda: False)
    actions.net_op("warp-connect")
    actions.net_op("warp-mode", "doh")
    actions.net_op("gdpi-start")
    actions.net_op("gdpi-install")
    assert direct == [("warp-connect", ""), ("warp-mode", "doh")]      # WARP: UAC yok
    assert elevated == [["netsvc", "gdpi-start"], ["netsvc", "gdpi-install"]]  # GoodbyeDPI: UAC
    monkeypatch.setattr(system, "is_admin", lambda: True)
    actions.net_op("gdpi-stop")
    assert direct[-1] == ("gdpi-stop", "") and len(elevated) == 2
    assert not actions.net_op("rm -rf").ok


def test_run_net_op_dispatches_to_core(monkeypatch):
    calls = []
    monkeypatch.setattr(ns, "service_control", lambda op, *a, **k: calls.append(("ctl", op)) or ns.NetResult(True, "ok", True))
    monkeypatch.setattr(ns, "set_start_type", lambda k, *a, **kw: calls.append(("start", k)) or ns.NetResult(True, "ok"))
    monkeypatch.setattr(ns, "remove_service", lambda *a, **k: calls.append(("rm",)) or ns.NetResult(True, "ok"))
    monkeypatch.setattr(ns, "bundled_tools_dir", lambda: None)
    for op in ("gdpi-start", "gdpi-stop", "gdpi-auto", "gdpi-manual", "gdpi-remove"):
        assert actions.run_net_op(op).ok
    assert calls == [("ctl", "start"), ("ctl", "stop"), ("start", "auto"), ("start", "manual"), ("rm",)]
    r = actions.run_net_op("gdpi-install")  # paketli kopya yok (gelistirme surumu)
    assert not r.ok and "Paketlenmiş" in r.message


def test_netsvc_is_allowed_for_elevated_helper_and_cli_status(monkeypatch, capsys):
    assert "netsvc" in cli.ELEVATED_ALLOWED
    monkeypatch.setattr(ns, "read_service", lambda name=ns.GDPI_SERVICE: ns.ServiceInfo(True, "running", "auto", r"C:\x\g.exe", "-5"))
    monkeypatch.setattr(ns, "trusted_location", lambda p, **k: False)
    monkeypatch.setattr(ns, "read_warp", lambda: ns.WarpInfo(True, "Connected", "NetworkHealthy", "doh", "MASQUE"))
    assert cli.main(["netsvc", "status"]) == 0
    out = capsys.readouterr().out
    assert "running" in out and "UYARI" in out and "Connected" in out and "MASQUE" in out


# ---------------- kurucu / kaldirici entegrasyonu ----------------
def _fake_ns(monkeypatch, bundle_exists=True):
    calls = {"svc": [], "warp": 0, "remove": []}
    monkeypatch.setattr(ns, "install_service", lambda tools, *a, **k: calls["svc"].append(tools) or ns.NetResult(True, "kaydedildi", True))
    monkeypatch.setattr(ns, "install_warp", lambda *a, **k: calls.__setitem__("warp", calls["warp"] + 1) or ns.NetResult(True, "WARP kuruldu."))
    monkeypatch.setattr(ns, "remove_service", lambda name=ns.GDPI_SERVICE, only_under=None: calls["remove"].append(only_under) or ns.NetResult(True, "kaldırıldı"))
    return calls


def test_installer_registers_bundled_gdpi_and_installs_warp(tmp_path, monkeypatch):
    calls = _fake_ns(monkeypatch)
    dest = tmp_path / "AuxySecurity"
    (dest / "tools" / "goodbyedpi" / "x86_64").mkdir(parents=True)
    (dest / "tools" / "goodbyedpi" / "x86_64" / "goodbyedpi.exe").write_bytes(b"MZ")
    steps = install.install_network_tools(install.InstallOptions(dest=dest, gdpi=True, warp=True), log=lambda m: None)
    assert calls["svc"] == [dest / "tools" / "goodbyedpi"] and calls["warp"] == 1
    assert any("GoodbyeDPI: kaydedildi" in s for s in steps) and any("WARP kuruldu" in s for s in steps)


def test_installer_skips_missing_bundle_and_never_fails_install(tmp_path, monkeypatch):
    calls = _fake_ns(monkeypatch)
    steps = install.install_network_tools(install.InstallOptions(dest=tmp_path / "yok", gdpi=True, warp=False), log=lambda m: None)
    assert calls["svc"] == [] and calls["warp"] == 0 and "atlandı" in steps[0]
    monkeypatch.setattr(ns, "install_warp", lambda: (_ for _ in ()).throw(RuntimeError("internet yok")))
    steps = install.install_network_tools(install.InstallOptions(dest=tmp_path / "yok", gdpi=False, warp=True), log=lambda m: None)
    assert "WARP kurulamadı: internet yok" in steps[0]  # istisna kurulumu bozmaz
    assert install.install_network_tools(install.InstallOptions(dest=tmp_path), log=lambda m: None) == []  # varsayilan: kapali


def test_uninstall_removes_only_services_under_this_install(tmp_path, monkeypatch):
    calls = _fake_ns(monkeypatch)
    monkeypatch.setattr(install, "stop_running_instances", lambda d: [])
    monkeypatch.setattr(install, "schedule_delete", lambda d, delay_s=3: None)
    from auxy.core import autostart, contextmenu

    monkeypatch.setattr(autostart, "is_installed", lambda: False)
    monkeypatch.setattr(contextmenu, "is_installed", lambda: False)
    o = install.InstallOptions(dest=tmp_path / "AuxySecurity", start_menu_path=tmp_path / "sm", desktop_path=tmp_path / "dk",
                               hive=__import__("winreg").HKEY_CURRENT_USER, reg_key=r"Software\AuxyTestM10")
    steps = install.uninstall(o, log=lambda m: None)
    assert calls["remove"] == [o.dest] and any(s.startswith("GoodbyeDPI:") for s in steps)  # kullanicinin baska konumdaki hizmeti korunur


def test_upgrade_stops_and_restarts_our_running_gdpi(tmp_path, monkeypatch):
    dest = tmp_path / "AuxySecurity"
    exe = dest / "tools" / "goodbyedpi" / "x86_64" / "goodbyedpi.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    ctl = []
    monkeypatch.setattr(ns, "read_service", lambda name=ns.GDPI_SERVICE: ns.ServiceInfo(True, "running", "auto", str(exe), "-5"))
    monkeypatch.setattr(ns, "service_control", lambda op, *a, **k: ctl.append(op) or ns.NetResult(True, "ok"))
    assert install._stop_our_gdpi(dest) is True and ctl == ["stop"]
    assert install._restart_gdpi() == "GoodbyeDPI yeniden başlatıldı" and ctl == ["stop", "start"]
    ctl.clear()
    # baska konumdaki (kullanicinin) hizmet: dokunma
    monkeypatch.setattr(ns, "read_service", lambda name=ns.GDPI_SERVICE: ns.ServiceInfo(True, "running", "auto", r"D:\baska\g.exe", ""))
    assert install._stop_our_gdpi(dest) is False and ctl == []


def test_setup_entry_flags_default_on_and_can_be_disabled():
    import importlib.util

    spec = importlib.util.spec_from_file_location("setup_entry", Path(__file__).parents[1] / "packaging" / "setup_entry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    on = mod.parse(["/S"])
    assert on["gdpi"] and on["warp"]
    off = mod.parse(["/S", "/NOGDPI", "/NOWARP"])
    assert not off["gdpi"] and not off["warp"]
    io = mod.build_options(off)
    assert io.gdpi is False and io.warp is False


# ---------------- doctor ----------------
def test_doctor_flags_gdpi_in_user_writable_folder(monkeypatch):
    monkeypatch.setattr(ns, "read_service", lambda name=ns.GDPI_SERVICE: ns.ServiceInfo(True, "stopped", "auto", r"C:\Users\x\Desktop\g.exe", ""))
    monkeypatch.setattr(ns, "trusted_location", lambda p, **k: False)
    c = doctor.check_network_tools()
    assert c.status == doctor.WARN and "yetki yükseltme" in c.detail
    monkeypatch.setattr(ns, "trusted_location", lambda p, **k: True)
    assert doctor.check_network_tools().status == doctor.OK
    monkeypatch.setattr(ns, "read_service", lambda name=ns.GDPI_SERVICE: ns.ServiceInfo(False, "missing"))
    assert doctor.check_network_tools().status == doctor.INFO


# ---------------- sayfa ----------------
@pytest.fixture
def npage(app, monkeypatch):
    from auxy.gui import network_page

    page = app.pages["network"]
    ops, answers = [], {"yes": True}
    monkeypatch.setattr(actions, "net_op", lambda op, value="": ops.append((op, value)) or ActionResult(True, f"{op} tamam", True))
    monkeypatch.setattr(network_page.messagebox, "askyesno", lambda *a, **k: answers["yes"])
    monkeypatch.setattr(page, "refresh", lambda: None)
    monkeypatch.setattr(ns, "trusted_location", lambda p, **k: p.startswith(r"C:\Program Files"))
    page.ops, page.answers = ops, answers
    return page


GOOD_EXE = r"C:\Program Files\AuxySecurity\tools\goodbyedpi\x86_64\goodbyedpi.exe"


def test_page_shows_gdpi_states_and_button_enablement(npage):
    npage._show_gdpi((ns.ServiceInfo(True, "running", "auto", GOOD_EXE, "-5"), None), None)
    assert "Çalışıyor" in npage.gdpi_state.cget("text")
    assert str(npage.gdpi_start_btn.cget("state")) == "disabled" and str(npage.gdpi_stop_btn.cget("state")) == "normal"
    assert npage.gdpi_auto.get() == 1 and npage.gdpi_warn.cget("text") == ""
    npage._show_gdpi((ns.ServiceInfo(True, "stopped", "manual", GOOD_EXE, "-5"), None), None)
    assert "Durduruldu" in npage.gdpi_state.cget("text")
    assert str(npage.gdpi_start_btn.cget("state")) == "normal" and str(npage.gdpi_stop_btn.cget("state")) == "disabled"
    assert npage.gdpi_auto.get() == 0
    npage._show_gdpi((ns.ServiceInfo(False, "missing"), None), None)
    assert "Kurulu değil" in npage.gdpi_state.cget("text") and str(npage.gdpi_start_btn.cget("state")) == "disabled"


def test_page_warns_about_untrusted_service_and_offers_fix_only_when_bundled(npage, tmp_path):
    bad = ns.ServiceInfo(True, "stopped", "auto", r"C:\Users\x\Desktop\g.exe", "-5")
    npage._show_gdpi((bad, None), None)
    assert "SİSTEM yetkisiyle" in npage.gdpi_warn.cget("text") and not npage.gdpi_fix_btn.winfo_manager()  # paket yok: duzeltme yok
    npage._show_gdpi((bad, tmp_path), None)
    assert npage.gdpi_fix_btn.winfo_manager() == "grid" and "Güvenli konuma" in npage.gdpi_fix_btn.cget("text")


def test_page_gdpi_actions_confirm_stop_and_run_ops(app, npage):
    npage.answers["yes"] = False
    npage.gdpi_op("gdpi-stop")
    app.update()
    assert npage.ops == []  # onay yok: durdurulmaz
    npage.answers["yes"] = True
    npage.gdpi_op("gdpi-stop")
    npage.gdpi_op("gdpi-start")
    assert pump(app, lambda: len(npage.ops) == 2) and npage.ops == [("gdpi-stop", ""), ("gdpi-start", "")]
    npage.gdpi_auto.select()
    npage._toggle_gdpi_auto()
    npage.gdpi_auto.deselect()
    npage._toggle_gdpi_auto()
    assert pump(app, lambda: len(npage.ops) == 4) and [o[0] for o in npage.ops[2:]] == ["gdpi-auto", "gdpi-manual"]


def test_page_shows_warp_status_and_selectors(npage):
    npage._show_warp(ns.WarpInfo(True, "Connected", "NetworkHealthy", "warp+doh", "WireGuard", True), None)
    assert "Bağlı" in npage.warp_state.cget("text") and "çalışıyor" in npage.warp_detail.cget("text")
    assert npage.proto_menu.get().startswith("WireGuard") and npage.mode_menu.get().startswith("WARP + DNS (DoH)")
    assert str(npage.warp_on_btn.cget("state")) == "disabled" and str(npage.warp_off_btn.cget("state")) == "normal"
    npage._show_warp(ns.WarpInfo(True, "Disconnected", "", "doh", "MASQUE", False), None)
    assert str(npage.warp_on_btn.cget("state")) == "normal" and "DURDURULMUŞ" in npage.warp_detail.cget("text")
    npage._show_warp(ns.WarpInfo(False), None)
    assert "Kurulu değil" in npage.warp_state.cget("text") and npage.warp_install_btn.winfo_manager() == "pack"
    assert str(npage.proto_menu.cget("state")) == "disabled"
    npage._show_warp(ns.WarpInfo(True, "Connected", "", "doh", "MASQUE", True), None)
    assert not npage.warp_install_btn.winfo_manager()


def test_page_warp_protocol_and_mode_change_need_confirmation(app, npage):
    npage.warp = ns.WarpInfo(True, "Connected", "", "doh", "MASQUE", True)
    npage.answers["yes"] = False
    npage._set_protocol(ns.WARP_PROTOCOLS["WireGuard"])
    npage._set_mode(ns.WARP_MODES["warp"])
    app.update()
    assert npage.ops == []
    npage.answers["yes"] = True
    npage._set_protocol(ns.WARP_PROTOCOLS["MASQUE"])  # zaten MASQUE: islem yok
    npage._set_protocol(ns.WARP_PROTOCOLS["WireGuard"])
    npage._set_mode(ns.WARP_MODES["warp"])
    npage.warp_op("warp-connect")
    assert pump(app, lambda: len(npage.ops) == 3)
    assert sorted(npage.ops) == sorted([("warp-protocol", "WireGuard"), ("warp-mode", "warp"), ("warp-connect", "")])


def test_nav_has_network_page_after_security(app):
    from auxy.gui import app as gui

    keys = [k for k, _ in gui.NAV]
    assert keys.index("network") == keys.index("security") + 1
    assert "network" in app.pages and dict(gui.NAV)["network"] == "Ağ güvenliği"


def test_warp_messages_are_short_turkish_not_raw_cli_output(warp):
    warp.fail = False
    assert ns.warp_op("disconnect").message == "WARP bağlantısı kesildi."
    assert ns.warp_op("protocol", "MASQUE").message == "Protokol MASQUE olarak ayarlandı."
    warp.fail = True
    long_err = "x" * 500 + "\nikinci satir\n" * 20
    warp_fail = ns._short(long_err)
    assert len(warp_fail) <= 140 and "\n" not in warp_fail and ns._short("\n\n  \n") == ""


def test_page_polls_warp_until_connected(app, npage, monkeypatch):
    from auxy.gui import network_page

    monkeypatch.setattr(network_page, "WARP_POLL_MS", 20)
    states = iter(["Connecting", "Connecting", "Connected", "Connected"])
    last = {"s": "Connecting"}

    def read():
        last["s"] = next(states, "Connected")
        return ns.WarpInfo(True, last["s"], "", "doh", "MASQUE", True)

    monkeypatch.setattr(ns, "read_warp", read)
    npage.warp_op("warp-connect")
    assert pump(app, lambda: "WARP bağlı." in npage.message.cget("text"), timeout=8)
    assert "Bağlı" in npage.warp_state.cget("text")


def test_page_gives_up_polling_with_clear_message(app, npage, monkeypatch):
    from auxy.gui import network_page

    monkeypatch.setattr(network_page, "WARP_POLL_MS", 10)
    monkeypatch.setattr(network_page, "WARP_POLL_MAX", 2)
    monkeypatch.setattr(ns, "read_warp", lambda: ns.WarpInfo(True, "Connecting", "", "doh", "MASQUE", True))
    npage._poll_warp("Connected", 2)
    assert pump(app, lambda: "hâlâ" in npage.message.cget("text"), timeout=5)


def test_theme_applied_and_assets_render(app):
    import customtkinter as ctk

    from auxy.agent.icon import make_banner_icon
    from auxy.gui import theme
    from auxy.gui import viewmodel as vm

    assert ctk.ThemeManager.theme["CTkFont"]["family"] == "Segoe UI"
    assert ctk.ThemeManager.theme["CTkFrame"]["corner_radius"] == 14
    for lvl in (vm.OK, vm.WARN, vm.CRIT, None):
        assert make_banner_icon(lvl, 64).size == (64, 64)
    assert theme.logo_image(32) is not None and theme.status_image(vm.OK) is not None
    assert theme.icon("nope") is None
    # kenar cubugu: etkin sayfa vurgulanir
    app.show("network")
    assert app.nav_buttons["network"].cget("fg_color") == theme.ACCENT
    assert app.nav_buttons["scan"].cget("fg_color") == "transparent"
    app.show("dashboard")
