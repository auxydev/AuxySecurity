import json
import tempfile
import time
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import actions, backup, system
from auxy.core import firewall as fw
from auxy.core.actions import ActionResult

REAL_SLEEP = time.sleep


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


class FakeFw:
    """PowerShell taklidi: kural deposu + degisiklik komutlari. Ortam degiskenleriyle gelen degerleri kaydeder."""

    def __init__(self, apply=True):
        self.rules = {  # ad -> (gorunen ad, program, etkin)
            "CoreNet-DHCP-In": ["Çekirdek Ağ - DHCP", r"%SystemRoot%\system32\svchost.exe", True],
            "WFDPRINT-SPOOL-In": ["Wi-Fi Direct Biriktirici", r"%SystemRoot%\system32\spoolsv.exe", True],
            "{GUID-1}": ["Teams", r"C:\Program Files\Teams\teams.exe", True],
        }
        self.blocks = {}  # ad -> (gorunen ad, program)
        self.apply = apply
        self.commands = []  # (komut, env)

    def __call__(self, command, env=None):
        env = env or {}
        self.commands.append((command, dict(env)))
        arg = env.get("AUXY_ARG", "")
        if command.startswith("$all = "):
            if "Get-NetFirewallRule -Enabled True" in command:
                data = [{"Name": n, "DisplayName": v[0], "Profile": "Any", "Program": v[1], "Group": ""}
                        for n, v in self.rules.items() if v[2]]
            else:  # AuxySecurity-*
                data = [{"Name": n, "DisplayName": v[0], "Profile": "Any", "Program": v[1], "Group": ""}
                        for n, v in self.blocks.items()]
            return 0, json.dumps(data), ""
        if command.startswith("Set-NetFirewallRule"):
            if self.apply:
                self.rules[arg][2] = command.endswith("True")
            return 0, "", ""
        if command.startswith("New-NetFirewallRule"):
            if self.apply:
                self.blocks[env["AUXY_NAME"]] = (env["AUXY_DISP"], arg)
            return 0, "", ""
        if command.startswith("Remove-NetFirewallRule"):
            if self.apply:
                self.blocks.pop(arg, None)
            return 0, "", ""
        return 1, "", "bilinmeyen komut"


# ---------------- listeleme ----------------
def test_list_rules_and_parse_variants():
    f = FakeFw()
    rules = fw.list_rules(f)
    assert [r.name for r in rules] == ["CoreNet-DHCP-In", "WFDPRINT-SPOOL-In", "{GUID-1}"]
    assert rules[2].display_name == "Teams" and rules[2].program.endswith("teams.exe")
    # tek kural: PowerShell ConvertTo-Json tek nesne dondurebilir; bos cikti
    assert fw._parse('{"Name":"A","DisplayName":"B"}')[0].name == "A"
    assert fw._parse("[]") == []
    with pytest.raises(fw.FirewallError):
        fw._parse("bozuk")
    with pytest.raises(fw.FirewallError, match="okunamadı"):
        fw.list_rules(lambda c, e=None: (1, "", "hata"))


# ---------------- pasiflestir / etkinlestir ----------------
def test_disable_enable_roundtrip_and_tracking():
    f = FakeFw()
    r = fw.disable_rule("{GUID-1}", f)
    assert r.ok and r.changed and f.rules["{GUID-1}"][2] is False
    assert fw.disabled_by_us() == ["{GUID-1}"]
    assert [x.name for x in fw.list_rules(f)] == ["CoreNet-DHCP-In", "WFDPRINT-SPOOL-In"]
    fw.enable_rule("{GUID-1}", f)
    assert f.rules["{GUID-1}"][2] is True and fw.disabled_by_us() == [] and backup.load() == {}


def test_name_passed_via_env_not_in_command_text():
    f = FakeFw()
    f.rules["x; calc.exe"] = ["Kotu", "p", True]
    fw.disable_rule("x; calc.exe", f)
    cmd, env = next((c, e) for c, e in f.commands if c.startswith("Set-NetFirewallRule"))
    assert cmd == "Set-NetFirewallRule -Name $env:AUXY_ARG -Enabled False"
    assert "calc" not in cmd and env["AUXY_ARG"] == "x; calc.exe"


def test_cannot_disable_unlisted_or_our_blocks_or_enable_foreign():
    f = FakeFw()
    with pytest.raises(fw.FirewallError, match="arasında değil"):
        fw.disable_rule("Yok-Boyle-Kural", f)
    with pytest.raises(fw.FirewallError, match="engel kuralları"):
        fw.disable_rule("AuxySecurity-in-0123456789ab", f)
    with pytest.raises(fw.FirewallError, match="biz pasifleştirmedik"):
        fw.enable_rule("CoreNet-DHCP-In", f)  # biz kapatmadik: acamayiz
    for bad in ("", "a\nb", "x" * 300):
        with pytest.raises(fw.FirewallError):
            fw.disable_rule(bad, f)
    assert not any(c.startswith("Set-NetFirewallRule") for c, _ in f.commands)


def test_disable_not_applied_rolls_back_tracking():
    f = FakeFw(apply=False)
    with pytest.raises(fw.FirewallError, match="uygulanmadı"):
        fw.disable_rule("{GUID-1}", f)
    assert fw.disabled_by_us() == [] and backup.load() == {}


def test_disable_command_failure_rolls_back_tracking():
    f = FakeFw()
    real = f.__call__

    def failing(command, env=None):
        if command.startswith("Set-NetFirewallRule"):
            return 5, "", "erisim engellendi"
        return real(command, env)

    with pytest.raises(fw.FirewallError, match="başarısız"):
        fw.disable_rule("{GUID-1}", failing)
    assert fw.disabled_by_us() == []


# ---------------- program engelleme ----------------
@pytest.fixture
def prog(tmp_path):
    p = tmp_path / "kotu program.exe"
    p.write_bytes(b"MZ")
    return str(p)


def test_block_creates_two_rules_and_is_idempotent(prog):
    f = FakeFw()
    r = fw.block_program(prog, f)
    assert r.ok and r.changed
    names = sorted(f.blocks)
    in_name, out_name = fw.rule_names_for(prog)
    assert names == sorted([in_name, out_name]) and all(n.startswith("AuxySecurity-") for n in names)
    assert all(v[1] == prog for v in f.blocks.values()) and "kotu program.exe" in f.blocks[in_name][0]
    again = fw.block_program(prog, f)
    assert not again.changed and "zaten engelli" in again.message
    created = [c for c, _ in f.commands if c.startswith("New-NetFirewallRule")]
    assert len(created) == 2  # ikinci cagri yeni kural uretmedi


def test_block_values_via_env_only(prog):
    f = FakeFw()
    fw.block_program(prog, f)
    for cmd, env in f.commands:
        if cmd.startswith("New-NetFirewallRule"):
            assert prog not in cmd and "kotu" not in cmd
            assert env["AUXY_ARG"] == prog and env["AUXY_NAME"].startswith("AuxySecurity-")


def test_block_rejects_system_files_missing_and_odd_paths(tmp_path):
    f = FakeFw()
    sysfile = Path(__import__("os").environ["SystemRoot"]) / "System32" / "notepad.exe"
    for bad in (str(sysfile), str(tmp_path / "yok.exe"), "goreli.exe", "\\\\sunucu\\x.exe", "", "C:\\a*.exe", str(tmp_path)):
        with pytest.raises(fw.FirewallError):
            fw.block_program(bad, f)
    assert f.blocks == {}


def test_unblock_by_path_by_rule_name_and_removed_program(prog):
    f = FakeFw()
    fw.block_program(prog, f)
    in_name, _ = fw.rule_names_for(prog)
    r = fw.unblock_program(in_name, f)  # kural adiyla: iki yon de kalkar
    assert r.changed and f.blocks == {}
    fw.block_program(prog, f)
    Path(prog).unlink()  # program silinmis: yine de engeli kalkabilmeli
    assert fw.unblock_program(prog, f).changed and f.blocks == {}
    assert not fw.unblock_program(prog, f).changed  # yokken: sorun degil


def test_unblock_never_removes_foreign_rules():
    f = FakeFw()
    for bad in ("CoreNet-DHCP-In", "AuxySecurity-in-ZZZZ", "AuxySecurity-*", "x\ny"):
        with pytest.raises(fw.FirewallError):
            fw.unblock_program(bad, f)
    assert not any(c.startswith("Remove-NetFirewallRule") for c, _ in f.commands)


# ---------------- actions / UAC ----------------
def test_actions_read_ops_need_no_uac_and_write_ops_validate_first(monkeypatch):
    seen = []
    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", lambda *a, **k: seen.append(a))
    monkeypatch.setattr(fw, "run_op", lambda op, value="": ActionResult(True, "ok", data=[{"name": "x"}]))
    assert actions.firewall_op("list").ok and actions.firewall_op("list-blocks").ok and seen == []
    for op, val in (("block", "goreli.exe"), ("disable", ""), ("unblock", "x\ny"), ("hack", "a")):
        assert not actions.firewall_op(op, val).ok
    assert seen == []  # gecersiz girdi icin UAC acilmadi


def test_actions_elevates_valid_write_op(monkeypatch, tmp_path):
    seen = []

    def fake(args, timeout_s=120):
        seen.append(args)
        actions.write_result(args[args.index("--result") + 1], True, "tamam", True)
        return 0

    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", fake)
    assert actions.firewall_op("disable", "{GUID-1}").ok
    assert seen[0][:3] == ["firewall-rule", "disable", "{GUID-1}"]
    p = tmp_path / "a.exe"
    p.write_bytes(b"MZ")
    assert actions.firewall_op("block", str(p)).ok and seen[1][:3] == ["firewall-rule", "block", str(p)]


def test_actions_admin_direct(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(fw, "run_op", lambda op, value="": ActionResult(True, f"{op}:{value}", True))
    assert actions.firewall_op("disable", "R1").message == "disable:R1"


# ---------------- CLI ----------------
def test_cli_list_needs_no_admin_and_helper_guard(monkeypatch, capsys):
    data = [{"name": "R1", "display_name": "Kural Bir", "profile": "Any", "program": r"C:\a.exe", "group": ""}]
    monkeypatch.setattr(actions, "firewall_op", lambda op, v="": ActionResult(True, "1 kural.", data=data))
    monkeypatch.setattr(system, "is_admin", lambda: False)
    out = Path(tempfile.gettempdir()) / "auxy-result-fw.json"
    try:
        assert cli.main(["firewall-rule", "list", "--result", str(out)]) == 0  # okuma: yonetici gerekmez
        assert "Kural Bir" in capsys.readouterr().out
        assert cli.main(["firewall-rule", "disable", "R1", "--result", str(out)]) == 3  # yazma: yardimci modunda yonetici yok
        assert json.loads(out.read_text(encoding="utf-8"))["ok"] is False
    finally:
        out.unlink(missing_ok=True)


# ---------------- GUI ----------------
def pump(a, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if cond():
            return True
        REAL_SLEEP(0.05)
    return False


RULES = [
    {"name": "R-A", "display_name": "Yazıcı Paylaşımı", "profile": "Private", "program": r"C:\win\spool.exe", "group": ""},
    {"name": "R-B", "display_name": "Teams", "profile": "Any", "program": "Any", "group": ""},
]
BLOCKS = [
    {"name": "AuxySecurity-in-0123456789ab", "display_name": "AuxySecurity: Engelle – kotu.exe", "profile": "Any",
     "program": r"D:\kotu.exe", "group": ""},
    {"name": "AuxySecurity-out-0123456789ab", "display_name": "AuxySecurity: Engelle – kotu.exe", "profile": "Any",
     "program": r"D:\kotu.exe", "group": ""},
]


@pytest.fixture
def spage(app, monkeypatch):
    page = app.pages["network"]
    calls = []

    def fake_op(op, value=""):
        calls.append((op, value))
        if op == "list":
            return ActionResult(True, "2 kural.", data=RULES)
        if op == "list-blocks":
            return ActionResult(True, "2", data=BLOCKS)
        return ActionResult(True, f"{op} tamam", True)

    monkeypatch.setattr(actions, "firewall_op", fake_op)
    page.calls = calls
    yield page
    page.rule_filter.delete(0, "end")


def _labels(frame):
    import customtkinter as ctk

    return [w.cget("text") for w in frame.winfo_children() if isinstance(w, ctk.CTkLabel)]


def test_rules_list_filter_and_blocks(app, spage):
    spage.load_rules()
    assert pump(app, lambda: len(spage.rules_cache) == 2)
    text = "\n".join(_labels(spage.rules_frame))
    assert "Yazıcı Paylaşımı" in text and "Teams" in text and "(tüm programlar)" in text
    assert text.count("ENGELLİ") == 1 and r"D:\kotu.exe" in text  # in/out ciftinden TEK satir
    spage.rule_filter.insert(0, "yazıcı")
    spage._render_rules()
    text2 = "\n".join(_labels(spage.rules_frame))
    assert "Yazıcı Paylaşımı" in text2 and "Teams" not in text2


def test_disable_requires_confirmation_then_runs_and_reloads(app, spage, monkeypatch):
    from auxy.gui import network_page

    spage.load_rules()
    assert pump(app, lambda: len(spage.rules_cache) == 2)
    monkeypatch.setattr(network_page.messagebox, "askyesno", lambda *a, **k: False)
    spage.disable_rule(RULES[0])
    app.update()
    assert not any(c[0] == "disable" for c in spage.calls)
    monkeypatch.setattr(network_page.messagebox, "askyesno", lambda *a, **k: True)
    spage.disable_rule(RULES[0])
    assert pump(app, lambda: ("disable", "R-A") in spage.calls)
    assert pump(app, lambda: "disable tamam" in spage.message.cget("text"))
    assert pump(app, lambda: [c[0] for c in spage.calls].count("list") >= 2)  # islem sonrasi liste yenilendi


def test_block_program_dialog_and_unblock(app, spage, monkeypatch, tmp_path):
    from auxy.gui import network_page

    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(network_page.filedialog, "askopenfilename", lambda **k: str(exe))
    monkeypatch.setattr(network_page.messagebox, "askyesno", lambda *a, **k: False)
    spage.block_program()
    app.update()
    assert not any(c[0] == "block" for c in spage.calls)  # onay yok: engellenmez
    monkeypatch.setattr(network_page.messagebox, "askyesno", lambda *a, **k: True)
    spage.block_program()
    assert pump(app, lambda: ("block", str(exe)) in spage.calls)
    spage.unblock("AuxySecurity-in-0123456789ab")
    assert pump(app, lambda: ("unblock", "AuxySecurity-in-0123456789ab") in spage.calls)
    monkeypatch.setattr(network_page.filedialog, "askopenfilename", lambda **k: "")
    n = len(spage.calls)
    spage.block_program()  # dosya secilmedi
    app.update()
    assert len(spage.calls) == n


def test_inbound_allow_needs_confirmation(app, monkeypatch):
    from auxy.gui import network_page

    page = app.pages["network"]
    applied = []
    monkeypatch.setattr(page, "_apply", lambda k, v: applied.append((k, v)))
    monkeypatch.setattr(page, "refresh", lambda: None)
    monkeypatch.setattr(network_page.messagebox, "askyesno", lambda *a, **k: False)
    page._set_inbound("fw_in_public", "İzin ver")
    assert applied == []  # reddedildi
    monkeypatch.setattr(network_page.messagebox, "askyesno", lambda *a, **k: True)
    page._set_inbound("fw_in_public", "İzin ver")
    page._set_inbound("fw_in_public", "Engelle")  # guclendirme: onay sormaz
    page._set_inbound("fw_in_private", "Varsayılan")
    assert applied == [("fw_in_public", "allow"), ("fw_in_public", "block"), ("fw_in_private", "default")]


# ---------------- PowerShell Turkce karakter / ortam degiskeni (gercek PowerShell; eksik tamamlama hatasi) ----------------
def test_pshell_returns_turkish_text_intact():
    """GERCEK HATA: PS 5.1 cikti OEM kod sayfasindaydi; UTF-8 cozmek 'Kullanim' -> 'Kullan?m?' yapiyordu."""
    from auxy.core import pshell

    rc, out, err = pshell.run("Write-Output 'Çekirdek Ağ - İstenmeyen ığüşöç ÇĞÜŞÖİ'")
    assert rc == 0 and out.strip() == "Çekirdek Ağ - İstenmeyen ığüşöç ÇĞÜŞÖİ"


def test_pshell_env_values_are_data_not_code():
    from auxy.core import pshell

    nasty = "a'b\"c; calc.exe `$(whoami) ğüş ‘x’"
    rc, out, _e = pshell.run("Write-Output $env:AUXY_ARG", {"AUXY_ARG": nasty})
    assert rc == 0 and out.strip() == nasty


def test_pshell_error_text_is_decoded_too():
    from auxy.core import pshell

    rc, out, err = pshell.run("Write-Error 'Çok kötü hata: ığüşöç'; exit 3")
    assert rc == 3 and "Çok kötü hata: ığüşöç" in err


def test_decode_output_utf8_and_oem():
    import ctypes

    from auxy.core import pshell

    text = "Çalışma Klasörü\\kötü.exe"
    assert pshell.decode_output(text.encode("utf-8")) == text
    oem = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    try:
        raw = text.encode(oem)
    except (LookupError, UnicodeEncodeError):
        pytest.skip("OEM kod sayfasi Turkce karakterleri kodlayamiyor")
    # UTF-8 olarak gecersiz baytlar -> OEM'e dusmeli (ASCII-yalniz ise zaten UTF-8 gecerlidir)
    assert pshell.decode_output(raw) == text


def test_firewall_list_with_real_powershell_returns_turkish_names_if_present():
    """Gercek makinede kural listesi okunabilmeli ve gorunen adlarda bozuk karakter (U+FFFD) olmamali."""
    rules = fw.list_rules()
    assert len(rules) > 0
    assert not any("\ufffd" in r.display_name or "\ufffd" in r.program for r in rules)
