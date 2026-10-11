# Sürüm notları

## 1.4.0 — 2026-10-11

### Yeni: Ön ayarlar
- **Tek tıkla çoklu ayar:** *En iyi hız*, *En güvenilir bağlantı*, *En gizli bağlantı*, *Maksimum gizlilik (Tor)*, *Yurt / kısıtlı ağ*. Her biri DNS, şifreli DNS, WARP, Tor, gizlilik anahtarları, rastgele MAC ve güvenlik duvarı profillerini birlikte ayarlar.
- **Önce plan, sonra onay:** ne değişeceği (önce → sonra), uyarılar (WARP/GoodbyeDPI DNS'i geçersiz kılıyorsa) ve atlananlar gösterilir; zaten istenen değerdekiler değiştirilmez.
- **Tek UAC:** yönetici gerektiren tüm adımlar (DNS, rastgele MAC, güvenlik duvarı) tek yükseltilmiş süreçte çalışır.
- **'En iyi hız' ve 'Yurt' ölçüm kullanır:** bu ağdaki en hızlı, kirletmeyen DNS seçilir.
- **Geri alma:** uygulamadan önce önceki durum kaydedilir; *Önceki ayarlara dön* DNS'i (eski elle ayar ya da otomatik), WARP, Tor, vekil, gizlilik anahtarları ve MAC'i geri yükler. Ön ayarlar art arda uygulansa da ilk (asıl) durum korunur.
- CLI: `auxy preset list | plan <ad> | apply <ad> --yes | revert`.
## 1.3.0 — 2026-10-11

### Yeni: DNS ve gizlilik sayfası
- **DNS seçimi:** Cloudflare, Google, Quad9, AdGuard, OpenDNS ya da özel IP; seçili ağlara atama (UAC), ilk değişiklikte eski ayar yedeklenir, 'Eski haline döndür'.
- **Hız ve güvenlik testi:** her DNS'e gerçek sorgu; hız, HTTPS/443 erişilebilirliği ve NXDOMAIN kirletme (ağın DNS'i yönlendiriyor mu) tespiti. 'En iyisini seç'.
- **Şifreli DNS (DoH)** + 'Sıkı mod' (şifresize düşme). GoodbyeDPI '--dns-addr' DNS'i yönlendiriyorsa uyarır.
- **Gizlilik:** reklam kimliği, kişiselleştirilmiş deneyimler, rastgele Wi-Fi MAC adresi, isteğe bağlı 'Ağ bilgimi göster'.
- **Tor (SOCKS5 vekili, VPN değil):** resmi paket dist.torproject.org'dan indirilir ve SHA-256 doğrulanır; başlat/durdur, bağlanma yüzdesi, köprüler (obfs4/snowflake/meek), yeni kimlik, Windows vekili anahtarı, Tor üzerinden doğrulama.
- CLI: `auxy dns|privacy|tor`.

### Not
- ODTÜ DNS'i yalnızca ODTÜ ağından (144.122.0.0/16) kullanılabilir; yurttan çalışmaz, bu yüzden hazır ayar yok: yerine ölçüm var.

## 1.1.2 — 2026-10-05

### Düzeltilen (aydınlık mod)
- Kenar çubuğu artık mod'u izler (aydınlıkta açık, koyuda koyu); simgeler iki modda da okunur.
- Tüm sayfalardaki renkler tek bir palete bağlandı: durum/hata/uyarı metinleri iki modda da okunur, kırmızı düğmeler ve çerçeveli düğmeler tutarlı.
- Metin kutuları (tarama geçmişi vb.) kartlarla aynı yüzey rengini kullanır.

## 1.1.1 — 2026-10-05

### Düzeltilen
- **WARP 'Bağlanıyor' takılması:** bağlan/kes sonrası durum artık oturana kadar (en çok ~30 sn) izlenir; sayfa bağlanma sırasında açılsa da izler.
- **WARP işlem mesajları:** `warp-cli`'nin uzun, İngilizce çıktısı yerine kısa Türkçe mesaj ("WARP bağlantısı kesildi."); hata mesajı tek satıra kısaltılır.

### Yeni görünüm
- Modern tema: Segoe UI, yuvarlak kartlar, mavi vurgu, açık/koyu mod uyumlu; koyu kenar çubuğu (logo, simgeler, yönetici durumu, sürüm); pano bandında durum kalkanı.

## 1.1.0 — 2026-10-05

### Yeni
- **Ağ güvenliği sayfası**: güvenlik duvarı (profiller, gelen bağlantı, kurallar, program engelleme) **Güvenlik sayfasından buraya taşındı**.
- **GoodbyeDPI** kartı: durum (çalışıyor / durduruldu / kurulu değil), Başlat / Kapat, Windows ile otomatik başlatma anahtarı.
- **Cloudflare WARP** kartı: durum, Bağlan / Bağlantıyı kes, bağlantı protokolü (**MASQUE** / **WireGuard**), çalışma kipi (WARP, WARP+DoH/DoT, yalnızca DoH/DoT, proxy, yalnızca tünel).
- **Kurulumda otomatik kurulum**: GoodbyeDPI uygulamayla gelir ve hizmet olarak kaydedilir (mevcut hizmetin argümanları, başlangıç türü ve çalışma durumu korunur); WARP yoksa `winget` ile arka planda kurulur. `/NOGDPI` `/NOWARP` ile kapatılır.
- **Yeni logo ve tray rozeti**: mavi kalkan + A (exe/pencere/görev çubuğu); tray'de kalkan üzerinde sorun sayısı (kritik: kırmızı, kritik olmayan: turuncu).
- `auxy netsvc` komutu; `doctor` GoodbyeDPI denetimi.

### Güvenlik
- GoodbyeDPI hizmeti SİSTEM olarak çalışır: exe'si kullanıcının yazabildiği klasördeyse (ör. Masaüstü) yetki yükseltme riski vardır. Hizmet yalnızca yönetici-yazılabilir konumdaki exe'ye kaydedilir; mevcut riskli hizmet için `doctor` uyarır ve kurulum/sayfa onu `Program Files`'a taşır.

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
