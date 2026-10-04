# Mimari (taslak – M0)

Ayrıntılı tasarım için [PLAN.md](../PLAN.md) bölüm 2.

```
auxy-agent (tray, olay tabanlı)  ──►  auxy-gui (istek üzerine açılır)
            └──────────── ikisi de ───────────►  auxy.core
```

## Şu an var olanlar (M0)
- `auxy.core.defender` – WMI ile durum/ayar okuma (`read_status`)
- `auxy.core.system` – yönetici kontrolü (`is_admin`)
- `auxy.__main__` – CLI (`auxy status`)

## İlkeler
- Core, UI'dan bağımsızdır; test edilebilir (WMI mock'lanır).
- Ağır importlar (win32com, GUI) geç yapılır.
- Sistem ayarını değiştiren her işlem önce eski değeri kaydeder (M1).
