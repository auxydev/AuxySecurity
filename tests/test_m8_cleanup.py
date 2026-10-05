import os
import sqlite3

import pytest

from auxy import __main__ as cli
from auxy.core import actions, autostart, backup, cleanup, contextmenu, paths, system
from auxy.core.actions import ActionResult


@pytest.fixture(autouse=True)
def safe(tmp_path, monkeypatch):
    """GERCEK sistem girdilerine (kayit defteri, gorev) ASLA dokunma: hepsi sahte."""
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    state = {"ctx": True, "task": True, "calls": []}
    monkeypatch.setattr(contextmenu, "is_installed", lambda: state["ctx"])
    monkeypatch.setattr(contextmenu, "remove", lambda: state.update(ctx=False) or state["calls"].append("ctx-remove"))
    monkeypatch.setattr(autostart, "is_installed", lambda: state["task"])

    def fake_autostart(op):
        state["calls"].append(f"autostart-{op}")
        state["task"] = False
        return ActionResult(True, "Başlangıç görevi kaldırıldı.", True)

    monkeypatch.setattr(actions, "autostart_op", fake_autostart)
    monkeypatch.setattr(system, "is_agent_running", lambda: False)
    yield state
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def make_vault_db(n: int):
    root = paths.home() / "vault"
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "vault.db")
    db.execute("CREATE TABLE items (id TEXT)")
    db.executemany("INSERT INTO items VALUES (?)", [(str(i),) for i in range(n)])
    db.commit()
    db.close()


def names(steps):
    return {s.name: s for s in steps}


def test_default_removes_system_entries_and_keeps_data(safe):
    (paths.home() / "dosya.txt").write_text("x")
    steps = names(cleanup.run())
    assert safe["calls"] == ["ctx-remove", "autostart-remove"]
    assert steps["Sağ tık menüsü"].ok and steps["Başlangıç görevi"].ok
    assert "korundu" in steps["Veri"].detail and (paths.home() / "dosya.txt").exists()  # veriye dokunmaz


def test_idempotent_when_nothing_installed(safe):
    safe["ctx"] = safe["task"] = False
    steps = names(cleanup.run())
    assert safe["calls"] == [] and "zaten kurulu değil" in steps["Başlangıç görevi"].detail


def test_remove_data_deletes_when_vault_empty(safe):
    make_vault_db(0)
    (paths.home() / "x.log").write_text("log")
    steps = names(cleanup.run(remove_data=True))
    assert steps["Veri"].ok and "silindi" in steps["Veri"].detail
    assert not any(paths.home().rglob("*")) or not paths.home().exists()


def test_remove_data_refused_when_vault_has_items(safe):
    make_vault_db(3)
    steps = cleanup.run(remove_data=True)
    d = names(steps)
    assert not d["Veri"].ok and "3 dosya var" in d["Veri"].detail and "KALICI" in d["Veri"].detail
    assert (paths.home() / "vault" / "vault.db").exists()  # silinmedi
    assert d["Sonuç"].ok is False


def test_force_vault_deletes_anyway(safe):
    make_vault_db(3)
    d = names(cleanup.run(remove_data=True, force_vault=True))
    assert d["Veri"].ok and not (paths.home() / "vault" / "vault.db").exists()


def test_unreadable_vault_db_is_treated_as_dangerous(safe):
    root = paths.home() / "vault"
    root.mkdir(parents=True)
    (root / "vault.db").write_bytes(b"BOZUK" * 100)
    assert cleanup.vault_item_count() == -1
    d = names(cleanup.run(remove_data=True))
    assert not d["Veri"].ok and "okunamadı" in d["Veri"].detail and (root / "vault.db").exists()


def test_remove_data_refused_while_agent_runs(safe, monkeypatch):
    monkeypatch.setattr(system, "is_agent_running", lambda: True)
    (paths.home() / "x.txt").write_text("x")
    d = names(cleanup.run(remove_data=True))
    assert not d["Veri"].ok and "Çıkış" in d["Veri"].detail and (paths.home() / "x.txt").exists()


def test_revert_settings_uses_revert_fn_only_when_backup_exists(safe):
    called = []
    fn = lambda: called.append(1) or ActionResult(True, "pua: off→on", True)  # noqa: E731
    d = names(cleanup.run(revert_settings=True, revert_fn=fn))
    assert called == [] and "geri alınacak değişiklik yok" in d["Ayarlar"].detail
    backup.remember_original("pua", 1)
    d = names(cleanup.run(revert_settings=True, revert_fn=fn))
    assert called == [1] and d["Ayarlar"].ok and "pua" in d["Ayarlar"].detail


def test_failed_step_marks_overall_failure(safe, monkeypatch):
    monkeypatch.setattr(actions, "autostart_op", lambda op: ActionResult(False, "Yönetici izni verilmedi."))
    steps = cleanup.run()
    assert names(steps)["Başlangıç görevi"].ok is False and names(steps)["Sonuç"].ok is False


def test_cli_exit_codes(safe, monkeypatch, capsys):
    assert cli.main(["cleanup"]) == 0
    out = capsys.readouterr().out
    assert "✔ Sağ tık menüsü" in out and "korundu" in out
    make_vault_db(2)
    assert cli.main(["cleanup", "--remove-data"]) == 1  # kasada dosya: reddedildi


# ---------------- revert_all ----------------
def test_revert_all_admin_runs_both_and_reports(monkeypatch):
    from auxy.core import service, winsec

    monkeypatch.setattr(system, "is_admin", lambda: True)
    R = lambda k: type("R", (), {"key": k, "old": "a", "new": "b"})()  # noqa: E731
    monkeypatch.setattr(service.DefenderService, "revert", lambda self, key=None: [R("pua")])
    monkeypatch.setattr(winsec.WinSecService, "revert", lambda self, key=None: [R("fw_public")])
    res = actions.revert_all()
    assert res.ok and "pua" in res.message and "fw_public" in res.message


def test_revert_all_reports_partial_failure(monkeypatch):
    from auxy.core import service, winsec
    from auxy.core.service import AuxyError

    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(service.DefenderService, "revert", lambda self, key=None: (_ for _ in ()).throw(AuxyError("kotu")))
    monkeypatch.setattr(winsec.WinSecService, "revert", lambda self, key=None: [])
    res = actions.revert_all()
    assert not res.ok and "Defender: kotu" in res.message


def test_revert_all_elevates_when_not_admin(monkeypatch):
    seen = []
    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", lambda args, timeout_s=120: seen.append(args) or (
        actions.write_result(args[args.index("--result") + 1], True, "ok", True) or 0))
    assert actions.revert_all().ok and seen[0][0] == "revert-all"


def test_cli_revert_all_helper_guard(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    out = os.path.join(__import__("tempfile").gettempdir(), "auxy-result-ra.json")
    try:
        assert cli.main(["revert-all", "--result", out]) == 3  # yardimci modunda yonetici alinamadi: dongu yok
    finally:
        if os.path.exists(out):
            os.remove(out)
