# Backlog

Kapsam dışı fikirler buraya girer; mevcut milestone genişlemez. (Güncel: 2026-10-05)

## Sırada (v1.0 sonrası)
- Kurulum programını ve exe'leri gerçek sertifikayla imzala (`scripts/sign.ps1` hazır, denenmedi)
- Windows 10 / temiz VM'de kurulum-kaldırma denemesi
- Uygulama içi güncelleme (şu an: yeni Setup'ı üstüne kur)
- Kurulum klasörüne açık ACL denetimi (şu an `Program Files` varsayılanına güvenilir)

## Fikirler
- YARA kural taraması
- VirusTotal hash sorgusu (yalnızca hash, opt-in)
- Açık port / ağ bağlantısı görüntüleyici
- Başlangıç öğeleri denetçisi
- Ayar profili dışa/içe aktarma
- Güvenlik duvarı: kural **ekleme** (şu an: listele, pasifleştir, program engelle)
- Bildirimde eylem düğmeleri (şu an: tray menüsünde "Tehdidi kasaya al")
- Kasa: arama, etiket, sayfalama
- Çoklu dil (i18n altyapısı; arayüz şu an Türkçe)

## Bilinçli olarak yapılmayanlar (neden: ilgili milestone dokümanı)
- `realtime` / `maps` değiştirme: Windows engelliyor (M1, M3)
- Exploit protection yazma: geri alınamaz (M6)
- Edge SmartScreen, hesap koruması: güvenilir yol yok / yönlendirme istenmedi (M6, B01)
- Güvenli silme: SSD'lerde anlamsız (B01)

## Fiziksel olarak doğrulanması gerekenler
- Gerçek USB, haftalık tetiklenme, oturum açılışında otomatik başlama, bildirim balonu, gerçek fare sürüklemesi
- Güvenlik duvarı profili kapat/aç (`scripts/backfill_live_admin.py --firewall`), bellek bütünlüğünü gerçekten değiştirme, çevrimdışı tarama
