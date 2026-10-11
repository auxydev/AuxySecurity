# M12 – Ön ayarlar (tek tıkla çoklu ayar)

**Durum:** İncelemede  **Tarih:** 2026-10-11  **Sürüm:** 1.4.0

## 1. Hedef
Kullanıcı isteği: "en iyi hız, en güvenilir bağlantı, en gizli bağlantı gibi ön ayarlar; seçince birden fazla ayar
otomatik değişsin."

## 2. Kapsam / Kapsam dışı
- Kapsam: 5 ön ayar, plan + onay, tek UAC, geri alma, CLI.
- Kapsam dışı: kullanıcı tanımlı ön ayarlar, ağa göre otomatik seçim, tray menüsü (BACKLOG).
- Dokunulmayanlar (bilinçli): Defender korumaları, GoodbyeDPI hizmeti, dosyalar, SmartScreen.

## 3. Nasıl çalıştırılır
```powershell
python -m auxy gui                      # Ön ayarlar sayfası
python -m auxy preset list
python -m auxy preset plan gizli        # ne değişecek? (hiçbir şeyi değiştirmez)
python -m auxy preset apply hiz --yes   # uygula (yönetici adımları için tek UAC)
python -m auxy preset revert            # önceki ayarlara dön
```

## 4. Ön ayarlar
| Ön ayar | DNS | WARP | Tor | Diğer |
|---|---|---|---|---|
| **En iyi hız** | bu ağda **ölçülen** en hızlı, kirletmeyen (şifresiz) | kapat | kapat + vekil eski haline | – |
| **En güvenilir** | Quad9 + şifreli (şifresize düşebilir: kopma yok) | dokunma | kapat | kapalı güvenlik duvarı profillerini aç |
| **En gizli** | Cloudflare + şifreli, **sıkı** | `WARP + DoH` kipi, bağlan | kapat | reklam kimliği ve kişiselleştirme kapalı, rastgele Wi-Fi MAC |
| **Maksimum gizlilik (Tor)** | En gizli ile aynı | aynı | başlat + Windows vekili Tor'a | aynı |
| **Yurt / kısıtlı ağ** | bu ağda ölçülen en iyi (+ şifreli) | `WARP` kipi (tüm trafik tünelde), bağlan | dokunma | – |

## 5. Yapılanlar
- `core/presets.py`: **saf plan mantığı** (`build_plan`: mevcut durum → değişiklik listesi; zaten istenen değerdekiler
  atlanır), uygulama (`execute`), geri alma (`revert_plan`/`execute_revert`), okunur özet (`describe`).
- **Tek UAC:** DNS, rastgele MAC ve güvenlik duvarı adımları `presetadmin` yükseltilmiş yardımcısında birleştirilir
  (izin listesinde); girdiler UAC'ye gitmeden önce doğrulanır. Bir adım hata verse diğerleri denenir, sonuç adım adım raporlanır.
- **Geri alma:** uygulamadan önce `preset_state.json`'a önceki durum yazılır (gizlilik anahtarları, MAC, WARP kipi/bağlantı,
  Tor, vekil, güvenlik duvarı); DNS'in eski hali zaten `dns_backup.json`'da. Art arda ön ayar uygulanırsa **ilk (asıl) durum**
  korunur. Güvenlik duvarı güvenlik gereği geri **kapatılmaz** (bilgi notu verilir).
- **Uyarılar:** WARP bağlıyken DNS'i WARP yönetir; GoodbyeDPI `--dns-addr` ile DNS'i yönlendiriyorsa DNS ayarı etkisiz kalır.
- Sayfa: kart başına simge, açıklama, madde madde ne yaptığı; etkin ön ayar vurgulanır; "Önceki ayarlara dön".

## 6. Kabul kriterleri ve sonuçlar
| Kriter | Sonuç |
|---|---|
| Gerçek makinede plan üretimi (`preset plan hiz/guvenilir/gizli/tor`) | ✔ gerçek DNS/WARP/Tor/MAC durumuna göre mantıklı planlar; zaten istenen değerler atlandı |
| Plan mantığı, uygulama, hata sürekliliği, UAC reddi, geri alma, zincirleme | ✔ 27 yeni test (sahte yürütücülerle) |
| Girdi doğrulaması UAC'den önce | ✔ |
| Testler | ✔ 516 test |

## 7. Bilinen sorunlar / Riskler
- **Gerçek uygulama bu makinede DENENMEDİ:** canlı ağı (DNS, WARP, MAC, Tor) değiştirir. Mantık ve komut dizileri birim
  testlerle ve `-WhatIf` kuru çalıştırmayla (M11) doğrulandı; ilk gerçek denemeyi sen yapmalısın. Sorun olursa
  *Önceki ayarlara dön* ya da Windows ayarları.
- "En iyi hız" ölçümü o andaki ağ koşuluna bağlıdır; tekrar çalıştırınca farklı sonuç çıkabilir.
- "En gizli" sıkı DoH: ağ 443'ü engelliyorsa DNS çözümü başarısız olabilir (o durumda *En güvenilir* ya da *Geri al*).
- WARP kurulu/Tor kurulu değilse ilgili adımlar atlanır ve plan bunu söyler.

## 8. İnceleme notları (kullanıcı geri bildirimi)
(Bekleniyor.)

## 9. Sonraki milestone'a etkisi
Yok.
