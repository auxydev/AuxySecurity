# AuxySecurity: GitHub'daki en yeni surumu derleyip kurar; once eski kurulumu kaldirir. Ayarlar ve karantina kasasi korunur.
# Kullanim (YONETICI PowerShell):
#   irm https://raw.githubusercontent.com/auxydev/AuxySecurity/main/scripts/reinstall.ps1 | iex
# Gereksinim: git ve Python 3.12+ (py ya da python komutu). Kaynak: %USERPROFILE%\AuxySecurity-src
$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "Bu betigi YONETICI olarak acilmis PowerShell'de calistir." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git bulunamadi: https://git-scm.com adresinden kur." }

if (Get-Command py -ErrorAction SilentlyContinue) { $pyExe = "py"; $pyArgs = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyExe = "python"; $pyArgs = @() }
else { throw "Python 3.12+ bulunamadi: https://python.org adresinden kur." }
$ver = & $pyExe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]"3.12") { throw "Python $ver eski; 3.12+ gerekli." }

$src = Join-Path $env:USERPROFILE "AuxySecurity-src"
$installed = Join-Path $env:ProgramFiles "AuxySecurity\AuxySecurity.exe"

Step "Kaynak kod guncelleniyor ($src)"
if (Test-Path (Join-Path $src ".git")) {
    git -C $src fetch --quiet origin main
    git -C $src reset --quiet --hard origin/main
} else {
    if (Test-Path $src) { throw "$src var ama git deposu degil; adini degistir ya da sil." }
    git clone --quiet https://github.com/auxydev/AuxySecurity.git $src
}
Set-Location $src
"Surum: " + (git log -1 --format="%h %s")

Step "Python ortami ve derleme araclari"
$venvPy = Join-Path $src ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { & $pyExe @pyArgs -m venv (Join-Path $src ".venv") }
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -e ".[dev]" pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip kurulumu basarisiz" }

# Derleme ESKI surum kaldirilmadan once: build.ps1 GoodbyeDPI'i calisan hizmetin klasorunden paketler.
Step "Uygulama derleniyor (birkac dakika surebilir)"
# Alt betikler ayri surecte, yalnizca bu calistirma icin izinle (irm|iex ile gelindiginde ExecutionPolicy .ps1'i engeller;
# sistem ayari DEGISTIRILMEZ).
foreach ($b in "build.ps1", "build_installer.ps1") {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $src "scripts\$b")
    if ($LASTEXITCODE -ne 0) { throw "$b basarisiz (cikis kodu $LASTEXITCODE)" }
}
$setup = Join-Path $(if ($env:AUXY_BUILD_DIR) { $env:AUXY_BUILD_DIR } else { Join-Path $env:TEMP "auxy-build" }) "AuxySecurity-Setup.exe"
if (-not (Test-Path $setup)) { throw "Kurulum programi uretilemedi" }

Step "Eski surum kapatiliyor ve kaldiriliyor"
Get-Process AuxySecurity, auxy -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
if (Test-Path $installed) {
    $p = Start-Process $installed -ArgumentList "uninstall", "--quiet" -Wait -PassThru
    "Kaldirma cikis kodu: $($p.ExitCode)"
    for ($i = 0; $i -lt 30 -and (Test-Path $installed); $i++) { Start-Sleep 1 }  # dosyalar cikistan sonra silinir
} else {
    "Program Files'ta kurulu surum yok."
}
# Gelistirme (kaynaktan) kurulumunun baslangic gorevi kalmissa kaldir; kurulum programi yenisini olusturur.
$ErrorActionPreference = "Continue"   # PS 5.1: yerel komutun yonlendirilen stderr'i Stop altinda istisna olur
schtasks /Query /TN AuxySecurity *> $null
if ($LASTEXITCODE -eq 0) { schtasks /Delete /TN AuxySecurity /F *> $null; "Eski baslangic gorevi kaldirildi." }
$ErrorActionPreference = "Stop"

Step "Yeni surum kuruluyor"
$p = Start-Process $setup -ArgumentList "/S", "/AUTOSTART", "/CONTEXTMENU" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Kurulum basarisiz (cikis kodu $($p.ExitCode))" }

$auxy = Join-Path $env:ProgramFiles "AuxySecurity\auxy.exe"
Step "Kuruldu: $(& $auxy --version)"
"Tray ajani oturum acilisinda baslar; simdi baslatmak icin Baslat menusunden AuxySecurity'yi ac."
