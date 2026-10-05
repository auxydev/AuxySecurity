# AuxySecurity kurulum programi: tek dosya AuxySecurity-Setup.exe (payload.zip gomulu, yonetici yetkisi ister).
# Once .\scripts\build.ps1 calistirilmis olmali. Cikti: %TEMP%\auxy-build\AuxySecurity-Setup.exe
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$out = if ($env:AUXY_BUILD_DIR) { $env:AUXY_BUILD_DIR } else { Join-Path $env:TEMP "auxy-build" }
$zip = Join-Path $out "payload.zip"
if (-not (Test-Path $zip)) { throw "payload.zip yok: once scripts\build.ps1 calistirin" }

$work = Join-Path $out "setup-work"
$ErrorActionPreference = "Continue"
& $py -m PyInstaller packaging\setup_entry.py --noconfirm --onefile --windowed --uac-admin `
    --name AuxySecurity-Setup --icon (Join-Path $root "packaging\auxy.ico") `
    --version-file (Join-Path $root "packaging\version_info.txt") `
    --paths (Join-Path $root "src") --add-data "${zip};." --collect-submodules auxy `
    --hidden-import win32com.client --hidden-import win32com.shell --hidden-import pythoncom --hidden-import pywintypes `
    --exclude-module pytest --exclude-module numpy --exclude-module matplotlib `
    --distpath $out --workpath $work --specpath $work --log-level WARN 2>&1 | ForEach-Object { "$_" }
$ErrorActionPreference = "Stop"
$exe = Join-Path $out "AuxySecurity-Setup.exe"
if (-not (Test-Path $exe)) { throw "AuxySecurity-Setup.exe uretilemedi" }
"Kurulum programi: $exe ($([math]::Round((Get-Item $exe).Length / 1MB, 1)) MB)"
