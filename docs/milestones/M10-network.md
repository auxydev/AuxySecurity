# M10 – Ağ güvenliği (GoodbyeDPI + WARP) ve görsel yenileme

**Durum:** İncelemede  **Tarih:** 2026-10-05  **Sürüm:** 1.1.0

## 1. Hedef
Kullanıcı isteği: ağ ile ilgili her şey ayrı bir **Ağ güvenliği** sayfasında olsun; bilgisayardaki **GoodbyeDPI**'ın durumu
(çalışıyor / durduruldu) ve Başlat / Kapat düğmeleri, **WARP**'ın bağlantı protokolleri bulunsun; bunlar için ayrıca bir şey
kurmak gerekmesin, **uygulama kurulurken arka planda kurulsun**. Ayrıca logo ve tray simgesi yenilendi (kalkan + hata rozeti).

## 2. Kapsam / Kapsam dışı
- Kapsam: sayfa, GoodbyeDPI hizmet yönetimi, WARP yönetimi (`warp-cli`), kurulumda otomatik kurulum, kaldırmada temizlik,
  `doctor` denetimi, CLI (`auxy netsvc`), logo/tray rozeti.
- Kapsam dışı: GoodbyeDPI/WARP ön ayarlarını (Türkiye alternatifleri vb.) uygulamadan düzenleme; WARP hesap/kayıt yönetimi.

## 3. Nasıl çalıştırılır
```powershell
python -m auxy gui                         # Ağ güvenliği sayfası
python -m auxy netsvc status               # GoodbyeDPI + WARP durumu (yönetici istemez)
python -m auxy netsvc gdpi-start           # hizmeti başlat (UAC)
python -m auxy netsvc warp-protocol WireGuard
python -m auxy netsvc warp-mode warp+doh
AuxySecurity-Setup.exe /S /NOGDPI /NOWARP  # ağ araçlarını kurmadan kur
```

## 4. Yapılanlar
- **Sayfa** (`gui/network_page.py`): güvenlik duvarı kartları Güvenlik sayfasından **taşındı**; GoodbyeDPI kartı (durum,
  Başlat/Kapat, otomatik başlatma anahtarı, güvenli konuma taşı/kur); WARP kartı (durum, Bağlan/Kes, protokol, kip).
- **Çekirdek** (`core/netservices.py`): hizmet durumu `win32service` ile (**yönetici gerekmez**); başlat/durdur/başlangıç
  türü/kaydet/kaldır yönetici ister (`netsvc` yükseltilmiş yardımcı alt komutu, izin listesinde). WARP `warp-cli` ile
  (yönetici gerekmez): `connect`, `disconnect`, `tunnel protocol set MASQUE|WireGuard`, `mode warp|warp+doh|doh|…`.
- **Kurulumda otomatik kurulum:** `build.ps1` makinedeki GoodbyeDPI paketini (`x86`, `x86_64`, lisanslar) uygulamaya
  `tools\goodbyedpi` olarak gömer; kurucu hizmeti kaydeder. Hizmet **zaten varsa** exe yolu güvenli konuma taşınır,
  **argümanlar, başlangıç türü ve çalışma durumu korunur**; yoksa Türkiye ön ayarıyla *elle başlatılacak* şekilde oluşturulur.
  WARP yoksa `winget install --id Cloudflare.Warp` sessizce çalışır (WARP yeniden dağıtılamaz; resmi paket kullanılır).
  Güncellemede çalışan goodbyedpi.exe önce durdurulur, sonra yeniden başlatılır.
- **Kaldırma:** yalnızca **bu kurulumdaki** GoodbyeDPI hizmeti (ve WinDivert sürücüsü) kaldırılır; başka konumdaki hizmete
  dokunulmaz. WARP kalır (bağımsız bir uygulama).
- **Logo/tray:** mavi kalkan + A (exe, pencere, görev çubuğu); tray'de sağlıklıyken yeşil tik, sorun varsa kalkan üzerinde
  rozet: kritik varsa **kırmızı** (kritik sayısı), yoksa **turuncu** (uyarı sayısı), 10+ → `9+`.
- `doctor`: GoodbyeDPI hizmeti konumu denetimi.

## 5. Teknik kararlar
- **GoodbyeDPI güvenlik riski (yeni bulgu, T18):** hizmet SİSTEM olarak çalışır; kullanıcının makinesinde exe Masaüstü
  (OneDrive) altındaydı. O klasöre yazabilen herhangi bir kullanıcı-yetkili program exe'yi/WinDivert sürücüsünü
  değiştirip **SİSTEM yetkisi** alabilirdi. Çözüm: yalnızca yönetici-yazılabilir konumdaki (Program Files vb.) exe hizmete
  kaydedilir; riskli mevcut hizmet için `doctor` ve sayfa uyarır, kurucu onu taşır.
- **WARP kipi/protokol okuma:** `warp-cli -j settings` JSON'u (`operation_mode`, `warp_tunnel_protocol`); `warp_doh` →
  `warp+doh` eşlemesi `normalize_mode` ile.
- GoodbyeDPI ikilileri **depoya girmez** (derleme çıktısı depo dışı); kaynak `AUXY_GOODBYEDPI_DIR` ya da makinedeki hizmetin klasörü.

## 6. Kabul kriterleri ve sonuçlar
| Kriter | Sonuç |
|---|---|
| Gerçek makinede durum okuma (GoodbyeDPI hizmeti, WARP) | ✔ `netsvc status`: GoodbyeDPI durduruldu/otomatik; WARP bağlı, MASQUE, kip DoH |
| Sayfa görünümü (PrintWindow ekran görüntüsü) | ✔ `docs/screenshots/ag-guvenligi.png` (örnek veriyle, kişisel yol yok) |
| Kurulu sürümle gerçek kurulum (Program Files, UAC) | ✔ GoodbyeDPI hizmeti `Program Files\AuxySecurity\tools\goodbyedpi\x86_64\goodbyedpi.exe`'ye taşındı; **argümanlar ve otomatik başlatma korundu**, durum Durduruldu kaldı |
| `doctor` | ✔ 20 tamam, 0 uyarı, 0 hata (öncesinde Masaüstü yolu uyarı verirdi) |
| Geçici klasöre kurulum (güvenilmeyen konum) | ✔ hizmet kaydı reddedildi, kullanıcının hizmetine dokunulmadı; kaldırma da dokunmadı |
| Testler | ✔ 444 test (30 yeni), toplam kapsam **%87** (öncesi %89): `netservices.py` %56 — yönetici gerektiren `win32service` yazma işlevleri (başlat/durdur/kaydet/kaldır) birim testinde çalıştırılamadı, yalnızca gerçek kurulumda `install_service` yolu denendi |

## 7. Performans ölçümü
Sayfa yalnızca açılınca/Yenile'de okur (3 küçük iş parçacığı: hizmet sorgusu, `warp-cli status/settings`, kayıt defteri). Tray ajanı
değişmedi; arka plan yoklaması yok.

## 8. Bilinen sorunlar / Riskler
- **Gerçek makinede DENENMEDİ** (yalnızca birim testleri, sahte nesnelerle): GoodbyeDPI **Başlat/Kapat/otomatik başlatma**
  değişikliği, WARP **Bağlan/Kes**, **protokol** ve **kip** değiştirme. Bunlar kullanıcının canlı ağ bağlantısını etkiler;
  otomatik denetim bu eylemleri engelledi, bu yüzden kullanıcı denemeli. Mantık `sc`/`warp-cli` çıktılarıyla değil, API
  çağrılarıyla ve komut dizisi doğrulamasıyla test edildi.
- `warp-cli tunnel protocol set` çıktıda "(network policy)" ve "Consumer only" ibaresi var: kurum ilkesi tarafından
  yönetiliyorsa değişiklik reddedilebilir; sayfa WARP'ın hata metnini gösterir.
- WARP'ın `winget` ile kurulumu internet ve (MSI için) UAC gerektirir; gerçek bir sıfırdan kurulum bu makinede denenemedi
  (WARP zaten kurulu).
- GoodbyeDPI, WinDivert sürücüsü yükler; bazı antivirüsler bunu "HackTool" diye işaretleyebilir.

## 9. İnceleme notları (kullanıcı geri bildirimi)
(Bekleniyor.)

## 10. Sonraki milestone'a etkisi
Yok; v1.x bakım işleri [BACKLOG](../../BACKLOG.md)'ta.
