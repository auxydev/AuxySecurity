# ADR-0001 – Defender erişimi: WMI birincil, PowerShell yedek

**Durum:** Kabul (M0, 2026-10-04)

## Bağlam
Defender durumu/ayarları iki yolla okunabilir: `Get-MpComputerStatus` (PowerShell) veya doğrudan
`root\Microsoft\Windows\Defender` WMI sınıfları. Uygulama başlangıçta çalışacak ve yük oluşturmamalı.

## Ölçüm (bu makine, Windows 11, Python 3.12)
| Yöntem | Süre | Not |
|---|---|---|
| PowerShell (yeni süreç, status+pref) | ~600 ms | Her çağrıda ayrı süreç + ~40 MB geçici RAM |
| WMI pywin32 (ilk çağrı) | ~170 ms | |
| WMI pywin32 (sonraki) | ~100 ms | Süreç RSS 29 → 36 MB |

Okuma için **yönetici yetkisi gerekmiyor** (WMI okuma standart kullanıcıyla çalıştı).

## Karar
- Okuma: WMI (pywin32). `win32com` **geç import** edilir.
- Yazma ve WMI'de karşılığı olmayan işlemler (tarama, imza güncelleme): M1'de `Set-MpPreference`
  / `Start-MpScan` PowerShell çağrısı ya da WMI yöntemi ile; parametreler **asla** string birleştirilerek
  komuta gömülmez.

## Sonuçlar
+ Düşük gecikme ve bellek. − pywin32 bağımlılığı (~30 MB disk).
