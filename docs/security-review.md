# Güvenlik Gözden Geçirmesi (M8)

**Tarih:** 2026-10-05  **Kapsam:** `src/auxy` (≈ 4.400 satır), bağımlılıklar, UAC/yükseltme akışı, kasa, dış komut çağrıları  
**Yöntem:** kod taraması (ağ/`eval`/`shell=True` aramaları), tehdit modeli, bağımlılık taraması (`pip-audit`), gerçek makinede saldırı senaryosu testleri, regresyon testleri.

## 1. Varlıklar ve güven sınırları

| Varlık | Neden önemli |
|---|---|
| Yönetici yetkisi | UAC ile ya da yüksek yetkili görevle çalışan kod, kullanıcının tüm sistemini değiştirebilir |
| Sistem güvenlik ayarları | Yanlış/kötü niyetli değişiklik korumayı kapatır |
| Karantina kasası ve anahtarı | Kullanıcı verisi; zararlı dosyalar |
| Günlük / yedek dosyaları | Yollar, ayar geçmişi |

```
 Aynı kullanıcı hesabındaki diğer süreçler (GÜVENİLMEZ olabilir)
        │  dosya sistemi, kayıt defteri (HKCU), %TEMP%, adlı nesneler
 ┌──────▼────────────────────────┐   UAC    ┌─────────────────────────────┐
 │ AuxySecurity GUI / ajan       │ ───────▶ │ yükseltilmiş yardımcı süreç │
 │ (standart kullanıcı yetkisi)  │ ◀─ JSON ─│ (yönetici)                  │
 └──────┬────────────────────────┘          └──────────────┬──────────────┘
        │ WMI, olay günlüğü, MpCmdRun, PowerShell           │ Set-MpPreference, Set-NetFirewall…, kayıt defteri
 ┌──────▼───────────────────────────────────────────────────▼──────────────┐
 │ Windows / Microsoft Defender (güvenilir)                                 │
 └──────────────────────────────────────────────────────────────────────────┘
```

**Temel varsayım:** Kullanıcı hesabında çalışan bir saldırgan kod olabilir, ama yönetici olamaz. Amaç: bu kodun AuxySecurity üzerinden **yönetici yetkisi kazanmasını** ve **güvenlik ayarlarını sessizce zayıflatmasını** önlemek.

## 2. Bulgular ve durum

| # | Tehdit | Önem | Durum | Önlem / kanıt |
|---|---|---|---|---|
| T1 | **UAC/görev ile çalışan kod, kullanıcının yazabildiği dizinden gelir** (`.venv`, `src`): kullanıcı hesabındaki zararlı, bu dosyaları değiştirip bir sonraki UAC onayında ya da oturum açılışında **yönetici yetkisi** kazanır | **Yüksek** (yalnızca geliştirme kurulumunda) | ⚠ **AÇIK (kabul edilmiş, görünür)** | `auxy doctor` ve Ayarlar uyarısı konumu tespit eder; yüksek yetkili başlangıç görevi kurarken **açık onay** ister; CLI uyarı yazar. Kalıcı çözüm M9: Program Files'a kurulum |
| T2 | **Sonuç dosyası saldırısı:** yükseltilmiş yardımcı `%TEMP%` altındaki sonuç dosyasına yazar; saldırgan dosyayı sembolik bağlantı/sabit bağlantı yapıp yönetici yetkisiyle rastgele dosya ezdirmeye çalışabilir | Yüksek | ✔ **KAPALI** | İki katman: (1) `resolve()` sonrası yol denetimi (yalnızca `%TEMP%\auxy-result-*`), (2) `open_result_file`: bağlantı/yeniden ayrıştırma noktası/hardlink reddi + denetim↔açış arası dosya kimliği (`st_ino`) doğrulaması (TOCTOU). Gerçek sembolik bağlantı ve hardlink ile test edildi, hedef dosya değişmedi |
| T3 | **Komut enjeksiyonu** (PowerShell/MpCmdRun) | Yüksek | ✔ **KAPALI** | Kullanıcı girdisi komut metnine **gömülmez**: ortam değişkeniyle (`$env:AUXY_ARG`) aktarılır; komutlar sabit; ayar adları/değerleri izinli listeden; MpCmdRun argümanları liste olarak. `;`, `'`, `"`, `` ` ``, `$(…)`, akıllı tırnak içeren değerle gerçek PowerShell testi |
| T4 | **Kaynak kodda tehlikeli kalıplar** | Orta | ✔ Yok | `eval`, `exec`, `pickle`, `shell=True`, `os.system`, ağ kütüphaneleri (`requests/urllib/socket/http`) için tarama: **sıfır** sonuç. `subprocess` yalnızca 10 sabit noktada |
| T5 | **Ağ trafiği / veri sızdırma** | Orta | ✔ Yok | Uygulama kendi başına ağ bağlantısı kurmaz; imza güncelleme Windows'un `MpCmdRun`'ıyla yapılır. Telemetri yok |
| T6 | **Kasa anahtarı**: DPAPI kullanıcı kapsamlı, aynı kullanıcı olarak çalışan zararlı anahtarı çözebilir | Orta | ⚠ **Sınır (belgeli)** | Kasa, *aynı hesaptaki zararlıya karşı gizlilik* sağlamaz; amacı dosyayı **çalıştırılamaz/izole** etmek ve Defender dışı dosyalar için karantina sunmaktır |
| T7 | **Kasa bütünlüğü** (kurcalama, kesme, sıralama, yanlış anahtar) | Orta | ✔ **KAPALI** | AES-256-GCM parçalı AEAD + "son parça" bayrağı; her durum için test; geri yüklemede özet doğrulama; silmeden önce kasadaki kopya doğrulanır |
| T8 | **Anahtar yedeği parolası zayıf** | Orta | ⚠ Kısmi | scrypt (n=2¹⁵), en az 8 karakter. Parola gücü kullanıcıya bağlı; dosya veri dizininin **dışına** yazılır |
| T9 | **Yetki kaybı = veri kaybı** (profil silinir, DPAPI anahtarı gider) | Orta | ✔ Azaltıldı | Parola korumalı anahtar dışa/içe aktarma; içe aktarırken anahtarın kasadaki dosyaları gerçekten açtığı **doğrulanır** |
| T10 | **Güvenliği zayıflatma** (güvenlik duvarı kapatma, SmartScreen, dışlama, "İzin ver") | Orta | ✔ Kontrollü | Açık onay kutuları; dışlamada tüm sürücü/Windows dizini/çalıştırılabilir uzantı reddi; yalnızca kendi pasifleştirdiğimiz kural geri açılır; hepsi geri alınabilir ve yedekli; yazma sonrası **geri okuma doğrulaması** |
| T11 | **Sonsuz UAC döngüsü / UAC yorgunluğu** | Düşük | ✔ Kapalı | Yardımcı modunda yönetici alınamazsa yeniden yükseltmeye çalışmaz; geçersiz girdi UAC'ye hiç gitmez (önce doğrulanır) |
| T12 | **Günlükte hassas veri** | Düşük | ✔ Kabul | Yollar ve ayar değişiklikleri yazılır; **parola, anahtar, dosya içeriği asla**. Döner günlük (3×512 KB). Bildirim/günlükte dosya adı görünür |
| T13 | **HKCU sağ tık komutu** (aynı kullanıcı zararlısı komutu değiştirebilir) | Düşük | ⚠ Sınır | Zaten kullanıcı alanı; komut yalnızca kullanıcı yetkisiyle çalışır. Yükseltme yok |
| T14 | **Tarama kilidi adı** (başka süreç mutex'i tutup taramayı engelleyebilir) | Düşük | ⚠ Sınır | Yalnızca hizmet reddi (kullanıcı kendi oturumunda); ölen sürecin kilidi devralınır |
| T15 | **Bağımlılık açıkları** | Orta | ✔ Temiz | `pip-audit` (temiz kurulum): 7 bağımlılıkta bilinen açık **yok**; 12 bulgunun tamamı yalnızca `pip` aracında (uygulamayla dağıtılmaz) |
| T16 | **Kaynak sızıntısı / uzun süre çalışma** | Düşük | ✔ Temiz | 300 yenileme turu: iş parçacığı sabit, bellek ±0.3 MB, handle +11 (önbellek); ajan 30 sn'de CPU %0.000 |
| T17 | **Sessiz hata** (konsolsuz süreçte yakalanmamış istisna) | Orta | ✔ Kapalı | `threading.excepthook`, `sys.excepthook`, `unraisablehook`, Tk geri çağırma kancası → günlük; ajan çökerse nedeni günlüğe yazılır; **Python istisnasında ajan içi denetçi yeniden başlatır, süreç ölümünde görevdeki tekrarlanan tetikleyici (10 dk, `IgnoreNew`) yeniden başlatır** (her ikisi gerçek makinede doğrulandı; ilk sürümdeki "hata durumunda yeniden başlat" ayarı Zamanlayıcı'da hata koduyla tetiklenmediği için bırakıldı) |

## 3. Bu inceleme sırasında yapılan sertleştirmeler
1. Sonuç dosyası güvenli açış (bağlantı/hardlink/TOCTOU) + iki katmanlı savunma testleri
2. Kurulum konumu riski tespiti (`core/hardening.py`), `doctor`/Ayarlar/CLI uyarıları, yüksek yetkili görev için onay
3. Bozuk `vault.db` için net hata (şifreli dosyalar korunur), bozuk `backup.json` **silinmeden kenara alınır**
4. Kasa anahtarı yedeği ve doğrulamalı geri yükleme
5. Yakalanmamış istisnaların günlüğe yazılması (daha önce konsolsuz süreçte kayboluyordu)
6. Testlerde gerçek diyalog açılmasının engellenmesi (test güvenliği)

## 4. Kalan riskler ve öneriler (M9 girdisi)
- **T1 en önemli kalan risk.** v1.0 paketi: `Program Files` altında (yalnızca yönetici yazar), imzalı yürütülebilir, görev oraya işaret eder. Geliştirme kurulumunda yüksek yetkili başlangıç görevi **önerilmez** (uyarı gösteriliyor).
- Yükseltilmiş yardımcının alt komut listesini daraltmak (şimdi tüm CLI alt komutlarını çalıştırabilir; hepsi kullanıcının UAC onayına bağlı): yalnızca yükseltme gerektiren komutlara izin veren bir "yönetici yardımcısı" giriş noktası.
- Yürütülebilir imzalama ve bütünlük (hash) doğrulaması.
- Kasa için isteğe bağlı parola ile ek koruma katmanı (T6'yı kısmen azaltır).

## 5. Doğrulanmayanlar
- ~~Görev Zamanlayıcı yeniden başlatması~~ M9'da gerçek testle doğrulandı (mekanizma değişti, bkz. T17).
- Çok kullanıcılı / alan (domain) ortamları, Windows 10.
