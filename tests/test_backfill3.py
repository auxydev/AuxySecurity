import hashlib
import os
import time
from pathlib import Path

import customtkinter as ctk
import pytest

from auxy import __main__ as cli
from auxy.core import paths
from auxy.core import vault as v
from auxy.core.vault import Vault, VaultError

REAL_SLEEP = time.sleep
PW = "doğru-parola-123"


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


@pytest.fixture
def outside(tmp_path):
    d = tmp_path / "usb"
    d.mkdir()
    return d


def make(d: Path, name: str, data: bytes) -> Path:
    p = d / name
    p.write_bytes(data)
    return p


# ---------------- anahtar yedegi: sifreleme ----------------
def test_key_backup_roundtrip_and_randomness():
    key = os.urandom(32)
    a, b = v.encrypt_key_backup(key, PW), v.encrypt_key_backup(key, PW)
    assert a != b  # rastgele tuz + nonce
    assert v.decrypt_key_backup(a, PW) == key and v.decrypt_key_backup(b, PW) == key
    assert key not in a  # duz anahtar dosyada gorunmez


def test_key_backup_wrong_password_tamper_and_format():
    key = os.urandom(32)
    blob = v.encrypt_key_backup(key, PW)
    with pytest.raises(VaultError, match="Parola yanlış"):
        v.decrypt_key_backup(blob, "baska-parola-999")
    bad = bytearray(blob)
    bad[-3] ^= 1
    with pytest.raises(VaultError, match="Parola yanlış ya da yedek dosyası bozulmuş"):
        v.decrypt_key_backup(bytes(bad), PW)
    with pytest.raises(VaultError, match="anahtar yedeği değil"):
        v.decrypt_key_backup(b"BASKA" + blob[5:], PW)
    with pytest.raises(VaultError, match="anahtar yedeği değil"):
        v.decrypt_key_backup(b"kisa", PW)


def test_short_password_rejected():
    with pytest.raises(VaultError, match="en az"):
        v.encrypt_key_backup(os.urandom(32), "kisa")


# ---------------- export kurallari ----------------
def test_export_writes_outside_and_refuses_inside_data_dir(outside):
    vault = Vault.default()
    dest = vault.export_key_file(outside / "yedek.auxkey", PW)
    assert dest.exists() and vault._key not in dest.read_bytes()
    with pytest.raises(VaultError, match="DIŞINA"):
        vault.export_key_file(vault.root / "yedek.auxkey", PW)  # kasanin icine
    with pytest.raises(VaultError, match="DIŞINA"):
        vault.export_key_file(paths.home() / "yedek.auxkey", PW)  # veri dizininin icine
    with pytest.raises(VaultError, match="en az"):
        vault.export_key_file(outside / "y2.auxkey", "kisa")
    assert not (outside / "y2.auxkey").exists()


# ---------------- profil kaybi senaryosu (gercek DPAPI) ----------------
def test_lost_key_is_recovered_from_backup(outside):
    data = os.urandom(5000)
    f = make(outside, "supheli.exe", data)
    vault = Vault.default()
    item = vault.add(f, "test")
    backup_file = vault.export_key_file(outside / "yedek.auxkey", PW)
    # profil kaybi benzeri: DPAPI ile korunan anahtar dosyasi yok oluyor
    (vault.root / "vault.key").unlink()
    broken = Vault.default()  # YENI rastgele anahtar uretir: eski dosyalar acilamaz
    assert broken._key != vault._key
    with pytest.raises(VaultError):
        broken.restore(item.id)
    # yedekten geri yukle
    msg = v.import_key_file(backup_file, PW)
    assert "doğrulandı" in msg
    healed = Vault.default()
    out = healed.restore(item.id)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()


def test_import_refuses_key_that_does_not_open_existing_items(outside, tmp_path, monkeypatch):
    # baska bir kasanin yedegi
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "baska_home"))
    other = Vault.default()
    foreign = other.export_key_file(outside / "baska.auxkey", PW)
    # asil kasa
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    vault = Vault.default()
    item = vault.add(make(outside, "a.bin", b"onemli" * 100), "t")
    with pytest.raises(VaultError, match="açmıyor"):
        v.import_key_file(foreign, PW)
    # mevcut anahtara dokunulmadi: kasa hala calisiyor
    assert Vault.default().restore(item.id).read_bytes() == b"onemli" * 100


def test_import_into_empty_vault_works_with_note(outside):
    vault = Vault.default()
    backup_file = vault.export_key_file(outside / "yedek.auxkey", PW)
    msg = v.import_key_file(backup_file, PW)
    assert "boş" in msg


def test_import_wrong_password_or_missing_file(outside):
    vault = Vault.default()
    backup_file = vault.export_key_file(outside / "yedek.auxkey", PW)
    with pytest.raises(VaultError, match="Parola yanlış"):
        v.import_key_file(backup_file, "yanlis-parola-1")
    with pytest.raises(VaultError, match="okunamadı"):
        v.import_key_file(outside / "yok.auxkey", PW)


# ---------------- add_many ----------------
def test_add_many_partial_failures(outside):
    vault = Vault.default()
    good1, good2 = make(outside, "a.exe", b"1" * 50), make(outside, "b.dll", b"2" * 50)
    sysfile = Path(os.environ["SystemRoot"]) / "System32" / "notepad.exe"
    added, errors = vault.add_many([good1, outside / "yok.txt", sysfile, good2], "toplu")
    assert [i.name for i in added] == ["a.exe", "b.dll"]
    assert len(errors) == 2 and any("yok.txt" in e for e in errors) and any("Korumalı" in e for e in errors)
    assert not good1.exists() and not good2.exists() and sysfile.exists()


# ---------------- CLI ----------------
def test_cli_vault_multi_add_export_import(outside, monkeypatch, capsys):
    f1, f2 = make(outside, "a.exe", b"1" * 20), make(outside, "b.exe", b"2" * 20)
    assert cli.main(["vault", "add", str(f1), str(f2), "--reason", "cli"]) == 0
    assert not f1.exists() and not f2.exists()
    monkeypatch.setattr(cli, "_ask_password", lambda confirm: PW)
    dest = outside / "cli.auxkey"
    assert cli.main(["vault", "export-key", str(dest)]) == 0
    assert dest.exists()
    # anahtar kaybi + CLI ile geri yukleme (kasa anahtari olmadan da calismali)
    (paths.home() / "vault" / "vault.key").unlink()
    assert cli.main(["vault", "import-key", str(dest)]) == 0
    assert "geri yüklendi" in capsys.readouterr().out
    assert cli.main(["vault", "list"]) == 0


def test_cli_vault_add_reports_errors(outside, capsys):
    good = make(outside, "a.exe", b"1" * 20)
    rc = cli.main(["vault", "add", str(good), str(outside / "yok.exe")])
    err = capsys.readouterr().err
    assert rc == 1 and "yok.exe" in err and not good.exists()


def test_cli_export_requires_target_and_password_mismatch(outside, monkeypatch, capsys):
    assert cli.main(["vault", "export-key"]) == 2
    assert cli.main(["vault", "import-key"]) == 2
    import getpass

    answers = iter(["parola-bir-123", "parola-iki-456"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    assert cli.main(["vault", "export-key", str(outside / "x.auxkey")]) == 1
    assert "uyuşmuyor" in capsys.readouterr().err and not (outside / "x.auxkey").exists()


# ---------------- GUI ----------------
def _toplevel(app):
    return next((w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)), None)


def _find(widget, cls):
    stack, found = [widget], []
    while stack:
        w = stack.pop()
        if isinstance(w, cls):
            found.append(w)
        stack.extend(w.winfo_children())
    return found


def test_password_dialog_validation_and_result(app):
    from auxy.gui import vault_page

    steps = {"n": 0}

    def drive():
        dlg = _toplevel(app)
        if dlg is None:
            app.after(50, drive)
            return
        entries = sorted(_find(dlg, ctk.CTkEntry), key=lambda e: e.winfo_y())
        ok_btn = next(b for b in _find(dlg, ctk.CTkButton) if b.cget("text") == "Tamam")
        steps["n"] += 1
        if steps["n"] == 1:  # kisa parola -> hata, kutu acik kalir
            entries[0].insert(0, "kisa")
            entries[1].insert(0, "kisa")
            ok_btn.invoke()
            steps["err1"] = [w.cget("text") for w in _find(dlg, ctk.CTkLabel)]
            for e in entries:
                e.delete(0, "end")
            entries[0].insert(0, "yeterince-uzun-1")
            entries[1].insert(0, "baska-bir-sey-22")  # uyusmuyor
            ok_btn.invoke()
            steps["err2"] = [w.cget("text") for w in _find(dlg, ctk.CTkLabel)]
            entries[1].delete(0, "end")
            entries[1].insert(0, "yeterince-uzun-1")
            ok_btn.invoke()  # gecerli: kapanir

    app.after(150, drive)
    pw = vault_page.ask_password(app, "Test", confirm=True)
    assert pw == "yeterince-uzun-1"
    assert any("En az" in t for t in steps["err1"]) and any("uyuşmuyor" in t for t in steps["err2"])


def test_password_dialog_cancel_returns_none(app):
    from auxy.gui import vault_page

    def drive():
        dlg = _toplevel(app)
        if dlg is None:
            app.after(50, drive)
            return
        next(b for b in _find(dlg, ctk.CTkButton) if b.cget("text") == "İptal").invoke()

    app.after(150, drive)
    assert vault_page.ask_password(app, "Test", confirm=False) is None


def pump(a, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if cond():
            return True
        REAL_SLEEP(0.05)
    return False


def test_gui_add_folder_and_multi_select(app, outside, monkeypatch):
    from auxy.gui import vault_page

    vault_page._vault = None  # test AUXY_HOME'una gore yeniden ac
    page = app.pages["quarantine"]
    monkeypatch.setattr(vault_page.messagebox, "askyesno", lambda *a, **k: True)
    folder = outside / "indirilen"
    folder.mkdir()
    for i in range(3):
        make(folder, f"f{i}.exe", bytes([i]) * 30)
    (folder / "alt").mkdir()
    make(folder / "alt", "derin.exe", b"d" * 30)  # alt klasor dahil DEGIL
    monkeypatch.setattr(vault_page.filedialog, "askdirectory", lambda **k: str(folder))
    page.add_folder()
    assert pump(app, lambda: "3 dosya kasaya alındı" in page.status.cget("text"))
    assert (folder / "alt" / "derin.exe").exists() and not list(folder.glob("*.exe"))
    # coklu dosya secimi + hata ozeti
    g = make(outside, "x.exe", b"x" * 10)
    monkeypatch.setattr(vault_page.filedialog, "askopenfilenames", lambda **k: [str(g), str(outside / "yok.exe")])
    page.add_file()
    assert pump(app, lambda: "1 dosya kasaya alındı" in page.status.cget("text"))
    assert "yok.exe" in page.status.cget("text")
    vault_page._vault = None


def test_gui_key_export_import_flow(app, outside, monkeypatch):
    from auxy.gui import vault_page

    vault_page._vault = None
    page = app.pages["quarantine"]
    dest = outside / "gui.auxkey"
    monkeypatch.setattr(vault_page.filedialog, "asksaveasfilename", lambda **k: str(dest))
    monkeypatch.setattr(vault_page, "ask_password", lambda parent, title, confirm=False: PW)
    page.export_key()
    assert pump(app, lambda: dest.exists() and "Yedek yazıldı" in page.status.cget("text"))
    monkeypatch.setattr(vault_page.filedialog, "askopenfilename", lambda **k: str(dest))
    page.import_key()
    assert pump(app, lambda: "Anahtar geri yüklendi" in page.status.cget("text"))
    # iptal edilen parola kutusu: hicbir sey yazilmaz
    dest2 = outside / "iptal.auxkey"
    monkeypatch.setattr(vault_page.filedialog, "asksaveasfilename", lambda **k: str(dest2))
    monkeypatch.setattr(vault_page, "ask_password", lambda parent, title, confirm=False: None)
    page.export_key()
    app.update()
    assert not dest2.exists()
    vault_page._vault = None
