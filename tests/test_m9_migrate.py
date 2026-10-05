import hashlib
import os
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import doctor, migrate
from auxy.core.vault import Vault


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Sahte LOCALAPPDATA: gercek Packages/AuxySecurity dizinlerine dokunulmaz."""
    local = tmp_path / "Local"
    legacy = local / "Packages" / "PythonSoftwareFoundation.Python.3.12_abc" / "LocalCache" / "Local" / "AuxySecurity"
    legacy.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "ayri-veri"))  # log dizini; hedefle karismasin
    monkeypatch.setenv("AUXY_INSTANCE", "_m9mig")
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield type("E", (), {"local": local, "legacy": legacy, "target": local / "AuxySecurity"})()
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def fill_legacy(legacy: Path):
    (legacy / "vault").mkdir()
    (legacy / "vault" / "vault.db").write_bytes(b"db")
    (legacy / "vault" / "vault.key").write_bytes(b"anahtar")
    (legacy / "vault" / "x.auxq").write_bytes(b"blob" * 100)
    (legacy / "backup.json").write_text('{"pua": 1}', encoding="utf-8")
    (legacy / "config.json").write_text("{}", encoding="utf-8")
    (legacy / "logs").mkdir()
    (legacy / "logs" / "auxy.log").write_text("log")


def test_find_legacy_dirs_only_non_empty(env):
    assert migrate.find_legacy_dirs() == []  # bos dizin sayilmaz
    fill_legacy(env.legacy)
    assert migrate.find_legacy_dirs() == [env.legacy]


def test_plan_and_migrate_copies_without_deleting_source(env):
    fill_legacy(env.legacy)
    plan = migrate.pending_plan()
    assert plan.needed and set(plan.to_copy) == {"vault", "backup.json", "config.json"} and plan.blocked == ()
    done = migrate.migrate(plan)
    assert all("kopyalandı" in d for d in done)
    assert (env.target / "vault" / "x.auxq").read_bytes() == b"blob" * 100
    assert (env.target / "backup.json").read_text(encoding="utf-8") == '{"pua": 1}'
    assert not (env.target / "logs").exists()  # gunluk tasinmaz
    assert (env.legacy / "vault" / "x.auxq").exists() and (env.legacy / "backup.json").exists()  # eski veri SILINMEDI
    assert str(env.legacy) in (env.target / migrate.MARKER).read_text(encoding="utf-8")
    assert migrate.pending_plan() is None  # artik tasinacak bir sey yok


def test_never_overwrites_existing_target_items(env):
    fill_legacy(env.legacy)
    env.target.mkdir()
    (env.target / "backup.json").write_text('{"cfa": 0}', encoding="utf-8")  # kullanicinin yeni verisi
    plan = migrate.pending_plan()
    assert "backup.json" in plan.blocked and "backup.json" not in plan.to_copy
    migrate.migrate(plan)
    assert (env.target / "backup.json").read_text(encoding="utf-8") == '{"cfa": 0}'  # ezilmedi
    assert (env.target / "vault" / "vault.db").exists()  # digerleri kopyalandi


def test_migration_continues_after_item_error_and_reports(env, monkeypatch):
    fill_legacy(env.legacy)
    real = migrate.shutil.copy2

    def flaky(src, dst, *a, **k):
        if Path(src).name == "backup.json":
            raise PermissionError("kilitli")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(migrate.shutil, "copy2", flaky)
    done = migrate.migrate(migrate.pending_plan())
    assert any("backup.json: HATA" in d and "kilitli" in d for d in done)
    assert (env.target / "vault" / "vault.db").exists() and (env.target / "config.json").exists()


def test_no_legacy_means_no_plan(env):
    assert migrate.pending_plan() is None
    assert cli.main(["migrate-data"]) == 0


def test_cli_dry_run_then_yes(env, capsys):
    fill_legacy(env.legacy)
    assert cli.main(["migrate-data"]) == 0
    out = capsys.readouterr().out
    assert "Kopyalanacak" in out and "--yes" in out and not env.target.exists()  # --yes olmadan DEGISMEZ
    assert cli.main(["migrate-data", "--yes"]) == 0
    assert (env.target / "vault" / "vault.db").exists()


def test_doctor_warns_about_pending_legacy_data(env):
    assert doctor.check_legacy_data().status == doctor.INFO
    fill_legacy(env.legacy)
    c = doctor.check_legacy_data()
    assert c.status == doctor.WARN and "migrate-data" in c.hint and "vault" in c.detail


def test_real_vault_survives_migration_with_dpapi_key(env, tmp_path, monkeypatch):
    """Gercek DPAPI anahtariyla: eski dizinde kasa olustur -> tasi -> yeni dizinde dosya geri yuklenebilsin."""
    data = os.urandom(3000)
    f = tmp_path / "supheli.exe"
    f.write_bytes(data)
    monkeypatch.setenv("AUXY_HOME", str(env.legacy))  # kasa "eski" dizinde olussun
    item = Vault.default().add(f, "tasima testi")
    plan = migrate.pending_plan()
    assert plan and "vault" in plan.to_copy
    migrate.migrate(plan)
    monkeypatch.setenv("AUXY_HOME", str(env.target))  # artik yeni dizin
    out = Vault.default().restore(item.id)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()
