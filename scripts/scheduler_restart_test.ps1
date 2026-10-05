# Gorev Zamanlayici "hata durumunda yeniden baslat" GERCEK dogrulamasi (YONETICI GEREKMEZ, gecici gorev, sonunda silinir).
# Gorev: her calistiginda log dosyasina bir satir yazar ve hata kodu 1 ile cikar. RestartOnFailure: 1 dk aralik, 2 deneme
# => toplam 3 calisma (1 ilk + 2 yeniden baslatma) beklenir.
param([string]$Work = "$env:TEMP\auxy-restart-test", [int]$WaitSeconds = 170)

$name = "AuxyRestartTest"
New-Item -ItemType Directory -Force $Work | Out-Null
$log = Join-Path $Work "calisma.log"
Remove-Item $log -ErrorAction SilentlyContinue
$user = "$env:USERDOMAIN\$env:USERNAME"
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Principals><Principal id="Author"><UserId>$user</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>2</Count></RestartOnFailure>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>cmd.exe</Command><Arguments>/c echo %time% &gt;&gt; "$log" &amp; exit /b 1</Arguments></Exec></Actions>
</Task>
"@
$xmlPath = Join-Path $Work "task.xml"
$xml | Out-File -Encoding Unicode $xmlPath
schtasks /Create /TN $name /XML $xmlPath /F | Out-Null
$start = Get-Date
schtasks /Run /TN $name | Out-Null
Start-Sleep -Seconds $WaitSeconds
$lines = @(Get-Content $log -ErrorAction SilentlyContinue)
schtasks /End /TN $name 2>$null | Out-Null
schtasks /Delete /TN $name /F | Out-Null
"calisma sayisi: $($lines.Count) (beklenen 3: ilk + 2 yeniden baslatma)"
"zamanlar: $($lines -join ' | ')"
"gecen sure: $([int]((Get-Date) - $start).TotalSeconds) sn"
"gorev silindi mi: $(-not (schtasks /Query /TN $name 2>$null))"
