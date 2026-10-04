# M1 – Çekirdek Kütüphane + CLI

**Durum:** İncelemede (3/5 ayar gerçek makinede doğrulandı; `realtime` ve `maps` Windows tarafından engelleniyor)  **Tarih:** 2026-10-04

## 1. Hedef
UI'dan bağımsız, test edilebilir bir servis katmanı: Defender ayarlarını okuma, **güvenli** yazma,
orijinal değere geri alma ve CLI (`auxy get / set / revert`).

## 2. Kapsam / Kapsam dışı
- Kapsam: 5 ayar (realtime, maps, pua, cfa, netprot), yedek/geri alma, yönetici ve Tamper algılama, günlük, UAC ile yükseltme (`--elevate`), `pip install -e .`.
- Kapsam dışı: tarama, güvenlik duvarı, SmartScreen vb. (M4/M6), GUI (M2).

## 3. Prototip: nasıl çalıştırılır
Proje klasöründe (artık `PYTHONPATH` gerekmiyor, paket editable kurulu):
```powershell
.\.venv\Scripts\python -m auxy get                    # tüm ayarlar
.\.venv\Scripts\python -m auxy get realtime           # tek ayar
.\.venv\Scripts\python -m auxy set maps advanced --elevate   # UAC ister
.\.venv\Scripts\python -m auxy revert --elevate       # orijinale dön
.\.venv\Scripts\python -m pytest -q
```
`--elevate` yeni bir yönetici konsolu açar, sonucu gösterir ve Enter bekler. Yönetici terminalindeysen `--elevate` gerekmez.

Geçerli değerler: `realtime` on/off · `maps` off/basic/advanced · `pua`, `cfa`, `netprot` off/on/audit.

Gerçek çıktı (yönetici olmayan oturum):
```
  realtime Gercek zamanli koruma           : on
  maps     Bulut koruma (MAPS)             : basic
  pua      Istenmeyen uygulama korumasi    : on
  cfa      Denetimli klasor erisimi        : off
  netprot  Ag korumasi                     : off
```

## 4. Yapılanlar
- [x] `core/settings.py`: ayar tablosu (izinli anahtar ve değerler), PowerShell'e yalnızca sabit parametre + doğrulanmış bool/int girer
- [x] `core/service.py`: `DefenderService` (`get_all`, `set`, `revert`); bağımlılıklar enjekte edilir (test için)
- [x] `core/backup.py`: orijinal değer yedeği (`%LOCALAPPDATA%\AuxySecurity\backup.json`), atomik yazım, bozuk dosya toleransı
- [x] `core/log.py`: dönen dosya günlüğü (`...\logs\auxy.log`); her ayar değişikliği kaydedilir
- [x] `core/system.py`: `relaunch_as_admin` (ShellExecute `runas`)
- [x] Hata sınıfları: `NotAdminError`, `TamperBlockedError`, `UnknownSettingError`
- [x] CLI: `get`, `set`, `revert`, `--elevate`; geçersiz değer yetki kontrolünden **önce** reddedilir
- [x] 22 birim testi (Defender taklidi ile)

## 5. Teknik kararlar
- **Orijinal-koruma kuralı:** Bir ayarın ilk değişikliğinde eski değer yedeklenir; sonraki değişiklikler yedeğin üstüne yazmaz. `revert` her zaman kullanıcının başlangıç durumuna döner (test: `test_original_not_overwritten_by_second_change`).
- **Yazma sonrası doğrulama:** `Set-MpPreference` hata vermese de Defender değeri uygulamayabilir (Tamper/grup ilkesi). Servis yazdıktan sonra WMI'dan geri okur; uygulanmadıysa hata verir ve yedeği geri alır.
- **Tamper erken engeli:** Tamper açıkken `realtime` ve `maps` için komut hiç çalıştırılmaz; kullanıcıya elle kapatma yolu söylenir. Bypass **denenmez**. (Not: Tamper bayrağı kapalı görünse de Windows bu iki ayarı yine engelleyebiliyor; asıl güvence yazma sonrası geri okumadır.)
- **Enjeksiyon önlemi:** Kullanıcı girdisi komuta girmez; değer tablodan seçilir (`test_invalid_key_and_value`).
- **Yedek konumu `%LOCALAPPDATA%`:** Ajan ve CLI aynı kullanıcıyla yükseltildiğinde aynı yolu görür. Farklı yönetici hesabı kullanılırsa yol değişir (bkz. bilinen sorunlar).

## 6. Kabul kriterleri ve sonuçlar
| Kriter | Sonuç |
|---|---|
| Birim testleri (mock) | ✔ 22 passed |
| Yönetici olmayan oturumda `get` çalışır | ✔ gerçek makinede |
| Yönetici olmayan oturumda `set`/`revert` temiz hata verir (rc=3), hiçbir şey değişmez | ✔ gerçek makinede |
| Geçersiz değer reddedilir (rc=2) | ✔ |
| Gerçek makinede yönetici yazma testi | ✔ **Kısmen.** Aşağıdaki tabloya bak |
| Hata durumları temiz (uygulanmadı tespiti) | ✔ Gerçek makinede `maps` için doğrulandı, kullanıcı hata mesajını gördü |

### Gerçek makinede yönetici yazma testi (2026-10-04)
Her ayar yazıldı, WMI'dan geri okundu, eski değere döndürüldü (hepsi geri alındı, son durum başlangıçla aynı).

| Ayar | Yazma | Geri alma | Sonuç |
|---|---|---|---|
| `pua` (1→0→1) | ✔ değişti | ✔ | **Çalışıyor** |
| `cfa` (0→1→0) | ✔ değişti | ✔ | **Çalışıyor** |
| `netprot` (0→1→0) | ✔ değişti | ✔ | **Çalışıyor** |
| `realtime` (açık→kapalı) | ✘ komut hatasız döndü, değer değişmedi | – | **Windows sessizce yok sayıyor** |
| `maps` (1→2), int ve isim (`Advanced`) ile | ✘ aynı | – | **Windows sessizce yok sayıyor** |

Bulgu: `IsTamperProtected` bu makinede `False` (kaynak: "E3 transition", `TamperProtection` kayıt değeri 0),
**yine de** `realtime` ve `maps` dışarıdan değişmiyor. Yani Tamper bayrağına güvenip "yazılabilir" demek yanlış;
doğru ölçüt **yazdıktan sonra geri okumak**; servis bunu zaten yapıyor. Bu yüzden "uygulanmadı" hatası bir bug değil, doğru tespit.
Grup ilkesi / MDM / Azure AD yönetimi yok (kayıt defteri ve `dsregcmd` ile kontrol edildi).

**Karar gerektiren konu (bkz. bölüm 8):** `realtime` ve `maps` için doğrudan yazma çalışmıyor.

## 7. Performans ölçümü
- `get`: tek WMI sorgusu, ~100 ms (M0 ölçümüyle aynı).
- `set`: PowerShell süreci (~0.5–1 sn) + 2 WMI okuması. Tek seferlik işlem olduğu için kabul edilebilir; GUI'de iş parçacığında çalışacak (M2).
- Boşta yük: yok, bu milestone'da arka plan süreç yok.

## 8. Bilinen sorunlar / Riskler
- **`realtime` ve `maps` bu makinede `Set-MpPreference` ile değişmiyor** (yukarıdaki tablo). Hızlı aç/kapat hedefinin en görünür parçası olan gerçek zamanlı koruma anahtarı doğrudan çalışmıyor.
  - Denenen ve **engellenen** yol: `HKLM\SOFTWARE\Policies\Microsoft\Windows Defender` altına `DisableRealtimeMonitoring`/`SpynetReporting` ilke değeri yazmak. Claude Code'un otomatik izin sistemi bunu "güvenliği zayıflatma" olarak reddetti; bu yolu atlatmaya çalışmadım. Ayrıca kalıcı ilke yazmak Windows Security'de "kuruluşunuz yönetiyor" uyarısı çıkarır ve geri alınması unutulabilir.
  - Kalan seçenekler (M3'te ele alınacak): (a) `realtime`/`maps` için salt-okunur durum + `windowsdefender://threatsettings` kısayolu; (b) Windows Security arayüzünü otomasyonla tıklamak (kırılgan, önerilmez); (c) kullanıcı açıkça isterse ilke yolu, süre sınırı ve otomatik geri alma ile.
  - Mevcut hata mesajı artık kullanıcıyı Windows Security'ye yönlendiriyor.
- `Set-MpPreference` çıktısı Türkçe Windows'ta yerelleştirilmiş hata verebilir; olduğu gibi gösteriliyor.
- Yedek, kullanıcıya özel (`%LOCALAPPDATA%`). Standart kullanıcıdan yönetici hesabına yükseltme (farklı hesap) yedek yolunu değiştirir; M3'te ajan tek hesapla çalışacağı için sorun olmayacak, gerekirse `%ProgramData%`'ya taşınır.
- Defender dışında bir üçüncü taraf AV kuruluysa WMI sınıfları farklı davranabilir (bu makinede test edilemez).
- `Set-MpPreference` değişikliğinden sonra Defender'ın WMI'da güncellemesi gecikirse yanlış "uygulanmadı" hatası olabilir; gerçek testte görülürse kısa bekleme/yeniden deneme eklenecek.

## 9. İnceleme notları
_(Senin geri bildirimin buraya eklenecek.)_

## 10. Sonraki milestone'a etkisi
M2 (GUI pano) bu servisi doğrudan kullanacak. `set` iş parçacığında çağrılacak; GUI'den UAC için ya uygulama baştan yönetici çalışacak ya da (M3) ajan yüksek yetkili görevle başlayacak.
