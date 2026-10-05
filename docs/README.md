# AuxySecurity Dokümantasyonu

Proje **sürekli prototipleme** ile geliştirildi: her milestone sonunda çalıştırılabilir bir prototip, test kanıtı ve
bir doküman çıkar. Her milestone dokümanı aynı 10 bölümlü şablonu izler (hedef, kapsam, nasıl çalıştırılır,
yapılanlar, kararlar, **kabul kriterleri ve gerçek sonuçlar**, performans, **bilinen sorunlar**, inceleme notları, sonraki adım).

## Milestone'lar

| Doküman | Konu |
|---|---|
| [M00 – Keşif](milestones/M00-spike.md) | Teknik varsayımların bu makinede doğrulanması (WMI, yetki, Tamper) |
| [M01 – Çekirdek + CLI](milestones/M01-core-cli.md) | Ayar okuma/yazma, yedek ve geri alma, Windows'un sessiz engeli bulgusu |
| [M02 – GUI pano](milestones/M02-gui-dashboard.md) | İlk arayüz, sağlık değerlendirmesi, iş parçacığı + kuyruk |
| [M03 – Tray ve başlangıç](milestones/M03-tray-autostart.md) | Tray ajanı, UAC akışı, Görev Zamanlayıcı |
| [M04 – Tarama](milestones/M04-scan-manager.md) | Hızlı/tam/özel tarama, iptal, tehdit listesi |
| [M05 – Karantina kasası](milestones/M05-quarantine-vault.md) | AES-256-GCM, DPAPI, geri yükleme |
| [M06 – Windows Güvenlik](milestones/M06-windows-security.md) | Güvenlik duvarı, SmartScreen, cihaz güvenliği, dışlamalar |
| [M07 – Gerçek zamanlı yardımcılar](milestones/M07-realtime-helpers.md) | Klasör izleme, olay aboneliği, USB, zamanlama, sağ tık |
| [B01 – Eksik tamamlama](milestones/B01-eksik-tamamlama.md) | M0–M7'de ertelenenlerin tamamlanması ve bulunan hatalar |

Şablon: [milestones/_TEMPLATE.md](milestones/_TEMPLATE.md)

## Diğer

- [Mimari](architecture.md) (taslak) · [Mimari kararlar](decisions/ADR-0001-wmi-vs-powershell.md)
- [Kapsamlı plan](../PLAN.md) · [Backlog](../BACKLOG.md)
- Ekran görüntüleri: `screenshots/` (README için temiz, örnek veriyle) · `milestones/img/` (milestone kanıtları)

## Okuma ipucu

Her milestone dokümanında **bölüm 6** (ne gerçekten çalıştı, kanıtıyla) ve **bölüm 8** (ne denenmedi / neden)
en değerli kısımlardır: "çalışıyor" iddiaları yalnızca gerçek makinede doğrulandıysa ✔ ile işaretlidir.
