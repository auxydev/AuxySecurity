# Kod imzalama: derlenen exe'leri ve kurulum programini Authenticode ile imzalar (SmartScreen/Defender itibari icin).
# GERCEK bir kod imzalama sertifikasi (PFX) gerekir; depoda sertifika YOKTUR ve bu betik bu makinede denenmedi.
# Kullanim:
#   $env:AUXY_PFX = "C:\yol\sertifika.pfx"; $env:AUXY_PFX_PASSWORD = "..."   # parola komut satirina YAZILMAZ
#   .\scripts\sign.ps1                       # %TEMP%\auxy-build altindaki exe'leri imzalar
# Gerekli: Windows SDK signtool.exe (PATH'te ya da AUXY_SIGNTOOL ile yol).
# Sira: build.ps1 -> sign.ps1 (uygulama exe'leri) -> payload'u yeniden olustur -> build_installer.ps1 -> sign.ps1 (kurulum exe'si)
$ErrorActionPreference = "Stop"
if (-not $env:AUXY_PFX -or -not (Test-Path $env:AUXY_PFX)) { throw "AUXY_PFX (PFX dosyasi yolu) ayarli degil" }
if (-not $env:AUXY_PFX_PASSWORD) { throw "AUXY_PFX_PASSWORD ayarli degil" }
$signtool = if ($env:AUXY_SIGNTOOL) { $env:AUXY_SIGNTOOL } else { (Get-Command signtool.exe -ErrorAction Stop).Source }
$out = if ($env:AUXY_BUILD_DIR) { $env:AUXY_BUILD_DIR } else { Join-Path $env:TEMP "auxy-build" }
$ts = if ($env:AUXY_TIMESTAMP_URL) { $env:AUXY_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }

$targets = @(
    Join-Path $out "dist\AuxySecurity\AuxySecurity.exe"
    Join-Path $out "dist\AuxySecurity\auxy.exe"
    Join-Path $out "AuxySecurity-Setup.exe"
) | Where-Object { Test-Path $_ }
if (-not $targets) { throw "imzalanacak exe bulunamadi: once build.ps1 / build_installer.ps1" }

foreach ($t in $targets) {
    & $signtool sign /fd SHA256 /f $env:AUXY_PFX /p $env:AUXY_PFX_PASSWORD /tr $ts /td SHA256 /d "AuxySecurity" $t
    if ($LASTEXITCODE -ne 0) { throw "imzalama basarisiz: $t" }
    & $signtool verify /pa $t
    if ($LASTEXITCODE -ne 0) { throw "dogrulama basarisiz: $t" }
    "imzalandi: $t"
}
