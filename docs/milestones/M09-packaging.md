# M9 – Paketleme ve v1.0

**Durum:** İncelemede  **Tarih:** 2026-10-05  **Sürüm:** 1.0.0

## 1. Hedef
Python kurmadan çalışan, `Program Files`'a kurulan, kaldırılabilen bir sürüm çıkarmak. Kurulu sürüm, güvenlik gözden
geçirmesindeki **T1** riskini (UAC ile çalışan kodun kullanıcının yazabildiği dizinden gelmesi) kapatır. Plan bölüm 5'teki M9.

## 2. Kapsam / Kapsam dışı
- Kapsam: PyInstaller derlemesi, kurulum programı, kaldırıcı, eski veri taşıma, M8'de yanlış çıkan yeniden başlatma
  mekanizmasının düzeltilmesi, yükseltilmiş alt komut izin listesi, imzalama betiği, sürüm notları.
- Kapsam dışı / yapılamadı: **gerçek imzalama** (sertifika yok; betik hazır, denenmedi), Windows 10 ve temiz sanal
  makinede kurulum testi (bu makine dışında ortam yok).

## 3. Prototip: nasıl çalıştırılır
```powershell
.\scripts\build.ps1                 # %TEMP%\auxy-build\dist\AuxySecurity\ (+ payload.zip)
.\scripts\build_installer.ps1       # %TEMP%\auxy-build\AuxySecurity-Setup.exe  (~53 MB, tek dosya)
# (isteğe bağlı) $env:AUXY_PFX / AUXY_PFX_PASSWORD ayarla, sonra: .\scripts\sign.ps1

AuxySecurity-Setup.exe                                   # pencereli kurulum (UAC sorar)
AuxySecurity-Setup.exe /S /AUTOSTART /CONTEXTMENU        # sessiz; /DIR=… /DESKTOP /NOSTARTMENU
& "C:\Program Files\AuxySecurity\auxy.exe" doctor
& "C:\Program Files\AuxySecurity\AuxySecurity.exe" uninstall   # ya da Ayarlar → Uygulamalar
```
Derleme çıktısı depoda **tutulmaz** (`*.exe`, `*.zip`, `.ico`, `version_info.txt` git dışı; çıktı `%TEMP%` altında,
OneDrive eşleşmesin diye).

## 4. Yapılanlar
- **Çatı:** `AuxySecurity.exe` (pencereli; argümansız = GUI) ve `auxy.exe` (konsol) tek klasörü (`onedir`) paylaşır.
  Tüm başlatma komutları (yeniden yükseltme, başlangıç görevi, sağ tık menüsü, tray → GUI) donmuş uygulamaya duyarlı hale
  getirildi (`system.app_exe/app_args/launch_params`).
- **Kurulum programı** (`packaging/setup_entry.py`, `core/install.py`): yönetici ister; payload'u **zip-slip korumalı**
  açar, doğrular, kısayolları (Başlat/masaüstü) ve HKLM Uninstall kaydını yazar, isteğe bağlı başlangıç görevi ve sağ tık
  menüsü kurar; çalışan örnekleri kapatır; hata olursa adım adım bildirir. Uygulama kurulumdan sonra **yükseltilmemiş**
  kullanıcı olarak başlatılır (explorer üzerinden).
- **Kaldırıcı** (`auxy.exe uninstall`): görev, sağ tık menüsü, kısayollar, kayıt silinir; dosyalar çıkıştan sonra silinir.
  **Veri korunur** (`--remove-data`: kasada dosya varsa reddeder, `--force-vault` ile zorlanır).
  Yalnızca **bu kurulumu gösteren** görev/menü girdileri kaldırılır.
- **Eski veri taşıma** (`core/migrate.py`): Store Python verisi gerçek `%LOCALAPPDATA%\AuxySecurity`'ye **kopyalanır**
  (üzerine yazmaz, silmez). `auxy migrate-data --yes`; kurulu GUI ilk açılışta sorar; `doctor` uyarır.
- **Yeniden başlatma düzeltmesi (M8 hatası):** M8'de "`RestartOnFailure` ile ajan çökünce yeniden başlar" demiştim.
  Gerçek Görev Zamanlayıcı testinde (`scripts/scheduler_restart_test.ps1`) **sıfırdan farklı çıkışta yeniden başlatmadığı**
  görüldü (3 dakikada 1 çalışma). Yerine: (a) ajan içinde `supervisor.supervise` (5 çökme / 10 dk, bekleme 2-5-15-30-60 sn),
  (b) görevde 10 dakikada bir **tekrarlayan tetikleyici + `IgnoreNew`** (çalışırken ikinci kopya yok, öldürülünce yeniden
  başlar; `scripts/scheduler_repeat_test.ps1` ile doğrulandı). M8 ve güvenlik dokümanları düzeltildi.
- **Yükseltilmiş alt komut izin listesi** (`ELEVATED_ALLOWED`): yükseltilmiş süreç yalnızca listedeki komutları çalıştırır
  (dışındakiler çıkış kodu 4).
- **Doctor:** donmuş "Sürüm" denetimi, eski veri, görev tekrar denetimi; `Program Files` konumu artık T1'i **OK** gösterir.
- `scripts/sign.ps1`, `scripts/build*.ps1`, `scripts/frozen_gui_check.py`, `CHANGELOG.md`.

## 5. Teknik kararlar
- **PyInstaller `onedir`** (tek dosya değil): her açılışta geçici klasöre açma yok → hızlı başlangıç, daha az Defender gürültüsü.
  Kurulum programı tek dosyadır (`onefile`, `--uac-admin`), uygulama payload'u içine gömülü.
- **Kendi kurucumuz** (Inno Setup yerine): ek araç bağımlılığı yok, aynı Python kodu test edilebilir (`tests/test_m9_install.py`).
- **Veri dizini taşınmaz, kopyalanır:** geri dönüş yolu açık kalsın.

## 6. Kabul kriterleri ve sonuçlar
| Kriter | Sonuç |
|---|---|
| Donmuş `auxy.exe --version/status/doctor` | ✔ 1.0.0; doctor'da bağımlılıklar ✔ (düzeltmeden sonra) |
| Donmuş GUI açılır (PrintWindow ile yalnız uygulama penceresi) | ✔ 0,5 sn'de pencere, 68 MB çalışma kümesi, çıkış kodu 0 |
| Donmuş ajan: bellek/CPU | ✔ ~25 MB özel bellek, %0 CPU (30 sn, yalıtılmış) |
| Defender özel taramasıyla derleme klasörü | ✔ tespit yok (tarama 2 sn sürdü; sonuç yanlış-pozitif yok, ama imzasız) |
| Sessiz kurulum (geçici klasör) + UAC | ✔ çıkış 0, dosyalar + HKLM kaydı |
| Kaldırma (UAC) | ✔ kayıt silindi, klasör çıkıştan sonra silindi, kullanıcının sağ tık menüsüne dokunulmadı |
| Gerçek kurulum `Program Files` + `/AUTOSTART /CONTEXTMENU` | ✔ doctor: Kurulum konumu ✔; görev `AuxySecurity.exe agent`, `HighestAvailable`, 10 dk tekrar; `schtasks /Run` ile ajan çalıştı |
| Eski veriyi taşıma | ✔ vault/backup/scan_history kopyalandı; doctor uyarısı kalktı |
| Testler | ✔ 414 test, kapsam **%89** |

**Gerçek testlerin yakaladığı hatalar (hepsi düzeltildi, birim testi eklendi):**
1. Donmuş `doctor` paket meta verisi yok diye bağımlılıkları ✘ gösteriyordu.
2. Donmuş exe çıkışında `IUnknown` iletisi: COM nesnesi `CoUninitialize`'dan sonra serbest kalıyordu (`del` + `gc` + sert çıkış).
3. Kaldırıcı `taskkill /IM auxy.exe` ile **kendini öldürüyordu** (çıkış 1, hiçbir adım uygulanmadan).
4. Çıkıştan sonra silme hiç çalışmıyordu: `subprocess` listesi iç tırnakları kaçırıp `cmd`'ye bozuk komut veriyordu → tek dizge.
5. Kaldırıcı, geliştirme kurulumuna ait sağ tık menüsünü de silecekti → yalnızca bu kurulumu gösterenleri siler.

## 7. Performans ölçümü
Uygulama klasörü 61 MB (`payload.zip` 29 MB, kurulum programı 53 MB). Ajan: ~25 MB özel, %0 CPU boşta. GUI açılışı 0,5 sn.

## 8. Bilinen sorunlar / Riskler
- **İmzasız:** SmartScreen "bilinmeyen yayıncı" uyarısı verebilir; `scripts/sign.ps1` sertifikayla denenmeli (**doğrulanmadı**).
- Windows 10, temiz VM, farklı kullanıcı hesabı ile kurulum **denenmedi**.
- Kurulum programı yalnızca bu makinede (Windows 11 Pro) denendi; `Program Files` kurulumu **güncelleme** senaryosu
  (üzerine kurma) geçici klasörde denendi, gerçek eski sürüm yükseltmesi değil.
- Kurulum klasörünün özel ACL'i yok: `Program Files`'ın varsayılan ACL'ine (yalnız yönetici yazar) güveniyoruz; `--dir`
  ile kullanıcı yazılabilir bir klasör seçilirse `doctor` T1 uyarısını verir.
- `taskkill /IM` ad bazlıdır: aynı adlı başka bir kurulumu da kapatır (kendimiz hariç).
- Bilinen fiziksel doğrulamalar: [BACKLOG](../../BACKLOG.md).

## 9. İnceleme notları (kullanıcı geri bildirimi)
(Bekleniyor.)

## 10. Sonraki milestone'a etkisi
Plan tamamlandı. v1.0.0 sonrası işler [BACKLOG](../../BACKLOG.md)'ta: imzalama, Windows 10 denemesi, güncelleme mekanizması.
