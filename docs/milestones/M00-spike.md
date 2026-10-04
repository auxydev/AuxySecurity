# M0 – Keşif ve Teknik Doğrulama (Spike)

**Durum:** İncelemede  **Tarih:** 2026-10-04

## 1. Hedef
Plandaki teknik varsayımları bu makinede kanıtlamak ve `auxy status` çalışan prototipini çıkarmak.

## 2. Kapsam / Kapsam dışı
- Kapsam: repo iskeleti, Defender durumunu **okuma**, WMI–PowerShell karşılaştırması, ilk testler ve dokümanlar.
- Kapsam dışı: ayar **değiştirme** (M1), GUI (M2), tray (M3).

## 3. Prototip: nasıl çalıştırılır
Proje klasöründe PowerShell:
```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python -m auxy status          # durum çıktısı
.\.venv\Scripts\python scripts\bench_status.py # WMI/PowerShell ölçümü
.\.venv\Scripts\python -m pytest -q            # testler
```
Örnek çıktı (bu makine):
```
AuxySecurity 0.0.1  |  Yonetici: hayir
DURUM (salt-okunur)
  Gercek zamanli koruma     : ACIK
  Tamper Protection         : KAPALI
  Imza surumu               : 1.459.551.0
  Imza guncelleme           : 2026-10-04 09:11:54
AYARLAR
  Bulut koruma (MAPS)       : Temel
  PUA koruma                : Acik
  Denetimli klasor erisimi  : Kapali
  Ag korumasi               : Kapali
```

## 4. Yapılanlar
- [x] `git init`, `.venv` (Python 3.12.10), `pyproject.toml`, `.gitignore`
- [x] `src/auxy` paket iskeleti (`core/`, `__main__.py`)
- [x] `core/defender.py`: WMI ile `MSFT_MpComputerStatus` + `MSFT_MpPreference` okuma, DMTF tarih çevirme, `DefenderError`
- [x] `core/system.py`: `is_admin()`
- [x] `auxy status` komutu (Türkçe, ASCII çıktı)
- [x] `scripts/bench_status.py` performans ölçümü
- [x] 4 birim testi (WMI mock'lu)
- [x] `docs/`: şablon, mimari taslağı, ADR-0001; `BACKLOG.md`

## 5. Teknik kararlar
- [ADR-0001](../decisions/ADR-0001-wmi-vs-powershell.md): okuma için WMI (pywin32), PowerShell yedek.

## 6. Kabul kriterleri ve sonuçlar
| Kriter | Sonuç |
|---|---|
| Gerçek zamanlı koruma, imza sürümü, Tamper durumu doğru okunuyor | ✔ PowerShell `Get-MpComputerStatus` çıktısıyla eşleşti (RTP açık, Tamper kapalı, imza 1.459.551.0) |
| Okuma için yönetici yetkisi gerekmiyor | ✔ Yönetici olmayan oturumda çalıştı |
| ADR-0001 yazıldı | ✔ |
| Testler geçiyor | ✔ 4 passed |
| Yazma (ayar değiştirme) yöntemi doğrulandı | ✘ Bilerek yapılmadı, M1'e devredildi (sistem ayarına dokunmadan keşif) |

## 7. Performans ölçümü
| Ölçüm | Sonuç |
|---|---|
| PowerShell (status+pref, yeni süreç) | ~600 ms |
| WMI ilk çağrı | ~170 ms |
| WMI sonraki çağrı | ~100 ms |
| Python süreç RSS | 29 MB → 36 MB (WMI sonrası) |

Not: Bu makinede **PowerShell'in kendisi 6x yavaş** ve ayrı süreç açıyor; WMI seçimi doğrulandı. 36 MB, ajan için 40 MB hedefine çok yakın; M3'te `win32com` yükü ve pystray eklenince yeniden ölçülecek.

## 8. Bilinen sorunlar / Riskler
- **Tamper Protection bu makinede KAPALI.** Yazma testleri M1'de mümkün olacak, ancak kullanıcı açarsa engellenir; M1'de bu durum algılanacak.
- Ajan bellek bütçesi (40 MB) sıkı. Gerekirse `win32com` yerine hafif `ctypes` COM ya da Nuitka ile küçültme M8'de değerlendirilir.
- `PYTHONPATH=src` gerekiyor; `pip install -e .` ile kaldırılabilir (M1'de yapılacak).
- Proje OneDrive içinde: `.venv` kurulumu ve senkronizasyon yavaşladı. **Öneri:** projeyi OneDrive dışına taşımak ya da `.venv` klasörünü OneDrive'dan hariç tutmak.
- `git commit` yapılmadı (istemedikçe commit atmıyorum).

## 9. İnceleme notları
_(Senin geri bildirimin buraya eklenecek.)_

## 10. Sonraki milestone'a etkisi
M1'de ayar yazma (`Set-MpPreference`) ve yedek/geri alma ile CLI komutları (`auxy set`, `auxy revert`) yapılacak. Yönetici yetkisi gereksinimi ve Tamper engeli test edilecek.
