# Sürüm notları

## 1.0.0 — 2026-10-05

İlk kararlı sürüm: paketlenmiş, kurulabilir uygulama.

### Yeni
- **Kurulum programı** `AuxySecurity-Setup.exe`: `Program Files`'a kurar, Başlat menüsü/masaüstü kısayolu, isteğe bağlı
  oturum açılışında başlatma ve sağ tık menüsü; sessiz mod `/S`. Kaldırma: Ayarlar → Uygulamalar ya da `auxy.exe uninstall`
  (ayarların ve karantina kasan **korunur**).
- **Paketlenmiş uygulama** (PyInstaller): `AuxySecurity.exe` (pencereli) ve `auxy.exe` (komut satırı), Python kurulumu gerekmez.
  Tray ajanı ~25 MB özel bellek, boşta %0 CPU.
- **Eski veri taşıma**: Store Python'un sanallaştırılmış veri dizini gerçek `%LOCALAPPDATA%\AuxySecurity` dizinine
  kopyalanır (`auxy migrate-data --yes` ya da ilk açılışta GUI önerisi). Eski veri silinmez.
- **Ajan içi yeniden başlatma denetçisi** (çökme olursa 5 kez / 10 dk'ya kadar, artan beklemeyle).
- `doctor`: sürüm, eski veri ve görev tekrarlama denetimleri.
- İmzalama betiği `scripts/sign.ps1` (kendi sertifikanla; depoda sertifika yok).

### Değişti
- Başlangıç görevi artık **10 dakikada bir tekrarlayan tetikleyici** + `IgnoreNew` kullanır. M8'deki `RestartOnFailure`
  yöntemi gerçek testte **çalışmadığı** için bırakıldı (Görev Zamanlayıcı sıfırdan farklı çıkış koduyla yeniden başlatmıyor).
- Yükseltilmiş yardımcı süreç yalnızca izinli alt komutları çalıştırır (`ELEVATED_ALLOWED`).
- `uninstall`, yalnızca **bu kurulumu** gösteren görev/sağ tık girdilerini kaldırır.

### Düzeltilen
- Paketlenmiş `doctor` bağımlılık denetimi paket meta verisi olmadığında yanlışlıkla hata veriyordu.
- Paketlenmiş exe'nin çıkışında "Win32 exception occurred releasing IUnknown" iletisi (COM nesnesi `CoUninitialize`
  sonrası serbest kalıyordu).
- Kaldırıcı kendi sürecini `taskkill` ile öldürüyordu; dosya silme komutu hiç çalışmıyordu (liste yerine tek dizge gerekiyordu).

## 0.8 ve öncesi
Milestone dokümanlarına bakın: [docs/milestones](docs/milestones/).
