import hashlib
import io
import os
import struct
from pathlib import Path

import pytest

from auxy.core import vault as v
from auxy.core.vault import Vault, VaultError

KEY = bytes(range(32))
CHUNK = 64  # testlerde kucuk parca: sinir durumlari ucuz


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path / "home" / "vault", KEY, chunk_size=CHUNK)


@pytest.fixture
def files(tmp_path):
    d = tmp_path / "user"
    d.mkdir()
    return d


def make(files: Path, name: str, data: bytes) -> Path:
    p = files / name
    p.write_bytes(data)
    return p


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- sifreleme ----
@pytest.mark.parametrize("n", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, CHUNK * 3, CHUNK * 3 + 7])
def test_encrypt_decrypt_roundtrip_boundaries(n):
    data = os.urandom(n)
    enc = io.BytesIO()
    digest, size = v.encrypt_stream(io.BytesIO(data), enc, KEY, CHUNK)
    assert (digest, size) == (sha(data), n)
    blob = enc.getvalue()
    out = io.BytesIO()
    assert v.decrypt_stream(io.BytesIO(blob), out, KEY, len(blob), CHUNK) == sha(data)
    assert out.getvalue() == data


def encrypt(data: bytes) -> bytes:
    enc = io.BytesIO()
    v.encrypt_stream(io.BytesIO(data), enc, KEY, CHUNK)
    return enc.getvalue()


def test_ciphertext_does_not_contain_plaintext():
    marker = b"ASLA-DUZ-METIN-OLARAK-GORUNMEMELI" * 5
    assert marker[:20] not in encrypt(marker)


def test_same_plaintext_encrypts_differently():
    assert encrypt(b"x" * 100) != encrypt(b"x" * 100)  # rastgele on ek


def decrypt(blob: bytes, key=KEY):
    return v.decrypt_stream(io.BytesIO(blob), io.BytesIO(), key, len(blob), CHUNK)


def test_tampered_byte_is_detected():
    blob = bytearray(encrypt(os.urandom(300)))
    blob[40] ^= 0x01
    with pytest.raises(VaultError, match="doğrulanamadı"):
        decrypt(bytes(blob))


def test_truncation_at_chunk_boundary_is_detected():
    blob = encrypt(os.urandom(CHUNK * 3))
    first = v.HEADER_LEN + 4 + CHUNK + v.TAG  # ilk parca sonu
    with pytest.raises(VaultError):
        decrypt(blob[:first])  # son-parca bayragi uyusmaz


def test_appended_data_is_detected():
    with pytest.raises(VaultError):
        decrypt(encrypt(os.urandom(100)) + b"\x00" * 10)


def test_wrong_key_and_bad_header():
    blob = encrypt(b"gizli")
    with pytest.raises(VaultError):
        decrypt(blob, key=bytes(32))
    with pytest.raises(VaultError, match="tanınmıyor"):
        decrypt(b"YANLIS" + blob[6:])


def test_chunk_reorder_is_detected():
    blob = encrypt(os.urandom(CHUNK * 2 + 10))
    step = 4 + CHUNK + v.TAG
    h = v.HEADER_LEN
    c0, c1, rest = blob[h:h + step], blob[h + step:h + 2 * step], blob[h + 2 * step:]
    with pytest.raises(VaultError):
        decrypt(blob[:h] + c1 + c0 + rest)


# ---- kasa islemleri ----
def test_add_removes_original_and_restore_is_bit_identical(vault, files):
    data = os.urandom(CHUNK * 5 + 3)
    p = make(files, "supheli.exe", data)
    mtime = p.stat().st_mtime
    item = vault.add(p, "test")
    assert not p.exists()
    assert item.sha256 == sha(data) and item.size == len(data)
    blob = vault.root / f"{item.id}.auxq"
    assert blob.exists() and data[:32] not in blob.read_bytes()
    out = vault.restore(item.id)
    assert out == p.resolve() and out.read_bytes() == data
    assert abs(out.stat().st_mtime - mtime) < 2
    assert vault.list() == [] and not blob.exists()


def test_restore_refuses_existing_target_unless_overwrite(vault, files):
    p = make(files, "a.bin", b"1" * 100)
    item = vault.add(p)
    make(files, "a.bin", b"baska")
    with pytest.raises(VaultError, match="zaten var"):
        vault.restore(item.id)
    assert vault.get(item.id)  # kayit duruyor
    vault.restore(item.id, overwrite=True)
    assert p.read_bytes() == b"1" * 100


def test_restore_to_other_path_creates_dirs(vault, files):
    item = vault.add(make(files, "a.bin", b"veri"))
    out = vault.restore(item.id, files / "yeni" / "klasor" / "b.bin")
    assert out.read_bytes() == b"veri"


def test_empty_file(vault, files):
    item = vault.add(make(files, "bos.txt", b""))
    assert item.size == 0
    assert vault.restore(item.id).read_bytes() == b""


def test_delete_permanently(vault, files):
    item = vault.add(make(files, "x.bin", b"x"))
    vault.delete(item.id)
    assert vault.list() == [] and not (vault.root / f"{item.id}.auxq").exists()
    with pytest.raises(VaultError):
        vault.get(item.id)


def test_list_newest_first(vault, files):
    a = vault.add(make(files, "a", b"1"))
    b = vault.add(make(files, "b", b"2"))
    assert [i.id for i in vault.list()] == [b.id, a.id]


def test_failed_original_delete_rolls_back(vault, files, monkeypatch):
    p = make(files, "kilitli.bin", b"data" * 50)

    def boom(path):
        raise PermissionError("kullanimda")

    monkeypatch.setattr(v.os, "remove", boom)
    with pytest.raises(VaultError, match="silinemedi"):
        vault.add(p)
    assert p.exists() and vault.list() == []
    assert not list(vault.root.glob("*.auxq")) and not list(vault.root.glob("*.tmp"))


def test_unreadable_file_leaves_no_residue(vault, files, monkeypatch):
    p = make(files, "x.bin", b"abc")
    real_open = open

    def fake_open(path, mode="r", *a, **k):
        if str(path) == str(p.resolve()) and "r" in mode:
            raise PermissionError("erisim reddedildi")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    with pytest.raises(VaultError, match="erişim"):
        vault.add(p)
    assert not list(vault.root.glob("*.tmp")) and vault.list() == []


def test_corrupt_blob_fails_restore_and_keeps_record(vault, files):
    item = vault.add(make(files, "a.bin", os.urandom(200)))
    blob = vault.root / f"{item.id}.auxq"
    raw = bytearray(blob.read_bytes())
    raw[30] ^= 0xFF
    blob.write_bytes(bytes(raw))
    with pytest.raises(VaultError):
        vault.restore(item.id)
    assert vault.get(item.id)
    assert not (files / "a.bin").exists() and not list(files.glob("*.auxy-restore"))


def test_missing_blob(vault, files):
    item = vault.add(make(files, "a.bin", b"abc"))
    (vault.root / f"{item.id}.auxq").unlink()
    with pytest.raises(VaultError, match="bulunamadı"):
        vault.restore(item.id)


# ---- koruma kurallari ----
def test_rejects_missing_dir_and_protected(vault, files):
    with pytest.raises(VaultError, match="bulunamadı"):
        vault.add(files / "yok.exe")
    with pytest.raises(VaultError, match="klasör"):
        vault.add(files)
    sysfile = Path(os.environ["SystemRoot"]) / "System32" / "notepad.exe"
    with pytest.raises(VaultError, match="Korumalı konum"):
        vault.add(sysfile)
    own = Path(v.__file__)
    with pytest.raises(VaultError, match="Korumalı konum"):
        vault.add(own)


def test_rejects_vault_internal_files(vault, files):
    item = vault.add(make(files, "a.bin", b"abc"))
    with pytest.raises(VaultError, match="Korumalı konum"):
        vault.add(vault.root / f"{item.id}.auxq")


def test_rejects_symlink(vault, files):
    target = make(files, "gercek.bin", b"x")
    link = files / "link.bin"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("sembolik baglanti olusturma yetkisi yok")
    with pytest.raises(VaultError, match="Sembolik"):
        vault.add(link)
    assert target.exists()


# ---- DPAPI anahtar ----
def test_dpapi_key_persists_and_is_not_plaintext(tmp_path):
    kf = tmp_path / "vault.key"
    k1 = v.load_or_create_key(kf)
    assert len(k1) == 32 and k1 not in kf.read_bytes()
    assert v.load_or_create_key(kf) == k1


def test_dpapi_corrupt_key_file_gives_clear_error(tmp_path):
    kf = tmp_path / "vault.key"
    kf.write_bytes(b"bozuk" * 20)
    with pytest.raises(VaultError, match="anahtarı çözülemedi"):
        v.load_or_create_key(kf)


def test_header_constants():
    assert v.HEADER_LEN == 13
    assert struct.calcsize(">I") == 4
