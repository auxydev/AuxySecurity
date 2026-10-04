# AuxySecurity – Kapsamlı Proje Planı

> Kişisel Windows Security (Defender) kontrol paneli + hafif tarayıcı + karantina aracı.
> Dil: Python 3.12+ · Hedef: Windows 11 · Metodoloji: Sürekli Prototipleme + Milestone dokümantasyonu

---

## 1. Vizyon ve Dürüst Kapsam

**AuxySecurity**, kendi antivirüs motorunu yazmaz. Windows Defender motoru zaten çekirdek seviyesinde çalışır ve Python ile bundan daha iyisi yazılamaz. AuxySecurity şunları yapar:

1. **Tek pencereli kontrol paneli**: Windows Security'deki ayarların çoğunu tek ekrandan görme/değiştirme.
2. **Hızlı anahtarlar (tray)**: Gerçek zamanlı koruma, bulut koruması vb. tek tıkla aç/kapat.
3. **Tarama yöneticisi**: Hızlı / Tam / Özel tarama başlat, ilerleme ve sonuç göster.
4. **Kendi karantina kasası (Vault)**: Şüpheli dosyayı şifreleyip izole eder, geri yüklenebilir.
5. **Hafif izleme**: İndirilenler gibi klasörlere düşen yeni dosyaları otomatik taratır.

### Bilinen kısıtlar (baştan kabul edilmeli)
| Kısıt | Etki | Çözüm |
|---|---|---|
| **Tamper Protection** açıkken `Set-MpPreference` ile koruma kapatılamaz | Bazı anahtarlar çalışmaz | Durumu oku, kapalıysa değiştir; açıksa "Windows Security'de elle kapat" yönlendirmesi göster. Programatik olarak kapatmaya **çalışmayacağız**. |
| Ayarların çoğu **yönetici yetkisi** ister | UAC sorunu | Görev Zamanlayıcı ile "en yüksek yetkiyle, oturum açılışında" başlatma (UAC istemsiz). |
| Bazı ayarlar **yeniden başlatma** ister (Memory Integrity) | UX | Arayüzde "yeniden başlat" rozeti göster. |
| Hesap koruması, Aile seçenekleri, Windows Hello vb. API'ye açık değil | Tam kapsam imkânsız | Salt-okunur durum + "Windows Security'yi aç" kısayolu (`windowsdefender://`). |
| Defender'ı sürekli kapalı tutmak güvenlik riski | Kendi kendine zarar | **Geçici devre dışı** modeli: süre dolunca otomatik geri açılır. |

---

## 2. Teknik Mimari

```
┌──────────────────────────────────────────────┐
│ auxy-agent  (tray, ~10-20 MB, event-driven)  │  <- başlangıçta çalışan TEK süreç
│  ├─ Tray menü + hızlı anahtarlar             │
│  ├─ Watcher (yeni dosya) / Event Log abone   │
│  └─ Zamanlayıcı (geçici devre dışı geri aç.) │
└───────────────┬──────────────────────────────┘
                │ gerektiğinde subprocess ile açar
┌───────────────▼──────────────┐
│ auxy-gui  (tam pencere)      │  <- kapatılınca bellekten düşer
└───────────────┬──────────────┘
                │ ikisi de import eder
┌───────────────▼──────────────────────────────┐
│ auxy_core  (UI'dan bağımsız kütüphane)       │
│  defender/  firewall/  system/  scan/        │
│  quarantine/  storage/  logging/             │
└──────────────────────────────────────────────┘
```

**Neden iki süreç?** Boşta duran uygulama sadece küçük bir tray ajanıdır. GUI ağır bileşenlerini ancak pencere açılınca yükler → "bilgisayara yük bindirmemeli" şartı.

### Teknoloji seçimleri
| Alan | Seçim | Gerekçe |
|---|---|---|
| GUI | **customtkinter** (tkinter tabanlı) | Hafif, kurulumu kolay, modern görünüm. PySide6 ~3x RAM tüketir. |
| Tray | **pystray** + Pillow | Hafif, tek bağımlılık zinciri. |
| Defender erişimi | **WMI (`root/Microsoft/Windows/Defender`)** birincil, **PowerShell** yedek | WMI, PowerShell başlatma maliyetinden (~300 ms, ~40 MB) kaçınır. |
| Registry | `winreg` (stdlib) | SmartScreen, Memory Integrity vb. |
| Olay dinleme | `pywin32` `win32evtlog.EvtSubscribe` | Polling yok, olay gelince uyanır. |
| Dosya izleme | `watchdog` (ReadDirectoryChangesW) | Çekirdek bildirimli, CPU ≈ 0. |
| Kasa şifreleme | `cryptography` (AES-GCM) | Karantinadaki zararlı dosya yanlışlıkla çalışamaz. |
| Veritabanı | `sqlite3` (stdlib) | Karantina kaydı, ayarlar, günlük. |
| Ayarlar | `tomllib` + `tomli_w` | Okunabilir config. |
| Paketleme | **PyInstaller** (ilk), ileride **Nuitka** | Hızlı prototip → sonra optimizasyon. |
| Test | `pytest`, `pytest-mock` | Windows API'leri soyutlanıp mock'lanır. |
| Kalite | `ruff`, `mypy` | |

### Başlangıçta çalıştırma
Registry `Run` anahtarı yönetici yetkisiyle başlatamaz. Bu yüzden:
`schtasks /Create /SC ONLOGON /RL HIGHEST /TN "AuxySecurity"` → UAC istemsiz, yüksek yetkili tray ajanı. Gecikme: 30 sn (açılışı yavaşlatmaz).

### Performans bütçesi (ölçülebilir hedef)
- Boşta CPU: **< %0.5** ortalama
- Boşta RAM (yalnızca ajan): **< 40 MB**
- Açılış etkisi (Task Manager "Başlangıç etkisi"): **Düşük**
- GUI açılış süresi: **< 1.5 sn**
- Kural: Sonsuz `while True: sleep` döngüsü yok. Her şey olay veya GUI görünürken 30 sn'lik yenileme.

---

## 3. Windows Security Kapsam Haritası

| Windows Security bölümü | Ayar | Yöntem | Kontrol |
|---|---|---|---|
| **Virüs ve tehdit koruması** | Gerçek zamanlı koruma | `Set-MpPreference -DisableRealtimeMonitoring` / WMI | Aç/Kapat* |
| | Bulut korumalı koruma (MAPS) | `-MAPSReporting` | Aç/Kapat |
| | Otomatik örnek gönderimi | `-SubmitSamplesConsent` | Seçim |
| | Tamper Protection | `Get-MpComputerStatus.IsTamperProtected` | **Salt-okunur** |
| | Hızlı/Tam/Özel tarama | `Start-MpScan` / `MpCmdRun.exe` | Başlat/İptal |
| | İmza güncelleme | `Update-MpSignature` | Başlat |
| | Tehdit geçmişi | `Get-MpThreat`, `Get-MpThreatDetection` | Listele/Temizle |
| | Dışlamalar | `Add/Remove-MpPreference -ExclusionPath/Extension/Process` | Yönet |
| | Denetimli klasör erişimi (fidye yazılımı) | `-EnableControlledFolderAccess`, korunan klasörler, izinli uygulamalar | Aç/Kapat + liste |
| | PUA / istenmeyen uygulama | `-PUAProtection` | Aç/Kapat |
| | Ağ koruması | `-EnableNetworkProtection` | Aç/Kapat |
| | Çevrimdışı tarama | `Start-MpWDOScan` | Başlat (yeniden başlatır) |
| **Güvenlik duvarı** | Etki alanı/Özel/Genel profil | `Set-NetFirewallProfile -Enabled` | Aç/Kapat |
| | Gelen bağlantıları engelle | `-DefaultInboundAction` | Seçim |
| | Kural listesi | `Get-NetFirewallRule` | Salt-okunur → sonra ekle/sil |
| **Uygulama ve tarayıcı denetimi** | SmartScreen (uygulama/Edge/Store) | Registry (`HKLM\...\Explorer\SmartScreenEnabled`, vb.) | Seçim |
| | Exploit protection | `Get-/Set-ProcessMitigation` | Sistem ayarları |
| **Cihaz güvenliği** | Memory Integrity (HVCI) | Registry `DeviceGuard\...\HypervisorEnforcedCodeIntegrity` | Aç/Kapat (reboot) |
| | TPM, Secure Boot | `Get-Tpm`, `Confirm-SecureBootUEFI` | Salt-okunur |
| **Genel durum** | AV/FW/Anti-spyware durumu | WMI `root\SecurityCenter2` | Salt-okunur |
| **Hesap koruması, Aile, Cihaz performansı** | – | API yok | Kısayol: `windowsdefender://` |

\* Tamper Protection açıksa çalışmaz; arayüz bunu açıkça belirtir.

---

## 4. Çalışma Metodolojisi: Sürekli Prototipleme

Her milestone aynı döngüyü izler. **Her milestone sonunda çalıştırabileceğin bir prototip vardır.**

```
 Planla (1 gün) → Prototip kur → Demo/İncele (sen) → Geri bildirim → Dokümanla → Sonraki
        ↑                                                                    │
        └──────────────── Geri bildirim bir sonraki kapsamı şekillendirir ───┘
```

**Kurallar**
1. Önce **en riskli/belirsiz** parça (spike), sonra güzelleştirme.
2. Her prototip `python -m auxy` veya tek komutla **çalıştırılabilir** olmalı.
3. Prototip kod "atılabilir" olabilir; milestone sonunda **refactor** adımı vardır.
4. Her milestone: *Çalışan prototip + dokümantasyon + test kanıtı + bilinen sorunlar.*
5. Kapsam kayması olursa yeni işler `BACKLOG.md`'ye gider, mevcut milestone genişlemez.
6. **Geri alınabilirlik**: Sistem ayarını değiştiren her özellik önce değişiklik öncesi değeri kaydeder (`state_backup`) ve "Varsayılana dön" sunar.

### Proje dizin yapısı
```
AuxySecurity/
├─ PLAN.md
├─ BACKLOG.md
├─ docs/
│  ├─ README.md                 # Dokümantasyon dizini
│  ├─ architecture.md
│  ├─ decisions/ADR-0001-*.md   # Mimari karar kayıtları
│  ├─ milestones/
│  │   ├─ _TEMPLATE.md
│  │   ├─ M00-spike.md
│  │   └─ ...
│  └─ user-guide.md
├─ src/auxy/
│  ├─ core/        (defender, firewall, system, scan, quarantine, storage)
│  ├─ agent/       (tray, watcher, scheduler)
│  ├─ gui/         (pages, widgets)
│  └─ __main__.py
├─ tests/
├─ scripts/        (install_task.ps1, build.ps1)
└─ pyproject.toml
```

### Milestone doküman şablonu (`docs/milestones/_TEMPLATE.md`)
```
# Mxx – <Ad>
Durum: Planlandı | Devam | İncelemede | Tamamlandı     Tarih: ...
## 1. Hedef (1-2 cümle)
## 2. Kapsam / Kapsam dışı
## 3. Prototip: nasıl çalıştırılır (komutlar + ekran görüntüsü)
## 4. Yapılanlar (görev listesi)
## 5. Teknik kararlar (ADR bağlantıları)
## 6. Kabul kriterleri ve sonuçlar (✔/✘ + kanıt)
## 7. Performans ölçümü (CPU/RAM)
## 8. Bilinen sorunlar / Riskler
## 9. İnceleme notları (kullanıcı geri bildirimi)
## 10. Sonraki milestone'a etkisi
```

---

## 5. Milestone'lar

### M0 – Keşif ve Teknik Doğrulama (Spike)
**Amaç:** Varsayımları bu makinede kanıtlamak.
- Python ortamı, `pyproject.toml`, repo iskeleti, `git init`.
- Yönetici yetkisi, Tamper Protection durumu, WMI/PowerShell erişimini doğrula.
- `Get-MpComputerStatus`, `Get-MpPreference` çıktılarını WMI ile al.
- WMI vs PowerShell süre/bellek karşılaştırması.
- **Prototip:** `python -m auxy status` → Defender'ın ana durumunu terminalde yazdırır.
- **Kabul:** Gerçek zamanlı koruma, imza sürümü, Tamper durumu doğru okunuyor; ADR-0001 (WMI vs PS) yazıldı.
- **Doküman:** M00-spike.md, architecture.md ilk taslak.

### M1 – Çekirdek Kütüphane + CLI
**Amaç:** UI'dan bağımsız, test edilebilir `auxy_core`.
- `DefenderService`: oku/yaz (gerçek zamanlı, MAPS, PUA, CFA, Ağ koruması).
- Ayar yedekleme/geri alma mekanizması, Tamper Protection engeli algılama ve anlamlı hata.
- Yetki kontrolü + "yönetici olarak yeniden başlat".
- Yapılandırılmış günlük (`%ProgramData%\AuxySecurity\logs`, döner dosya).
- **Prototip:** `auxy get`, `auxy set realtime off`, `auxy revert`.
- **Kabul:** Birim testleri (mock); gerçek makinede aç/kapat doğrulandı; hata durumları temiz.

### M2 – GUI İskeleti: Pano
**Amaç:** İlk görülebilir arayüz.
- customtkinter ana pencere, sol menü: *Pano · Tarama · Karantina · Ayarlar · Günlük*.
- Pano: koruma durumu kartları (yeşil/sarı/kırmızı), tek bakışta "güvendesin / dikkat".
- Anahtarlar (toggle) gerçek ayarlara bağlı; Tamper kilidi görsel olarak belirtilir.
- **Prototip:** `python -m auxy gui`
- **Kabul:** Pencere < 1.5 sn'de açılır; toggle → gerçek durum değişir; arayüz donmaz (iş parçacığı + kuyruk).

### M3 – Tray Ajanı + Hızlı Anahtarlar + Başlangıçta Çalışma
**Amaç:** "Başlangıçta çalışsın ve yük oluşturmasın."
- pystray menüsü: durum rozeti, hızlı anahtarlar, "Hızlı tara", "Paneli aç".
- GUI ayrı süreç olarak, tray'den açılır.
- Görev Zamanlayıcı kurulum/kaldırma betiği, 30 sn gecikmeli başlangıç.
- "Koruma 10/30/60 dk duraklat" (otomatik geri açılır).
- **Prototip:** Oturum aç → tray simgesi → tek tıkla anahtar.
- **Kabul:** Boşta RAM < 40 MB, CPU < %0.5 (ölçüm tablosu docs'ta).

### M4 – Tarama Yöneticisi
- Hızlı / Tam / Özel (klasör/dosya seç) / Çevrimdışı tarama.
- İlerleme (`MpCmdRun`/olaylar), iptal, imza güncelleme, tarama geçmişi.
- Tehdit listesi: tehdit adı, şiddet, dosya yolu, durum; Defender aksiyonları (temizle/kaldır).
- Sağ tık / sürükle-bırak ile dosya tarama.
- **Prototip:** GUI'den tarama başlat → bulgu tablosu.
- **Kabul:** EICAR test dosyası algılanıp listelenir.

### M5 – Karantina Kasası (Vault)
- Dosyayı AES-GCM ile şifreleyip `%ProgramData%\AuxySecurity\vault\` altına taşı; ACL ile kullanıcıya çalıştırma kapat; uzantı `.auxq`.
- SQLite meta: orijinal yol, SHA-256, zaman, neden, boyut.
- **Geri yükle** (orijinal yola / farklı yola), **kalıcı sil**, **Defender karantinasıyla eşitle**.
- **Güvenlik rayları:** `C:\Windows`, `System32`, Auxy'nin kendi dosyaları ve kritik yollar koruma listesinde; kalıcı silmede onay.
- Tarama sonuçlarından "Kasaya al" butonu.
- **Prototip:** EICAR → kasaya al → geri yükle döngüsü.
- **Kabul:** Hash eşleşir, geri yüklenen dosya bire bir aynı, kasadaki dosya çalıştırılamaz.

### M6 – Tam Windows Security Kapsamı
- Güvenlik duvarı profilleri, SmartScreen, Memory Integrity (reboot rozeti), Exploit protection, dışlama yönetimi, CFA korunan klasörler / izinli uygulamalar, PUA, Ağ koruması.
- Cihaz güvenliği (TPM, Secure Boot) salt-okunur.
- API'si olmayanlar için `windowsdefender://` kısayolları.
- "Ayarlar" sayfası kategorilere ayrılmış, her ayarda kısa açıklama ve risk etiketi.
- **Prototip:** Windows Security'deki tüm başlıkların karşılığı.
- **Kabul:** Bölüm 3 tablosundaki her satır ✔ / salt-okunur / kısayol olarak işaretli ve test edilmiş.

### M7 – Gerçek Zamanlı Yardımcılar
- `watchdog` ile İndirilenler/Masaüstü izleme → yeni dosyayı otomatik `Custom Scan`.
- Defender olay günlüğüne abonelik (ID 1116/1117/5007) → Windows bildirimi ("Tehdit bulundu → Kasaya al?").
- Zamanlanmış tarama (haftalık, boştayken).
- USB takılınca tara (opsiyonel).
- **Kabul:** Dosya düşünce < 3 sn içinde tarama tetiklenir, CPU zirvesi sınırlı, boşta yük sıfıra döner.

### M8 – Sağlamlaştırma ve Performans
- Performans profili (`cProfile`, `psutil`) ve bütçe doğrulaması.
- Tek örnek kilidi, çökme kurtarma, bozuk ayar dosyası toleransı.
- Güvenlik gözden geçirme: komut enjeksiyonu (PowerShell parametreleri **asla** string birleştirilmez), yol doğrulama, kasa anahtar yönetimi (DPAPI ile korunan anahtar).
- Denetim günlüğü: kim, ne zaman, hangi ayarı değiştirdi.
- Test kapsamı hedefi ≥ %70 (core).
- Sanal makinede (Windows 11 VM) kurulum/kaldırma testi.

### M9 – Paketleme ve v1.0
- PyInstaller `--onedir` build, tek tıkla kurulum betiği/Inno Setup, kaldırıcı (görev ve ayar geri alma).
- Kullanıcı kılavuzu, SSS, sorun giderme.
- Sürüm notları, `v1.0.0` etiketi.
- Son izleme: 7 günlük gerçek kullanım, performans raporu.

### Backlog (v1.x)
YARA kural tarama · VirusTotal hash sorgusu (yalnızca hash, opt-in) · Dosya bütünlüğü izleme · Açık port/ağ bağlantısı görüntüleyici · Başlangıç öğeleri denetçisi · Karanlık/açık tema · Bildirim özelleştirme · Dışa aktar/içe aktar ayar profili.

---

## 6. Zaman Çizelgesi (tahmini, haftalık 8–10 saat varsayımıyla)
| Milestone | Süre | Çıktı (inceleyeceğin prototip) |
|---|---|---|
| M0 Spike | 2-3 gün | CLI durum çıktısı |
| M1 Çekirdek+CLI | 1 hf | `auxy set ...` |
| M2 GUI Pano | 1 hf | İlk pencere |
| M3 Tray+Başlangıç | 1 hf | Tray ajanı |
| M4 Tarama | 1-1.5 hf | Tarama ekranı |
| M5 Karantina | 1-1.5 hf | Kasa |
| M6 Tam kapsam | 2 hf | Tüm ayarlar |
| M7 Gerçek zamanlı | 1 hf | Otomatik tarama |
| M8 Sağlamlaştırma | 1 hf | Performans raporu |
| M9 Paketleme | 1 hf | Kurulum dosyası |
| **Toplam** | **~10–12 hafta** | |

---

## 7. Risk Kaydı
| Risk | Olasılık | Etki | Önlem |
|---|---|---|---|
| Tamper Protection ayarları engeller | Yüksek | Orta | Algıla, kullanıcıyı yönlendir; bypass deneme |
| WMI sınıfları sürümler arası farklı | Orta | Orta | PowerShell yedek katmanı, soyutlama |
| Kasa şifre anahtarı kaybı | Düşük | Yüksek | DPAPI + yedek anahtar dışa aktarma |
| Yanlışlıkla sistem dosyasını karantinaya alma | Orta | Yüksek | Koruma listesi + onay + geri yükleme |
| Defender'ı kapalı unutma | Orta | Yüksek | Otomatik geri açma, tray'de kırmızı rozet |
| GUI donması (uzun tarama) | Orta | Düşük | İş parçacığı/subprocess + olay kuyruğu |
| Antivirüs yazılımı Auxy'yi şüpheli bulur (PyInstaller) | Orta | Düşük | Kendi imzası/dışlaması, `--onedir`, ileride Nuitka |

---

## 8. Varsayımlar (itiraz edersen değiştiririm)
1. Tek kullanıcılı, kişisel kullanım; Windows 11, Microsoft Defender birincil AV.
2. Arayüz dili **Türkçe** (i18n altyapısıyla, sonradan İngilizce eklenebilir).
3. Ağ trafiği yok (telemetri yok); VirusTotal vb. yalnızca opt-in.
4. Kendi tarama motoru yazılmayacak; Defender motoru sarılacak.

## 9. Bir Sonraki Adım
Onayınla **M0**'a başlarım: repo iskeleti, `pyproject.toml`, `docs/` yapısı ve `auxy status` prototipi.
