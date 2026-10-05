"""Karantina kasasi: supheli dosyayi AES-256-GCM ile sifreleyip izole eder, geri yukler.

Dosya bicimi (.auxq):
  baslik  = b"AUXQ" + surum(1 bayt) + on_ek(8 bayt rastgele)            -> 13 bayt
  parca_i = uzunluk(4 bayt, buyuk-endian) + sifreli_metin(duz_parca + 16 bayt etiket)
  nonce_i = on_ek + i(4 bayt);  AAD = baslik + (b"\\x01" son parca / b"\\x00" degil)
Parcali yapi buyuk dosyalari bellege yuklemez; "son parca" bayragi kesilmis dosyayi yakalar.

Anahtar: rastgele 256 bit, Windows DPAPI (kullanici kapsami) ile korunup vault.key'de saklanir.
Metaveri: SQLite (vault.db). Orijinal dosya, kasada dogrulandiktan SONRA silinir.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import struct
import sys
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from auxy.core import paths
from auxy.core.log import get_logger
from auxy.core.service import AuxyError

MAGIC = b"AUXQ"
VERSION = b"\x01"
CHUNK_SIZE = 4 * 1024 * 1024
TAG = 16
HEADER_LEN = len(MAGIC) + 1 + 8
_REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


class VaultError(AuxyError):
    pass


@dataclass(frozen=True)
class VaultItem:
    id: str
    original_path: str
    name: str
    sha256: str
    size: int
    quarantined_at: str
    reason: str
    mtime: float


# ---------------- sifreleme ----------------
def _nonce(prefix: bytes, index: int) -> bytes:
    return prefix + struct.pack(">I", index)


def encrypt_stream(src, dst, key: bytes, chunk_size: int | None = None) -> tuple[str, int]:
    """src (rb) -> dst (wb). (sha256 hex, duz boyut) dondurur."""
    chunk_size = chunk_size or CHUNK_SIZE
    aes = AESGCM(key)
    prefix = os.urandom(8)
    header = MAGIC + VERSION + prefix
    dst.write(header)
    sha, total, index = hashlib.sha256(), 0, 0
    current = src.read(chunk_size)
    while True:
        nxt = src.read(chunk_size) if len(current) == chunk_size else b""
        final = not nxt
        sha.update(current)
        total += len(current)
        ct = aes.encrypt(_nonce(prefix, index), current, header + (b"\x01" if final else b"\x00"))
        dst.write(struct.pack(">I", len(ct)) + ct)
        if final:
            return sha.hexdigest(), total
        current, index = nxt, index + 1


def decrypt_stream(src, dst, key: bytes, size: int, chunk_size: int | None = None) -> str:
    """src (rb, toplam `size` bayt) -> dst (wb). Duz metnin sha256'sini dondurur; bozuksa VaultError."""
    chunk_size = chunk_size or CHUNK_SIZE
    header = src.read(HEADER_LEN)
    if len(header) != HEADER_LEN or header[:4] != MAGIC or header[4:5] != VERSION:
        raise VaultError("Kasa dosyası biçimi tanınmıyor (bozuk ya da farklı sürüm).")
    prefix = header[5:]
    aes, sha, index = AESGCM(key), hashlib.sha256(), 0
    pos = HEADER_LEN
    while True:
        raw_len = src.read(4)
        if len(raw_len) != 4:
            raise VaultError("Kasa dosyası kesilmiş.")
        (n,) = struct.unpack(">I", raw_len)
        if n < TAG or n > chunk_size + TAG:
            raise VaultError("Kasa dosyası bozuk (geçersiz parça boyutu).")
        ct = src.read(n)
        if len(ct) != n:
            raise VaultError("Kasa dosyası kesilmiş.")
        pos += 4 + n
        final = pos == size
        try:
            pt = aes.decrypt(_nonce(prefix, index), ct, header + (b"\x01" if final else b"\x00"))
        except InvalidTag:
            raise VaultError("Kasa dosyası doğrulanamadı: değiştirilmiş, bozulmuş ya da anahtar yanlış.") from None
        sha.update(pt)
        dst.write(pt)
        if final:
            return sha.hexdigest()
        index += 1


# ---------------- anahtar (DPAPI) ----------------
def load_or_create_key(key_file: Path) -> bytes:
    import win32crypt

    if key_file.exists():
        try:
            return win32crypt.CryptUnprotectData(key_file.read_bytes(), None, None, None, 0)[1]
        except Exception as exc:
            raise VaultError(
                "Kasa anahtarı çözülemedi (farklı Windows kullanıcısı ya da bozuk anahtar dosyası). "
                "Kasadaki dosyalar bu anahtar olmadan açılamaz."
            ) from exc
    key = os.urandom(32)
    key_file.write_bytes(win32crypt.CryptProtectData(key, "AuxySecurity vault key", None, None, None, 0))
    return key


# ---------------- anahtar yedegi (parola korumali) ----------------
KEY_EXPORT_MAGIC = b"AUXK1"
MIN_PASSWORD_LEN = 8
_SCRYPT = dict(n=2**15, r=8, p=1)  # ~32 MB bellek, ~0.1 sn: kaba kuvveti yavaslatir


def _kdf(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, **_SCRYPT).derive(password.encode("utf-8"))


def encrypt_key_backup(key: bytes, password: str) -> bytes:
    """Kasa anahtarini parolayla sifreler. Bicim: magic(5) + tuz(16) + nonce(12) + sifreli(32+16)."""
    if len(password) < MIN_PASSWORD_LEN:
        raise VaultError(f"Parola en az {MIN_PASSWORD_LEN} karakter olmalı.")
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(_kdf(password, salt)).encrypt(nonce, key, KEY_EXPORT_MAGIC + salt)
    return KEY_EXPORT_MAGIC + salt + nonce + ct


def decrypt_key_backup(blob: bytes, password: str) -> bytes:
    head = len(KEY_EXPORT_MAGIC)
    if len(blob) < head + 16 + 12 + 16 or blob[:head] != KEY_EXPORT_MAGIC:
        raise VaultError("Bu bir AuxySecurity anahtar yedeği değil (ya da bozuk).")
    salt, nonce, ct = blob[head:head + 16], blob[head + 16:head + 28], blob[head + 28:]
    try:
        key = AESGCM(_kdf(password, salt)).decrypt(nonce, ct, KEY_EXPORT_MAGIC + salt)
    except InvalidTag:
        raise VaultError("Parola yanlış ya da yedek dosyası bozulmuş.") from None
    if len(key) != 32:
        raise VaultError("Yedekteki anahtar geçersiz.")
    return key


def save_key(key_file: Path, key: bytes) -> None:
    import win32crypt

    key_file.write_bytes(win32crypt.CryptProtectData(key, "AuxySecurity vault key", None, None, None, 0))


# ---------------- koruma kurallari ----------------
def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _protected_roots(vault_root: Path) -> list[tuple[Path, str]]:
    roots = [
        (Path(os.environ.get("SystemRoot", r"C:\Windows")), "Windows sistem dizini"),
        (Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows Defender",
         "Defender dizini"),
        (vault_root, "karantina kasası"),
        (paths.home(), "AuxySecurity veri dizini"),
        (Path(__file__).resolve().parents[1], "AuxySecurity uygulama dosyaları"),
        (Path(sys.prefix), "Python ortamı"),
    ]
    return [(p.resolve(), why) for p, why in roots]


def check_allowed(path: Path, vault_root: Path) -> Path:
    """Dosya karantinaya alinabilir mi? Degilse VaultError. Cozumlenmis yolu dondurur."""
    p = Path(path)
    if not p.exists():
        raise VaultError(f"Dosya bulunamadı: {p}")
    if p.is_symlink() or (os.stat(p, follow_symlinks=False).st_file_attributes & _REPARSE):
        raise VaultError("Sembolik bağlantı / yeniden ayrıştırma noktası karantinaya alınamaz.")
    if not p.is_file():
        raise VaultError("Yalnızca dosyalar karantinaya alınabilir (klasör değil).")
    resolved = p.resolve()
    for root, why in _protected_roots(vault_root):
        if _is_under(resolved, root):
            raise VaultError(f"Korumalı konum ({why}); bu dosya karantinaya alınamaz: {resolved}")
    return resolved


# ---------------- kasa ----------------
class Vault:
    def __init__(self, root: Path, key: bytes, chunk_size: int | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._key = key
        self._chunk = chunk_size
        self._db = self.root / "vault.db"
        self._log = get_logger()
        with closing(self._connect()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, original_path TEXT NOT NULL,"
                " name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,"
                " quarantined_at TEXT NOT NULL, reason TEXT NOT NULL, mtime REAL NOT NULL)"
            )

    @classmethod
    def default(cls) -> Vault:
        root = paths.home() / "vault"
        root.mkdir(parents=True, exist_ok=True)
        return cls(root, load_or_create_key(root / "vault.key"))

    # ---- anahtar yedegi ----
    def export_key_file(self, dest: str | Path, password: str) -> Path:
        """Anahtari parolayla sifreleyip DISARI yazar. Kasanin/veri dizininin icine yazilamaz
        (kasa silinirse yedek de gitmesin)."""
        dest = Path(dest).resolve()
        for protected in (self.root.resolve(), paths.home().resolve()):
            if _is_under(dest, protected):
                raise VaultError("Yedek, AuxySecurity veri dizininin DIŞINA (örn. USB bellek) kaydedilmeli.")
        blob = encrypt_key_backup(self._key, password)
        if decrypt_key_backup(blob, password) != self._key:  # yazmadan once kendini dogrula
            raise VaultError("Yedek doğrulanamadı; yazılmadı.")
        dest.write_bytes(blob)
        self._log.info("KASA anahtar yedegi yazildi: %s", dest)
        return dest

    def verify_key(self, key: bytes) -> bool | None:
        """Verilen anahtar kasadaki ilk kaydi acabiliyor mu? Kayit yoksa None (dogrulanamaz)."""
        items = self.list()
        if not items:
            return None
        item = items[0]
        blob = self._blob(item.id)

        class _Null:
            def write(self, _b):
                return None

        try:
            with open(blob, "rb") as f:
                return decrypt_stream(f, _Null(), key, blob.stat().st_size, self._chunk) == item.sha256
        except (VaultError, OSError):
            return False

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._db, timeout=10)
        try:
            db.execute("SELECT count(*) FROM sqlite_master").fetchone()  # bozuk dosyayi burada yakala
        except sqlite3.DatabaseError as exc:
            db.close()
            raise VaultError(
                "Kasa veritabanı (vault.db) bozuk ya da okunamıyor. Şifreli dosyalar (.auxq) diskte duruyor "
                f"ama kayıt listesi okunamıyor: {exc}") from exc
        return db

    def _blob(self, item_id: str) -> Path:
        return self.root / f"{item_id}.auxq"

    # ---- islemler ----
    def add(self, path: str | Path, reason: str = "Elle eklendi") -> VaultItem:
        src_path = check_allowed(Path(path), self.root)
        item_id = uuid.uuid4().hex
        blob, tmp = self._blob(item_id), self._blob(item_id).with_suffix(".tmp")
        try:
            st = src_path.stat()
            try:
                with open(src_path, "rb") as src, open(tmp, "wb") as dst:
                    sha, size = encrypt_stream(src, dst, self._key, self._chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
            except PermissionError as exc:
                raise VaultError(
                    f"Dosyaya erişim reddedildi ya da dosya kullanımda: {src_path}") from exc
            os.replace(tmp, blob)
            self._verify(blob, sha)  # silmeden once kasadaki kopyayi dogrula
            item = VaultItem(item_id, str(src_path), src_path.name, sha, size,
                             datetime.now().isoformat(timespec="seconds"), reason, st.st_mtime)
            with closing(self._connect()) as db, db:
                db.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)", tuple(item.__dict__.values()))
            try:
                os.remove(src_path)
            except OSError as exc:
                self._drop(item_id)  # silinemediyse geri al: dosya kullaniliyor olabilir
                raise VaultError(f"Orijinal dosya silinemedi (kullanımda olabilir): {src_path}") from exc
        except BaseException:
            tmp.unlink(missing_ok=True)
            if not self._exists(item_id):
                blob.unlink(missing_ok=True)
            raise
        self._log.info("KASA ekle: %s (%s, %d bayt, sha256=%s)", src_path, reason, size, sha[:12])
        return item

    def _verify(self, blob: Path, expected_sha: str) -> None:
        class _Null:
            def write(self, _b):  # noqa: D401
                return None

        with open(blob, "rb") as f:
            got = decrypt_stream(f, _Null(), self._key, blob.stat().st_size, self._chunk)
        if got != expected_sha:
            raise VaultError("Kasadaki kopya doğrulanamadı (özet uyuşmuyor); dosya silinmedi.")

    def add_many(self, targets: list[str | Path], reason: str = "Elle eklendi") -> tuple[list[VaultItem], list[str]]:
        """Her dosya bagimsiz eklenir; biri basarisiz olunca digerleri etkilenmez. (eklenenler, hata mesajlari)"""
        added, errors = [], []
        for t in targets:
            try:
                added.append(self.add(t, reason))
            except VaultError as exc:
                errors.append(f"{Path(t).name}: {exc}")
        return added, errors

    def list(self) -> list[VaultItem]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM items ORDER BY quarantined_at DESC, rowid DESC").fetchall()
        return [VaultItem(*r) for r in rows]

    def get(self, item_id: str) -> VaultItem:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise VaultError(f"Kasada böyle bir kayıt yok: {item_id}")
        return VaultItem(*row)

    def _exists(self, item_id: str) -> bool:
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is not None

    def restore(self, item_id: str, dest: str | Path | None = None, overwrite: bool = False) -> Path:
        item = self.get(item_id)
        target = Path(dest) if dest else Path(item.original_path)
        if target.exists() and not overwrite:
            raise VaultError(f"Hedef zaten var: {target}. Başka bir yol seç ya da üzerine yazmayı onayla.")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".auxy-restore")
        blob = self._blob(item_id)
        try:
            with open(blob, "rb") as src, open(tmp, "wb") as dst:
                got = decrypt_stream(src, dst, self._key, blob.stat().st_size, self._chunk)
            if got != item.sha256:
                raise VaultError("Geri yüklenen dosyanın özeti kayıtla uyuşmuyor; işlem iptal edildi.")
            os.replace(tmp, target)
            os.utime(target, (item.mtime, item.mtime))
        except FileNotFoundError as exc:
            raise VaultError("Kasa dosyası diskte bulunamadı (silinmiş olabilir).") from exc
        finally:
            tmp.unlink(missing_ok=True)
        self._drop(item_id)
        self._log.info("KASA geri yukle: %s -> %s", item.name, target)
        return target

    def delete(self, item_id: str) -> None:
        item = self.get(item_id)
        self._drop(item_id)
        self._log.info("KASA kalici sil: %s (%s)", item.name, item.sha256[:12])

    def _drop(self, item_id: str) -> None:
        self._blob(item_id).unlink(missing_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM items WHERE id = ?", (item_id,))


def import_key_file(src: str | Path, password: str, root: Path | None = None) -> str:
    """Yedekten anahtari geri yukler (DPAPI ile yeniden korur). Kasada kayit varsa, anahtarin onlari
    gercekten acabildigi DOGRULANIR; acmiyorsa mevcut anahtar KORUNUR. Sonuc mesaji doner."""
    root = Path(root) if root else paths.home() / "vault"
    root.mkdir(parents=True, exist_ok=True)
    try:
        blob = Path(src).read_bytes()
    except OSError as exc:
        raise VaultError(f"Yedek dosyası okunamadı: {exc}") from exc
    key = decrypt_key_backup(blob, password)
    key_file = root / "vault.key"
    vault = Vault(root, key)
    verdict = vault.verify_key(key)
    if verdict is False:
        raise VaultError("Bu anahtar yedeği, kasadaki dosyaları açmıyor (başka bir kasaya ait olabilir). "
                         "Mevcut anahtara dokunulmadı.")
    save_key(key_file, key)
    get_logger().info("KASA anahtari yedekten geri yuklendi")
    return ("Anahtar geri yüklendi ve kasadaki dosyalarla doğrulandı." if verdict
            else "Anahtar geri yüklendi (kasa boş olduğu için dosyalarla doğrulanamadı).")
