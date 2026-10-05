# Backlog

Kapsam dışı fikirler buraya girer; mevcut milestone genişlemez. (Güncel: 2026-10-05)

## Sırada (v1.0 yolunda)
- **M9** Paketleme: `Program Files` kurulumu (T1 riskini kapatır), kurulum dosyası, imzalama, veri yolunu Store-sanallaştırmasından çıkarma + taşıma, kaldırıcı (`auxy cleanup` mantığı hazır), yükseltilmiş yardımcı alt komut listesini daraltma

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
