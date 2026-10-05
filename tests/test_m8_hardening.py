import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import actions, backup, doctor, hardening, paths
from auxy.core import vault as v
from auxy.core.vault import Vault, VaultError


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUXY_INSTANCE", "_m8hard")  # doctor tarama kilidini/ajan mutex'ini gercek olanlarla paylasmasin
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


# ---------------- kurulum konumu riski ----------------
def test_location_risk_user_dirs_warn_and_program_files_ok(tmp_path):
    risky = hardening.install_location_risk(tmp_path / "src" / "auxy", tmp_path / ".venv" / "Scripts")
    assert risky.risky and len(risky.paths) == 2 and "yönetici yetkisi kazanabilir" in risky.detail
    pf = Path(os.environ["ProgramFiles"])
    safe = hardening.install_location_risk(pf / "AuxySecurity" / "auxy", pf / "AuxySecurity" / "python")
    assert not safe.risky and safe.paths == ()
    mixed = hardening.install_location_risk(pf / "AuxySecurity" / "auxy", tmp_path / "python")  # biri riskli yeter
    assert mixed.risky and mixed.paths == (str(tmp_path / "python"),)


# ---------------- sonuc dosyasi guvenli yazim ----------------
def tmp_result(name: str) -> Path:
    return Path(tempfile.gettempdir()) / f"auxy-result-{name}.json"


def test_result_file_normal_write_new_and_existing():
    p = tmp_result("m8-normal")
    p.unlink(missing_ok=True)
    try:
        actions.write_result(str(p), True, "yeni dosya")  # yoksa O_EXCL ile olusturur
        assert json.loads(p.read_text(encoding="utf-8"))["message"] == "yeni dosya"
        actions.write_result(str(p), False, "ustune yaz", True, {"a": 1})  # varsa keser ve yazar
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["message"] == "ustune yaz" and data["data"] == {"a": 1}
    finally:
        p.unlink(missing_ok=True)


def test_result_file_refuses_hardlink_and_leaves_victim_untouched(tmp_path):
    victim = tmp_path / "kurban.txt"
    victim.write_text("DEGISMEMELI", encoding="utf-8")
    link = tmp_result("m8-hardlink")
    link.unlink(missing_ok=True)
    try:
        os.link(victim, link)
    except OSError:
        pytest.skip("sabit baglanti olusturulamadi")
    try:
        with pytest.raises(ValueError, match="hardlink"):
            actions.write_result(str(link), True, "saldiri")
        assert victim.read_text(encoding="utf-8") == "DEGISMEMELI"
    finally:
        link.unlink(missing_ok=True)


def test_result_file_refuses_symlink(tmp_path):
    victim = tmp_path / "kurban2.txt"
    victim.write_text("DEGISMEMELI", encoding="utf-8")
    link = tmp_result("m8-symlink")
    link.unlink(missing_ok=True)
    try:
        os.symlink(victim, link)
    except OSError:
        pytest.skip("sembolik baglanti yetkisi yok (gelistirici modu kapali)")
    try:
        # 1. katman: yol denetimi (resolve() baglantiyi izler -> hedef gecici dizinde degil -> reddedilir)
        with pytest.raises(ValueError, match="Gecersiz sonuc dosyasi yolu"):
            actions.write_result(str(link), True, "saldiri")
        # 2. katman (derinlemesine savunma): yol denetimi atlansa bile dosya acilisi baglantiyi reddeder
        with pytest.raises(ValueError, match="sade bir dosya degil"):
            hardening.open_result_file(str(link))
        assert victim.read_text(encoding="utf-8") == "DEGISMEMELI"
    finally:
        link.unlink(missing_ok=True)


def test_result_file_detects_swap_between_check_and_open(monkeypatch):
    p = tmp_result("m8-toctou")
    p.write_text("{}", encoding="utf-8")
    real_fstat = os.fstat

    class Fake:
        def __init__(self, st):
            self.st_ino, self.st_dev = st.st_ino + 1, st.st_dev  # farkli dosya gibi

    monkeypatch.setattr(hardening.os, "fstat", lambda fd: Fake(real_fstat(fd)))
    try:
        with pytest.raises(ValueError, match="degistirildi"):
            hardening.open_result_file(str(p))
    finally:
        monkeypatch.undo()
        p.unlink(missing_ok=True)


def test_result_path_outside_temp_still_rejected():
    with pytest.raises(ValueError):
        actions.write_result(r"C:\Windows\auxy-result-x.json", True, "x")


# ---------------- bozuk dosya dayanikliligi ----------------
def test_corrupt_vault_db_gives_clear_error_and_blob_files_survive(tmp_path):
    root = tmp_path / "vault"
    vault = Vault(root, os.urandom(32))
    f = tmp_path / "a.bin"
    f.write_bytes(b"onemli" * 100)
    item = vault.add(f)
    blob = root / f"{item.id}.auxq"
    (root / "vault.db").write_bytes(b"BU BIR SQLITE DOSYASI DEGIL" * 50)
    with pytest.raises(VaultError, match="bozuk"):
        Vault(root, os.urandom(32))  # yeni acilis
    with pytest.raises(VaultError, match="bozuk"):
        vault.list()  # acik kasa
    assert blob.exists()  # sifreli dosya diskte duruyor, kaybolmadi


def test_vault_db_valid_but_missing_table_is_recreated_not_crash(tmp_path):
    root = tmp_path / "vault2"
    root.mkdir()
    sqlite3.connect(root / "vault.db").close()  # bos, gecerli sqlite
    vault = Vault(root, os.urandom(32))
    assert vault.list() == []


def test_corrupt_backup_is_moved_aside_not_lost_or_overwritten():
    f = paths.backup_file()
    f.write_text("{bozuk json", encoding="utf-8")
    assert backup.load() == {}
    aside = list(f.parent.glob("backup.json.bozuk-*"))
    assert len(aside) == 1 and aside[0].read_text(encoding="utf-8") == "{bozuk json"  # kanit korunur
    backup.remember_original("pua", 1)  # yeni kayit eski dosyanin ustune yazmaz
    assert backup.load() == {"pua": 1}
    assert aside[0].exists()


def test_backup_json_valid_but_wrong_shape_is_treated_as_corrupt():
    paths.backup_file().write_text("[1, 2, 3]", encoding="utf-8")
    assert backup.load() == {}
    assert list(paths.backup_file().parent.glob("backup.json.bozuk-*"))


def test_corrupt_scan_history_and_config_do_not_crash():
    from auxy.core import config as cfgmod
    from auxy.core import scan

    paths.scan_history_file().write_text("\x00\x01 bozuk", encoding="utf-8")
    assert scan.load_history() == []
    cfgmod.config_file().write_text("{", encoding="utf-8")
    assert cfgmod.load() == cfgmod.Config()


# ---------------- doctor ----------------
def test_doctor_runs_all_checks_and_never_crashes():
    results = doctor.run_checks()
    names = [r.name for r in results]
    assert any(n.startswith("Python") for n in names) and "Defender servisi" in names and "Kurulum konumu" in names
    assert all(r.status in (doctor.OK, doctor.WARN, doctor.FAIL, doctor.INFO) for r in results)
    ok, warn, fail = doctor.summarize(results)
    assert ok + warn + fail <= len(results)


def test_doctor_isolates_a_failing_check(monkeypatch):
    def boom():
        raise RuntimeError("wmi coktu")

    monkeypatch.setattr(doctor, "CHECKS", (("a", boom), ("b", lambda: doctor.Check("Ikinci", doctor.OK, "var"))))
    results = doctor.run_checks()
    assert results[0].status == doctor.FAIL and "wmi coktu" in results[0].detail
    assert results[1].name == "Ikinci" and results[1].status == doctor.OK  # digeri etkilenmedi


def test_doctor_report_format_and_exit_codes(monkeypatch, capsys):
    results = [doctor.Check("Iyi", doctor.OK, "tamam"), doctor.Check("Orta", doctor.WARN, "dikkat", "su komutu calistir"),
               doctor.Check("Kotu", doctor.FAIL, "bozuk", "onar")]
    text = doctor.format_report(results)
    assert "✔ Iyi" in text and "⚠ Orta" in text and "✘ Kotu" in text and "→ su komutu calistir" in text
    assert "1 tamam, 1 uyarı, 1 hata" in text
    monkeypatch.setattr(doctor, "run_checks", lambda: results)
    assert cli.main(["doctor"]) == 1  # hata varsa cikis kodu 1
    monkeypatch.setattr(doctor, "run_checks", lambda: results[:2])
    assert cli.main(["doctor"]) == 0
    capsys.readouterr()
    cli.main(["doctor", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data[0] == {"name": "Iyi", "status": "ok", "detail": "tamam", "hint": ""}


def test_check_python_warns_for_store_python(monkeypatch):
    monkeypatch.setattr(doctor.sys, "executable", r"C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.12\python.exe")
    c = doctor.check_python()
    assert c.status == doctor.WARN and "sanallaştırır" in c.hint
    monkeypatch.setattr(doctor.sys, "executable", r"C:\Python312\python.exe")
    assert doctor.check_python().status == doctor.OK


def test_check_log_counts_only_recent_errors():
    now = datetime.now()
    old = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    recent = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    f = paths.log_dir() / "auxy.log"
    f.write_text(
        f"{old},123 ERROR eski hata\n{recent},456 INFO bilgi\n{recent},789 ERROR yeni hata bir\n"
        f"{recent},790 CRITICAL AJAN COKTU\n   Traceback satiri\n", encoding="utf-8")
    c = doctor.check_log()[0]
    assert c.status == doctor.WARN and "2 hata" in c.detail and "AJAN COKTU" in c.detail
    f.write_text(f"{old},1 ERROR eski\n", encoding="utf-8")
    assert doctor.check_log()[0].status == doctor.OK


def test_check_vault_states(tmp_path):
    assert doctor.check_vault()[0].detail == "henüz oluşturulmadı"  # kasa yok: olusturmaz
    assert not (paths.home() / "vault").exists() or not (paths.home() / "vault" / "vault.key").exists()
    vault = Vault.default()
    f = tmp_path / "x.bin"
    f.write_bytes(b"x" * 50)
    vault.add(f)
    ok = doctor.check_vault()[0]
    assert ok.status == doctor.OK and "1 kayıt" in ok.detail and "açıyor" in ok.detail
    (vault.root / "vault.key").unlink()
    gone = doctor.check_vault()[0]
    assert gone.status == doctor.FAIL and "import-key" in gone.hint
    assert not (vault.root / "vault.key").exists()  # doctor anahtar URETMEZ (hicbir sey degistirmez)


def test_doctor_does_not_modify_anything():
    before = {p: p.stat().st_mtime_ns for p in paths.home().rglob("*") if p.is_file()}
    doctor.run_checks()
    after = {p: p.stat().st_mtime_ns for p in paths.home().rglob("*") if p.is_file()}
    new = set(after) - set(before)
    assert all(p.name in ("auxy.log",) or p.parent.name == "logs" for p in new)  # yalnizca gunluk dosyasi olusabilir
    assert all(before[p] == after[p] for p in before if p.name != "auxy.log")
