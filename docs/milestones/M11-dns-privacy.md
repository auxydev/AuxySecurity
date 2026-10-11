# M11 – DNS, gizlilik ve Tor

**Durum:** İncelemede  **Tarih:** 2026-10-11  **Sürüm:** 1.3.0

## 1. Hedef
Kullanıcı isteği: (1) KYK/GSB yurt internetinde internet çok kötü; forumlarda "ODTÜ DNS'i ile hızlanıyor" deniyor →
uygulamada **DNS ayarları**; (2) siber güvenlik alanında gelişen biri olarak **ekstra gizlilik**; (3) **Tor** kullanılabilsin.

## 2. Kapsam / Kapsam dışı
- Kapsam: DNS seçimi + şifreli DNS (DoH) + **ölçüm tabanlı** hız/güvenlik testi, gizlilik ayarları (reklam kimliği,
  kişiselleştirme, rastgele Wi-Fi MAC), Tor (kur, başlat/durdur, köprüler, yeni kimlik, Windows vekili, doğrulama).
- Kapsam dışı: **gerçek "Tor VPN"** (tüm sistem trafiğini Tor'a zorlamak TUN sürücüsü ister), Tor'un kurucuya gömülmesi.

## 3. Nasıl çalıştırılır
```powershell
python -m auxy gui                          # "DNS ve gizlilik" sayfası
python -m auxy dns status                   # bağlı ağlar ve geçerli DNS (yönetici istemez)
python -m auxy dns bench                    # hız + güvenlik testi (yönetici istemez)
python -m auxy dns apply cloudflare --adapters 12 --doh      # UAC
python -m auxy dns apply "1.1.1.1,8.8.8.8" --adapters 12     # özel
python -m auxy dns reset --adapters 12      # eski haline (yedekten) / otomatiğe
python -m auxy privacy status | mac-on Wi-Fi | ad_id-off
python -m auxy tor install | start [--bridges obfs4] | verify | newnym | proxy-on | stop
```

## 4. ODTÜ DNS hakkında (araştırıldı, doğrulandı)
ODTÜ BİDB'nin DNS sunucuları **yalnızca ODTÜ IP aralığından (144.122.0.0/16) gelen özyinelemeli sorgulara** yanıt verir;
dışarıdan (ör. KYK yurdundan) kullanılamaz. Forumlardaki "ODTÜ DNS'i ile hız arttı" yorumları büyük olasılıkla ODTÜ
ağındakiler için geçerlidir ya da başka bir DNS'e geçmenin etkisidir. Bu yüzden hazır ayarlara **eklenmedi**; yerine
**ölçüm** eklendi (aşağıda). Kaynak: [ODTÜ BİDB](https://bidb.metu.edu.tr/en/node/10011).

## 5. Yapılanlar
- **DNS** (`core/dns.py`): bağlı fiziksel ağlar ve geçerli DNS (elle/otomatik); hazır ayarlar Cloudflare, Google, Quad9,
  AdGuard, OpenDNS (+ özel IP, 1-4 adet, doğrulanır); seçili ağlara atama (yönetici/UAC); **ilk değişiklikte eski ayar
  yedeklenir**, "Eski haline döndür" yedeği (yoksa DHCP'yi) geri yükler; önbellek temizleme.
- **Şifreli DNS (DoH):** Windows'un yerleşik DoH desteği (`Add/Set-DnsClientDohServerAddress`, AutoUpgrade). **Sıkı mod**
  şifreli bağlantı kurulamazsa şifresiz DNS'e düşmez.
- **Hız ve güvenlik testi:** her DNS'e gerçek UDP/53 sorgusu (6 alan adı × 2 tur, ortanca ms), **HTTPS/443 erişilebilirliği**
  (DoH çalışır mı), **NXDOMAIN kirletme tespiti** (var olmayan alan adına cevap dönüyorsa ağ/DNS yönlendiriyor) ve mevcut
  DNS'in kendisi de listelenir. "En iyisini seç" yalnızca hızlı + kirletmeyen + güvenilir olanı önerir.
- **GoodbyeDPI etkileşimi:** GoodbyeDPI `--dns-addr` ile UDP/53'ü kendi sunucusuna yönlendirdiğinden sistem DNS'i **etkisiz**
  kalır; sayfa bunu uyarır.
- **Gizlilik** (`core/privacy.py`): reklam kimliği ve kişiselleştirilmiş deneyimler (HKCU, yönetici gerekmez), **rastgele Wi-Fi
  MAC** (`netsh wlan set randomization`, UAC), isteğe bağlı "Ağ bilgimi göster" (Cloudflare izi: IP/ülke/WARP; tek istek,
  onaylı).
- **Tor** (`core/tor.py`): resmi *Tor Expert Bundle* yalnızca `dist.torproject.org`'dan indirilir, **SHA-256 doğrulanır**,
  güvenli çıkarılır (yol geçişi/bağlantı/aygıt reddi); yerel SOCKS5 (127.0.0.1:9050) + kontrol portu (çerezli, yalnız
  127.0.0.1); bağlanma yüzdesi canlı izlenir; **köprüler** (obfs4/snowflake/meek, paketle gelen listeden); yeni kimlik;
  **Windows vekili** anahtarı (eski ayar yedeklenir, Tor durunca geri alınır); **doğrulama** (check.torproject.org'a
  Tor üzerinden, alan adı vekile çözdürülür → DNS sızıntısı yok).
- Yeni sayfa **"DNS ve gizlilik"**; CLI: `auxy dns|privacy|tor`; yükseltilmiş izin listesine `dns` ve `privacy` eklendi.

## 6. Teknik kararlar
- **Tahmin yerine ölçüm:** "hangi DNS iyi" ağdan ağa değişir; uygulama kendi ağında test eder.
- **Tor VPN değil:** dürüst etiketleme (arayüzde ve kodda). Gerçek sistem-geneli Tor için TUN sürücüsü (kapsam dışı, BACKLOG).
- **Tor yönetici olarak çalışmaz:** indirilen exe kullanıcı yazılabilir klasörde (`%LOCALAPPDATA%\AuxySecurity\tor`); yükseltilmiş
  çalışırsa T1 tipi risk doğar → reddedilir.
- **Tor kurucuya gömülmedi** (kullanıcı tıklamasıyla indirilir): ikili dosya dağıtımı ve güncel kalma sorumluluğu yok.

## 7. Kabul kriterleri ve sonuçlar
| Kriter | Sonuç |
|---|---|
| Gerçek makinede ağ/DNS okuma, hız testi | ✔ `dns status` / `dns bench`: 5 sağlayıcı + mevcut DNS ölçüldü (telefon paylaşımlı ağda ~120-146 ms; kirletme yok) |
| Gerçek PowerShell betikleri (`-WhatIf` ile kuru çalıştırma) | ✔ `apply` (DoH + sıkı), `reset`, `flush`: sözdizimi ve cmdlet parametreleri geçerli, **hiçbir şey değişmedi** |
| `privacy status`, `tor status` | ✔ |
| Testler | ✔ 489 test (36 yeni), toplam kapsam %86; `dns.py` %82, `tor.py` %71 |

## 8. Bilinen sorunlar / Riskler
- **Gerçek DNS değişikliği, DoH ve rastgele MAC bu makinede UYGULANMADI** (canlı ağı etkiler; yalnızca `-WhatIf`
  kuru çalıştırma ve birim testleri). İlk denemede UAC çıkar; "Eski haline döndür" yedekten geri alır.
- **Tor gerçekten indirilmedi/çalıştırılmadı** (indirme kullanıcı tıklamasıyla; ikili dosya). İndirme, SHA-256, çıkarma, torrc,
  kontrol protokolü ayrıştırması, SOCKS5 el sıkışması ve vekil yedeği **sahte verilerle test edildi**. Beklenmeyen paket
  düzeni, köprü (`pt_config.json`) biçimi ve snowflake gerçek ağda doğrulanmadı.
- SHA-256 değeri aynı siteden gelir: **bütünlük** denetimidir; `sha256sums-signed-build.txt.asc` GPG imzası doğrulanmaz
  (GPG gerekir). Tor Browser'ı resmi siteden kurmak yine de en güvenli yoldur.
- Tor Türkiye'de/yurt ağlarında engelli olabilir; köprü gerekir. DNS/Tor, ağ yöneticisinin kurallarını ihlal etmemeli
  (yurt ağı kullanım şartlarını kontrol et).
- DoH, Windows 11'de çalışır; Windows 10 desteği sınırlı/denenmedi.

## 9. İnceleme notları (kullanıcı geri bildirimi)
(Bekleniyor.)

## 10. Sonraki milestone'a etkisi
Yok. Fikirler: gerçek Tor VPN (TUN), DNS kara liste/reklam engelleme, DNS-sızıntı testi, VPN kill-switch.
