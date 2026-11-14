# M13 – Hızlı kurulum paketi (`başlat.bat`)

**Durum:** İncelemede  **Tarih:** 2026-11-15  **Sürüm:** 1.5.0

## 1. Hedef
Kullanıcı isteği: "hızlı bir indirici; dosyaların içinde `başlat.bat` olsun, onu çalıştırınca adım adım kendisi kursun."

## 2. Kapsam / Kapsam dışı
- Kapsam: dağıtılabilir zip (`başlat.bat` + kurucu + SHA256SUMS + açıklama), adım adım sihirbaz, sorusuz kip, paket üretici.
- Kapsam dışı: paketi internette yayımlama (GitHub Release vb.) — kullanıcı onayı gerektirir; depo özel.

## 3. Nasıl çalıştırılır
```powershell
.\scripts\build.ps1                 # uygulama
.\scripts\build_installer.ps1       # AuxySecurity-Setup.exe
python scripts\make_package.py      # %TEMP%\auxy-build\AuxySecurity-Kurulum-<sürüm>.zip
```
Kullanıcı: zip'i çıkar → `başlat.bat`'a çift tıkla. Sorusuz: `başlat.bat /auto` (`/nogdpi`, `/nowarp`, `/nostart`).

## 4. Adımlar
1. **Sistem:** 64 bit + Windows 10/11.
2. **Yönetici izni:** değilse kendini UAC ile yeniden başlatır; reddedilirse durur.
3. **Doğrulama:** `AuxySecurity-Setup.exe`'nin SHA-256'sı `SHA256SUMS.txt` ile karşılaştırılır (`certutil`); uyuşmazsa
   kurucu **hiç çalıştırılmaz**.
4. **Seçenekler (E/H, 60 sn sonra varsayılan):** otomatik başlatma (E), sağ tık (E), masaüstü kısayolu (H), GoodbyeDPI (E),
   WARP indirme (E).
5. **Kurulum:** kurucu sessiz kipte, seçilen bayraklarla.
6. **Denetim:** `AuxySecurity.exe` var mı, `auxy --version`, `auxy doctor` özeti.
7. **Açma:** uygulama `explorer.exe` üzerinden **yükseltilmemiş** kullanıcı olarak açılır (Tor vb. yönetici olarak çalışmamalı).

## 5. Teknik kararlar
- `.bat` UTF-8 (BOM'suz) + CRLF, `chcp 65001`; zip içindeki Türkçe dosya adı UTF-8 bayrağıyla yazılır (Python `zipfile`).
- Kurucu `call` ile çalıştırılır (toplu iş dosyası GUI programını bekler, çıkış kodu doğru alınır).
- Test kipi (`AUXY_BAT_TEST=1` + `AUXY_SETUP` + `AUXY_INSTALLDIR`): yükseltme/soru/açma atlanır, sisteme dokunulmaz.

## 6. Kabul kriterleri ve sonuçlar
| Kriter | Sonuç |
|---|---|
| Gerçek `cmd.exe` ile tam akış (sahte kurucu) | ✔ 7 adım, doğru bayraklar, çıkış 0 |
| Değiştirilmiş kurucu reddi (SHA uyuşmazlığı) | ✔ kurucu hiç çalışmadı, çıkış 1 |
| Kurucu yok / hata kodu / uygulama dosyası yok | ✔ anlaşılır hata, çıkış 1 |
| Kaçış karakteri (`^`) ekrana sızmıyor | ✔ (ilk denemede sızıyordu: tırnak içindeki `^(` düzeltildi) |
| Paket: Türkçe adlı `başlat.bat`, eşleşen SHA-256, CRLF | ✔ ve `Expand-Archive` ile çıkarınca ad korunuyor |
| Testler | ✔ 525 test (9 yeni) |

## 7. Bilinen sorunlar / Riskler
- **Yükseltilmiş gerçek uçtan uca çalıştırma bu oturumda yapılamadı** (UAC istemi iptal edildi). Test kipinde ve sahte
  kurucuyla doğrulandı; ilk gerçek çalıştırmayı kullanıcı yapacak.
- SHA-256 aynı zip'ten gelir: **bütünlük** (bozulma) denetimidir; zip'i kim değiştirirse SHA dosyasını da değiştirebilir.
  Gerçek güven için kurucunun kod imzası (`scripts/sign.ps1`) gerekir.
- İmzasız `.bat` / `.exe`: SmartScreen "bilinmeyen yayıncı" uyarısı verebilir ("Ek bilgi → Yine de çalıştır").

## 8. İnceleme notları (kullanıcı geri bildirimi)
(Bekleniyor.)
