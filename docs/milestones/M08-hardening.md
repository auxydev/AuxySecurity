# M8 – Sağlamlaştırma

**Durum:** İncelemede  **Tarih:** 2026-10-05

## 1. Hedef
Prototipi güvenilir hale getirmek: kaynak kullanımı, çökme/sessiz hata dayanıklılığı, güvenlik gözden geçirmesi, bozuk veriye dayanıklılık, test kapsamı, temiz kurulum ve kaldırma. Plan bölüm 5'teki M8 maddeleri.

## 2. Kapsam / Kapsam dışı
- Kapsam: bölüm 4'teki 10 madde.
- Kapsam dışı: sanal makinede kurulum/kaldırma testi (VM yok; yerine temiz-venv tekerlek kurulumu yapıldı), kurulum dosyası ve imzalama (**M9**).

## 3. Nasıl çalıştırılır
```powershell
python -m auxy doctor            # ortam ve kurulum tanısı (hiçbir şeyi değiştirmez); --json
python -m auxy cleanup           # kaldırma temizliği: sağ tık menüsü + başlangıç görevi (veriye dokunmaz)
python -m auxy cleanup --revert-settings   # değiştirdiğin ayarları orijinaline döndür (UAC)
python -m auxy revert-all        # Defender + Windows güvenlik ayarlarının hepsini geri al (UAC)
pytest -q                        # 366 test
python scripts\leak_check.py 300 # kaynak sızıntısı taraması
python scripts\measure_agent.py 30   # yalıtılmış ajan bellek/CPU ölçümü
```
`doctor` örnek çıktı (gerçek makine, kısaltılmış):
```
 ✔ Python                     3.12.10 (...\.venv\Scripts\python.exe)
 ✔ Defender WMI erişimi       156 ms
 ✔ Gerçek zamanlı koruma      açık
 ✔ Karantina kasası           0 kayıt; anahtar kayıt yok, doğrulanamadı
 ⚠ Kurulum konumu             Uygulama kodu / Python kullanıcının yazabildiği bir dizinde: …
 ⚠ Günlük                     son 24 saatte 6 hata; sonuncusu: …
Özet: 16 tamam, 2 uyarı, 0 hata
```

## 4. Yapılanlar
1. **Yakalanmamış istisna kancaları** (`core/crashlog.py`): ana iş parçacığı, diğer iş parçacıkları, `unraisable` ve Tk geri çağırmaları günlüğe yazılır. (M7'de izleme iş parçacığı sessizce ölmüştü; konsolsuz `pythonw`'da hata hiçbir yerde görünmüyordu.)
2. **Çökme kurtarma:** Ajan çökerse nedeni günlüğe yazılır ve çıkış kodu ≠ 0 olur; başlangıç görevi XML'ine **"hata durumunda 1 dk sonra, 3 kez yeniden başlat"** eklendi.
3. **Bellek:** Bekleyen ajan çalışma kümesini küçültür (`EmptyWorkingSet`) ve simgeleri bir kez çizip önbelleğe alır.
4. **`auxy doctor`:** 15+ bağımsız kontrol (Python, bağımlılıklar, Defender, WMI, veri dizini, yapılandırma, yedek, **kasa anahtarı doğrulaması**, ajan, görev, sağ tık, **kurulum konumu riski**, günlükteki son hatalar, tarama kilidi). Hiçbir şeyi değiştirmez (kasa anahtarı bile üretmez); bir kontrol hata verirse doctor çökmez.
5. **Güvenlik gözden geçirmesi** ([security-review.md](../security-review.md)): 17 tehdit maddesi; sonuç dosyası sertleştirme (sembolik bağlantı/hardlink/TOCTOU), kurulum konumu uyarıları, yüksek yetkili görev için onay, bağımlılık taraması.
6. **Bozuk veriye dayanıklılık:** bozuk `vault.db` → net hata, şifreli dosyalar korunur; bozuk `backup.json` → **silinmeden** kenara alınır (yeni kayıtlar eskileri ezmez); bozuk config/geçmiş → varsayılana düşer.
7. **Kaldırma:** `auxy cleanup` (sağ tık + görev; veri silme yalnızca `--remove-data`, **kasada dosya varsa reddeder**), `revert-all`.
8. **Test kapsamı ölçümü** (`coverage`, dal kapsamı dahil): **%86**; 366 test.
9. **Temiz kurulum testi:** tekerlek (wheel) oluşturuldu, boş sanal ortamda kuruldu, repo dışından çalıştırıldı.
10. **Sızıntı taraması** (`scripts/leak_check.py`).

## 5. Teknik kararlar
- **Çalışma kümesi küçültme:** Windows'un "Bellek" metriğini düşürür; **özel (gerçek) belleği azaltmaz** (24 MB sabit). Bekleyen bir tray ajanı için meşru ve yaygın bir yöntemdir (sayfalar gerektikçe geri yüklenir; CPU etkisi ölçülemeyecek kadar küçük). Sonucu bu ayrımla raporluyorum.
- **Doctor salt-okunur:** Tanı aracı sorunu **kendisi yaratmamalı**: kasa yoksa oluşturmaz, anahtar yoksa üretmez (testle doğrulanır).
- **Bozuk dosyayı silme, kenara al:** Yedek dosyası kullanıcının tek geri dönüş yoludur; bozuksa kanıt olarak saklanır.
- **Kaldırmada veri koruması:** Kasa şifreli olduğundan, silinen veri/anahtar geri getirilemez; bu yüzden varsayılan davranış veriyi korumaktır.

## 6. Kabul kriterleri ve sonuçlar
| Kriter | Sonuç |
|---|---|
| Boşta CPU < %0.5, RAM < 40 MB | ✔ **CPU %0.000**; **çalışma kümesi 2.8 MB** (önce 40.0), **özel bellek 24.0 MB**; her iki ölçüt de < 40 MB. Launcher (venv kalıntısı, kurulu sürümde yok) +11.9 MB ayrı |
| Sızıntı yok | ✔ 300 tur (35 sn): iş parçacığı sabit, RSS −0.3/+0.1 MB, handle +11 / +3. Tur başına ~117 ms |
| Ajan, değişikliklerden sonra uçtan uca çalışıyor | ✔ gerçek ajan: izleme, olay aboneliği, ayar sinyali (0.11 sn), kapalıyken tarama yok, açınca var; boşta CPU %0.000 |
| Yakalanmamış hata günlüğe düşer | ✔ iş parçacığı, ana iş parçacığı, finalizer, Tk; **gerçek alt süreçte** ajan çökmesi: çıkış kodu 1 + günlükte iz |
| Görev XML'inde yeniden başlatma | ✔ XML doğrulandı; ⏳ **gerçek tetiklenme denenmedi** |
| Sonuç dosyası saldırıları | ✔ **gerçek** sembolik bağlantı ve hardlink: reddedildi, hedef dosya değişmedi |
| Bozuk dosyalar | ✔ vault.db, backup.json (2 biçim), config, geçmiş |
| `doctor` | ✔ gerçek makinede 16 tamam / 2 uyarı / 0 hata; hiçbir şeyi değiştirmediği testle kanıtlı |
| Kapsam ≥ %70 (core) | ✔ **core %89**, agent %83, gui %82, **toplam %86** |
| Temiz kurulum | ✔ tekerlek 100 KB / 44 dosya; boş venv'e kuruldu; `auxy` komutu, 100% modül içe aktarma, `doctor`, `status` repo dışından çalıştı |
| Bağımlılık taraması | ✔ uygulamanın 7 bağımlılığında bilinen açık yok (yalnızca `pip` aracında) |
| Testler kararlı | ✔ tam paket **10/10** art arda koşuda geçti |

## 7. Performans ölçümü
| Ölçüm | M7 | M8 |
|---|---|---|
| Ajan çalışma kümesi (asıl süreç) | 40.0–42.7 MB | **2.8 MB** |
| Ajan özel bellek | 24.4 MB | 24.0 MB |
| Ajan CPU (30 sn) | 0.000% | 0.000% |
| Pencere açılışı | ~0.35–0.9 sn | ~0.8 sn (güvenlik sayfası daha çok kart) |
| Test paketi | 185 test, ~5 sn | 366 test, ~19 sn |

## 8. Bu milestone'da bulunan gerçek hatalar
1. **Dışlama listesi ikinci "Listele"de çöküyordu** (`TclError`): yenilerken not etiketi yok ediliyordu. Etiket her seferinde yeniden oluşturuluyor.
2. **Tray bildirimleri güvenli sarmalayıcıyı atlıyordu:** `_apply` ve `_quick_scan` doğrudan `icon.notify` çağırıyordu; simge hazır değilken istisna fırlatırdı.
3. **Testler gerçek diyalog açıyordu:** yeni risk uyarısını tetikleyen iki test ekranında gerçek bir "Güvenlik uyarısı" penceresi açmış olabilirdi. Artık testte gerçek diyalog çağrısı **hata verir** (`conftest.py`).
4. **Testlerde kırılganlık, 3 ayrı kök neden:** (a) art arda `Tk()` açma (Tcl hatası) → tek ortak pencere; (b) `pystray` pencere sınıf adını `id()`'den türetiyor, çöp toplanan `Icon`'un id'si yeniden kullanılınca `WinError 1410` → testlerde `Icon`'lar canlı tutuluyor; (c) adlı olay/mutex gerçek çalışan ajanla paylaşılıyordu → testlerde ayrı örnek adı.
5. **Benim hatam:** `auxy cleanup`'ı gerçek makinede varsayılan haliyle denedim ve daha önce kurulu olan **sağ tık menüsünü kaldırdım** (onay almadan). Hemen yeniden kurdum; `cleanup` testleri artık yalnızca sahtelerle çalışır (kayıt defterine/göreve dokunmaz).
6. **Benim hatam:** ekran görüntüsü betiği (README çalışması) `ImageGrab` ile ekranı kopyalıyordu; uygulama penceresi tarayıcının arkasında kalınca **başka bir pencere (kişisel içerik)** yakalandı. Dosyalar anında silindi, hiçbir zaman commit edilmedi; tüm betikler `PrintWindow` ile yalnızca uygulama penceresini alan ve doğrulayan `scripts/_capture.py`'ye geçirildi. Daha önce commit'lenen tüm görüntüler piksel analiziyle kontrol edildi: yalnızca uygulama penceresi.

## 9. Bilinen sorunlar / Doğrulanmayanlar
- **Görev Zamanlayıcı'nın yeniden başlatması gerçek ortamda denenmedi** (ajanı öldürüp 1 dk beklemek; yükseltilmiş ajan için ek UAC gerekir).
- **VM'de kurulum/kaldırma yapılamadı;** yerine temiz sanal ortamda tekerlek kurulumu yapıldı. `cleanup`'ın başlangıç görevini kaldırma adımı sahtelerle (ve B01'de gerçek UAC ile) doğrulandı, uçtan uca gerçek `cleanup --remove-data` çalıştırılmadı (kullanıcı verisini silerdi).
- **T1 (UAC kodu yazılabilir dizinden gelir) açık risk;** v1.0 paketiyle kapanacak. Bkz. [security-review.md](../security-review.md).
- Çalışma kümesi küçültmesi yalnızca bellek *metriğini* düşürür (bölüm 5).
- Kapsam: `gui/` sayfaları ve `tray` hâlâ en düşük (%74–83); UAC'li gerçek akışlar birim testle tam kapsanamaz.
- Windows 10, domain/çok kullanıcılı ortamlar denenmedi.

## 10. İnceleme notları
_(Senin geri bildirimin buraya eklenecek.)_

## 11. Sonraki milestone'a etkisi
**M9 (Paketleme, v1.0):** `Program Files` altına kurulum (T1'i kapatır), imzalı yürütülebilir (PyInstaller/Nuitka), kurulum/kaldırıcı (`cleanup` mantığı hazır), veri yolunun Store sanallaştırmasından çıkarılması + taşıma, otomatik güncelleme yok (ağ yok ilkesi), sürüm notları. Güvenlik gözden geçirmesindeki "yardımcı alt komut listesini daraltma" maddesi de M9'a girer.
