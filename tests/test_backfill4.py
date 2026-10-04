import json
import tempfile
import time
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import actions, system
from auxy.core import defender_quarantine as dq
from auxy.core.actions import ActionResult

REAL_SLEEP = time.sleep

# gercek makineden alinan cikti (yol kisaltildi)
REAL_OUTPUT = r"""The following items are quarantined:

ThreatName = Virus:DOS/EICAR_Test_File
      file:C:\Users\kagan\AppData\Local\Temp\scantest\eicar-test.txt quarantined at 4.10.2026 19:54:32 (UTC)
      file:C:\Users\kagan\AppData\Local\Temp\scantest\eicar-2.txt quarantined at 4.10.2026 19:58:12 (UTC)

ThreatName = Trojan:Win32/Sahte
      file:D:\İndirilenler\Türkçe Klasör\kötü.exe quarantined at 5.10.2026 09:00:00 (UTC)
      regkey:HKLM\Software\Kotu quarantined at 5.10.2026 09:00:01 (UTC)
"""


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


# ---------------- ayristirma ----------------
def test_parse_real_output():
    items = dq.parse_listall(REAL_OUTPUT)
    assert [i.threat for i in items] == ["Virus:DOS/EICAR_Test_File"] * 2 + ["Trojan:Win32/Sahte"] * 2
    assert items[0].path.endswith(r"scantest\eicar-test.txt") and items[0].scheme == "file"
    assert items[0].quarantined_at == "4.10.2026 19:54:32 (UTC)"
    assert items[2].path == r"D:\İndirilenler\Türkçe Klasör\kötü.exe"  # bosluk + Turkce karakter
    assert items[3].scheme == "regkey"


@pytest.mark.parametrize("text", ["", "The following items are quarantined:\n", "rastgele\nmetin\n",
                                  "      file:C:\\x quarantined at 1.1.2026 (UTC)\n"])  # ThreatName'siz kalinti satir
def test_parse_empty_or_garbage(text):
    assert dq.parse_listall(text) == []


def test_parse_file_underscore_prefix_variant():
    out = "ThreatName = X\n      file:_C:\\a\\b.exe quarantined at 1.1.2026 00:00:00 (UTC)\n"
    assert dq.parse_listall(out)[0].path == r"C:\a\b.exe"


# ---------------- list / restore ----------------
class FakeMp:
    """MpCmdRun taklidi: karantina listesini tutar, -Restore -FilePath ile siler."""

    def __init__(self, output=REAL_OUTPUT, rc=0, restore_works=True):
        self.output, self.rc, self.restore_works, self.calls = output, rc, restore_works, []
        self.landed = []  # alternatif klasorlere yazilan dosyalar (gercek Defender davranisi)

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["-Restore", "-ListAll"]:
            return self.rc, self.output
        if args[:2] == ["-Restore", "-FilePath"] and self.restore_works:
            path = args[2]
            if "-Path" in args:
                # GERCEK DAVRANIS (canli testte gorulen): alternatif klasore geri yuklemede oge listede KALIR
                dest = Path(args[args.index("-Path") + 1]) / Path(path).name
                dest.write_text("geri yuklendi")
                self.landed.append(dest)
            else:
                self.output = "\n".join(ln for ln in self.output.splitlines() if path not in ln)
        return self.rc, ""


def test_list_items_and_error():
    assert len(dq.list_items(FakeMp())) == 4
    with pytest.raises(dq.DefenderQuarantineError, match="okunamadı"):
        dq.list_items(FakeMp(rc=2))


def test_restore_builds_args_and_verifies():
    mp = FakeMp()
    target = r"C:\Users\kagan\AppData\Local\Temp\scantest\eicar-test.txt"
    res = dq.restore(target, run=mp)
    assert res.ok and res.changed and "yeniden karantinaya" in res.message
    assert ["-Restore", "-FilePath", target] in mp.calls
    assert not any("-Path" in c for c in mp.calls)
    # alternatif klasore
    mp2 = FakeMp()
    d = Path(tempfile.mkdtemp(prefix="auxy-dq-"))
    res2 = dq.restore(target, str(d), run=mp2)
    assert ["-Restore", "-FilePath", target, "-Path", str(d)] in mp2.calls
    assert (d / "eicar-test.txt").exists() and "Geri yüklendi:" in res2.message
    assert len(dq.list_items(mp2)) == 4  # oge listede KALIR: gercek Defender davranisi, hata sayilmamali


def test_restore_rejects_unknown_path_and_bad_input():
    mp = FakeMp()
    with pytest.raises(dq.DefenderQuarantineError, match="listesinde değil"):
        dq.restore(r"C:\baska\dosya.exe", run=mp)  # listede olmayan yol: komut HIC calistirilmaz
    assert not any(c[:2] == ["-Restore", "-FilePath"] for c in mp.calls)
    for bad in ["", "goreli\\yol.exe", "\\\\sunucu\\paylasim\\x.exe", "C:\\a\nb.exe", "x.exe"]:
        with pytest.raises(dq.DefenderQuarantineError):
            dq.validate_restore_path(bad)


def test_restore_invalid_target_dir(tmp_path):
    t = r"C:\Users\kagan\AppData\Local\Temp\scantest\eicar-test.txt"
    for bad in ("goreli", str(tmp_path / "yok")):
        with pytest.raises(dq.DefenderQuarantineError, match="Hedef klasör"):
            dq.restore(t, bad, run=FakeMp())


def test_restore_failure_and_not_applied(tmp_path):
    t = r"C:\Users\kagan\AppData\Local\Temp\scantest\eicar-test.txt"
    with pytest.raises(dq.DefenderQuarantineError, match="uygulanmadı"):
        dq.restore(t, run=FakeMp(restore_works=False))  # orijinal konum: hala listede, dosya yok
    with pytest.raises(dq.DefenderQuarantineError, match="hedefte bulunamadı"):
        dq.restore(t, str(tmp_path), run=FakeMp(restore_works=False))  # alternatif: dosya hedefe dusmedi
    calls = {"n": 0}

    def flaky(args):
        calls["n"] += 1
        if args[:2] == ["-Restore", "-ListAll"]:
            return 0, REAL_OUTPUT
        return 5, "erisim engellendi"

    with pytest.raises(dq.DefenderQuarantineError, match="başarısız"):
        dq.restore(t, run=flaky)


# ---------------- temizleme / cevrimdisi (SAHTE yurutucu: gercek komut asla calismaz) ----------------
def test_clean_and_offline_use_fixed_commands():
    seen = []

    def fake(cmd):
        seen.append(cmd)
        return 0, ""

    assert dq.clean_active(fake).ok and dq.offline_scan(fake).ok
    assert seen == ["Remove-MpThreat", "Start-MpWDOScan"]  # sabit komutlar, kullanici girdisi yok


def test_clean_and_offline_failures():
    with pytest.raises(dq.DefenderQuarantineError, match="Remove-MpThreat"):
        dq.clean_active(lambda c: (1, "hata"))
    with pytest.raises(dq.DefenderQuarantineError, match="Start-MpWDOScan"):
        dq.offline_scan(lambda c: (1, "hata"))


def test_run_op_dispatch(monkeypatch):
    monkeypatch.setattr(dq, "list_items", lambda run=None: [dq.QuarantinedItem("T", r"C:\a", "file", "d")])
    res = dq.run_op("list")
    assert res.data == [{"threat": "T", "path": r"C:\a", "scheme": "file", "quarantined_at": "d"}]
    monkeypatch.setattr(dq, "clean_active", lambda: ActionResult(True, "temiz"))
    assert dq.run_op("clean").message == "temiz"
    with pytest.raises(dq.DefenderQuarantineError):
        dq.run_op("sil")


# ---------------- actions: UAC akisi ----------------
def test_actions_validate_before_uac_and_elevate(monkeypatch):
    seen = []

    def fake(args, timeout_s=120):
        seen.append((args, timeout_s))
        actions.write_result(args[args.index("--result") + 1], True, "ok", False, [{"a": 1}])
        return 0

    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", fake)
    bad = actions.defender_quarantine_op("restore", "goreli.exe")
    assert not bad.ok and seen == []  # gecersiz girdi icin UAC acilmaz
    assert not actions.defender_quarantine_op("hack").ok and seen == []
    r = actions.defender_quarantine_op("list")
    assert r.ok and r.data == [{"a": 1}] and seen[0][0][:2] == ["defender-quarantine", "list"]
    actions.defender_quarantine_op("restore", r"C:\x\y.exe", r"C:\hedef")
    assert seen[1][0][:5] == ["defender-quarantine", "restore", r"C:\x\y.exe", "--to", r"C:\hedef"]
    actions.defender_quarantine_op("offline-scan")
    assert seen[2][1] == 300  # uzun zaman asimi


def test_actions_admin_direct(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(dq, "run_op", lambda op, p="", t="": ActionResult(True, f"{op}!"))
    assert actions.defender_quarantine_op("clean").message == "clean!"
    monkeypatch.setattr(dq, "run_op", lambda *a: (_ for _ in ()).throw(dq.DefenderQuarantineError("kotu")))
    r = actions.defender_quarantine_op("clean")
    assert not r.ok and r.message == "kotu"


# ---------------- CLI ----------------
def test_cli_offline_scan_needs_yes_and_helper_mode(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(actions, "defender_quarantine_op", lambda op, p="", t="": ran.append(op) or ActionResult(True, "ok"))
    assert cli.main(["defender-quarantine", "offline-scan"]) == 2  # --yes yok: calismaz
    assert ran == [] and "YENİDEN BAŞLATIR" in capsys.readouterr().err
    assert cli.main(["defender-quarantine", "offline-scan", "--yes"]) == 0
    assert ran == ["offline-scan"]


def test_cli_list_prints_and_helper_guard(monkeypatch, capsys):
    out = Path(tempfile.gettempdir()) / "auxy-result-dq.json"
    try:
        data = [{"threat": "Virus:X", "path": r"C:\a.exe", "scheme": "file", "quarantined_at": "1.1.2026 (UTC)"}]
        monkeypatch.setattr(actions, "defender_quarantine_op", lambda op, p="", t="": ActionResult(True, "1 öğe.", data=data))
        monkeypatch.setattr(system, "is_admin", lambda: True)
        assert cli.main(["defender-quarantine", "list", "--result", str(out)]) == 0
        assert "Virus:X" in capsys.readouterr().out
        assert json.loads(out.read_text(encoding="utf-8"))["data"] == data
        monkeypatch.setattr(system, "is_admin", lambda: False)  # yardimci modunda yonetici alinamadi
        assert cli.main(["defender-quarantine", "list", "--result", str(out)]) == 3
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


DATA = [
    {"threat": "Virus:DOS/EICAR_Test_File", "path": r"C:\x\eicar.txt", "scheme": "file", "quarantined_at": "4.10.2026 (UTC)"},
    {"threat": "Trojan:Y", "path": r"HKLM\Software\Kotu", "scheme": "regkey", "quarantined_at": "5.10.2026 (UTC)"},
]


@pytest.fixture
def qpage(app, monkeypatch):
    from auxy.gui import vault_page

    page = app.pages["quarantine"]
    calls = []

    def fake_op(op, path="", to_dir=""):
        calls.append((op, path, to_dir))
        return ActionResult(True, f"{op} tamam", True, DATA if op == "list" else None)

    monkeypatch.setattr(actions, "defender_quarantine_op", fake_op)
    page.calls = calls
    yield page
    page.mode_btn.set(vault_page.MODE_VAULT)
    page._set_mode(vault_page.MODE_VAULT)
    page.defender_view.loaded = False
    app.update()


def _buttons(widget, text):
    import customtkinter as ctk

    stack, out = [widget], []
    while stack:
        w = stack.pop()
        if isinstance(w, ctk.CTkButton) and w.cget("text") == text:
            out.append(w)
        stack.extend(w.winfo_children())
    return out


def test_mode_switch_shows_defender_list(app, qpage):
    from auxy.gui import vault_page

    qpage.mode_btn.set(vault_page.MODE_DEFENDER)
    qpage._set_mode(vault_page.MODE_DEFENDER)
    assert pump(app, lambda: qpage.defender_view.loaded)
    assert qpage.defender_view.winfo_ismapped() and not qpage.list._parent_frame.winfo_ismapped()
    assert str(qpage.file_btn.cget("state")) == "disabled"
    # yalnizca 'file' ogeleri icin geri yukle dugmesi
    assert len(_buttons(qpage.defender_view.list, "Geri yükle…")) == 1
    assert "2 öğe" in qpage.status.cget("text")
    qpage.mode_btn.set(vault_page.MODE_VAULT)
    qpage._set_mode(vault_page.MODE_VAULT)
    app.update()
    # CTkScrollableFrame'in gorunen kabi _parent_frame'dir
    assert qpage.list._parent_frame.winfo_ismapped() and not qpage.defender_view.winfo_ismapped()
    assert qpage.status.cget("text") == ""  # Defender gorunumunun mesaji kasada kalmaz


@pytest.mark.parametrize("answer,expect_dir", [(True, ""), (False, r"C:\Yeni")])
def test_defender_restore_choices(app, qpage, monkeypatch, answer, expect_dir):
    from auxy.gui import vault_page

    monkeypatch.setattr(vault_page.messagebox, "askyesnocancel", lambda *a, **k: answer)
    monkeypatch.setattr(vault_page.filedialog, "askdirectory", lambda **k: r"C:\Yeni")
    qpage.defender_view.restore(DATA[0])
    assert pump(app, lambda: any(c[0] == "restore" for c in qpage.calls))
    assert ("restore", DATA[0]["path"], expect_dir) in qpage.calls


def test_defender_restore_cancel_and_no_folder(app, qpage, monkeypatch):
    from auxy.gui import vault_page

    monkeypatch.setattr(vault_page.messagebox, "askyesnocancel", lambda *a, **k: None)
    qpage.defender_view.restore(DATA[0])
    monkeypatch.setattr(vault_page.messagebox, "askyesnocancel", lambda *a, **k: False)
    monkeypatch.setattr(vault_page.filedialog, "askdirectory", lambda **k: "")  # klasor secilmedi
    qpage.defender_view.restore(DATA[0])
    app.update()
    assert not any(c[0] == "restore" for c in qpage.calls)


def test_offline_scan_needs_both_confirmations(app, qpage, monkeypatch):
    from auxy.gui import vault_page

    answers = iter([False])
    monkeypatch.setattr(vault_page.messagebox, "askyesno", lambda *a, **k: next(answers))
    qpage.defender_view.offline_scan()  # ilk onay HAYIR
    app.update()
    assert not any(c[0] == "offline-scan" for c in qpage.calls)
    answers2 = iter([True, False])  # ilk EVET, son uyari HAYIR
    monkeypatch.setattr(vault_page.messagebox, "askyesno", lambda *a, **k: next(answers2))
    qpage.defender_view.offline_scan()
    app.update()
    assert not any(c[0] == "offline-scan" for c in qpage.calls)
    answers3 = iter([True, True])
    monkeypatch.setattr(vault_page.messagebox, "askyesno", lambda *a, **k: next(answers3))
    qpage.defender_view.offline_scan()
    assert pump(app, lambda: any(c[0] == "offline-scan" for c in qpage.calls))  # sahte op: gercek yeniden baslatma YOK


def test_clean_button_on_scan_page_only_when_active(app, qpage, monkeypatch):
    from datetime import datetime

    from auxy.core import threats
    from auxy.gui import scan_page

    page = app.pages["scan"]
    mk = lambda active: [threats.Detection(1, "T", "Yüksek", [], datetime.now(), False, active)]  # noqa: E731
    page._show_threats(mk(False), None)
    assert not page.clean_btn.winfo_manager()
    page._show_threats(mk(True), None)
    assert page.clean_btn.winfo_manager()
    monkeypatch.setattr(scan_page.messagebox, "askyesno", lambda *a, **k: False)
    page.clean_active()
    app.update()
    assert not any(c[0] == "clean" for c in qpage.calls)  # onay HAYIR: calismaz
    monkeypatch.setattr(scan_page.messagebox, "askyesno", lambda *a, **k: True)
    page.clean_active()
    assert pump(app, lambda: any(c[0] == "clean" for c in qpage.calls))
    page._show_threats([], None)
    assert not page.clean_btn.winfo_manager()
