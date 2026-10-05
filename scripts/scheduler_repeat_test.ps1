# Gorev Zamanlayici "tekrarlanan tetikleyici + IgnoreNew" GERCEK dogrulamasi (YONETICI GEREKMEZ, gecici gorev, sonunda silinir).
# Beklenen davranis (ajan icin kullandigimiz mekanizma):
#   1) Eylem calisirken tekrar tetikleyici YENI ornek baslatmaz (IgnoreNew)  -> log'da 1 satir
#   2) Surec oldurulunce (cokme benzeri) bir sonraki tetikte YENI ornek baslar -> log'da 2 satir
param([string]$Work = "$env:TEMP\auxy-repeat-test", [int]$Phase1 = 80, [int]$Phase2 = 100)

$name = "AuxyRepeatTest"
New-Item -ItemType Directory -Force $Work | Out-Null
$log = Join-Path $Work "calisma.log"
Remove-Item $log -ErrorAction SilentlyContinue
$user = "$env:USERDOMAIN\$env:USERNAME"
$boundary = (Get-Date).AddSeconds(15).ToString("yyyy-MM-ddTHH:mm:ss")
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <StartBoundary>$boundary</StartBoundary>
      <Repetition><Interval>PT1M</Interval></Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>$user</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>cmd.exe</Command><Arguments>/c echo %time% &gt;&gt; "$log" &amp; ping -n 600 127.0.0.1 &gt; nul</Arguments></Exec></Actions>
</Task>
"@
$xmlPath = Join-Path $Work "task.xml"
$xml | Out-File -Encoding Unicode $xmlPath
schtasks /Create /TN $name /XML $xmlPath /F | Out-Null
$t0 = Get-Date

# Faz 1: ilk tetik (~15 sn) + en az 1 tekrar tetik gecsin; ornek calisirken yeni baslamamali
Start-Sleep -Seconds $Phase1
$afterPhase1 = @(Get-Content $log -ErrorAction SilentlyContinue).Count

# Cokme benzeri: eylemin surecini zorla oldur
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" | Where-Object { $_.CommandLine -like "*auxy-repeat-test*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process ping -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -gt $t0 } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds $Phase2
$afterKill = @(Get-Content $log -ErrorAction SilentlyContinue)

schtasks /End /TN $name 2>$null | Out-Null
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" | Where-Object { $_.CommandLine -like "*auxy-repeat-test*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process ping -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -gt $t0 } | Stop-Process -Force -ErrorAction SilentlyContinue
schtasks /Delete /TN $name /F | Out-Null

"FAZ 1 (calisirken, ~$Phase1 sn, tekrar tetik gecti): log satiri = $afterPhase1  (beklenen 1: IgnoreNew yeni ornek baslatmadi)"
"FAZ 2 (surec oldurulduktan ~$Phase2 sn sonra):       log satiri = $($afterKill.Count)  (beklenen >= 2: yeni ornek baslatildi)"
"zamanlar: $($afterKill -join ' | ')"
"gorev silindi mi: $(-not (schtasks /Query /TN $name 2>$null))"
