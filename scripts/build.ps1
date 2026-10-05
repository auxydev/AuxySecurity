# AuxySecurity derleme: uygulama klasoru (onedir) + payload.zip. (Kurulum programi: scripts\build_installer.ps1)
# Kullanim: .\scripts\build.ps1            (proje kokunden)
# Cikti   : %TEMP%\auxy-build\dist\AuxySecurity\  ve  %TEMP%\auxy-build\payload.zip  (OneDrive disinda: yuzlerce MB eslesmesin)
#           Degistirmek icin AUXY_BUILD_DIR ortam degiskeni.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

& $py packaging\make_assets.py
$out = if ($env:AUXY_BUILD_DIR) { $env:AUXY_BUILD_DIR } else { Join-Path $env:TEMP "auxy-build" }
New-Item -ItemType Directory -Force $out | Out-Null
$dist = Join-Path $out "dist"
$work = Join-Path $out "work"
$ErrorActionPreference = "Continue"   # PS 5.1: PyInstaller'in stderr INFO satirlari hata sayilmasin
& $py -m PyInstaller packaging\auxysecurity.spec --noconfirm --distpath $dist --workpath $work --log-level WARN 2>&1 | ForEach-Object { "$_" }
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller basarisiz" }

$app = Join-Path $dist "AuxySecurity"
foreach ($exe in "AuxySecurity.exe", "auxy.exe") {
    if (-not (Test-Path (Join-Path $app $exe))) { throw "$exe uretilemedi" }
}
# GoodbyeDPI'i uygulamayla paketle (Apache-2.0; WinDivert LGPL: lisanslar birlikte kopyalanir). Kaynak sirasi:
# AUXY_GOODBYEDPI_DIR  ->  makinedeki GoodbyeDPI hizmetinin klasoru. Bulunamazsa paketlenmez (kurucu 'atlandi' der).
# Ikili dosyalar depoya EKLENMEZ (.gitignore: derleme cikti klasoru depo disindadir).
$gsrc = $env:AUXY_GOODBYEDPI_DIR
if (-not $gsrc) {
    $svc = Get-CimInstance Win32_Service -Filter "Name='GoodbyeDPI'" -ErrorAction SilentlyContinue
    if ($svc -and $svc.PathName -match '^"?([^"]+?\\goodbyedpi\.exe)') {
        $cand = Split-Path (Split-Path $Matches[1])   # ...\x86_64\goodbyedpi.exe -> ...\<paket>
        if (Test-Path (Join-Path $cand "x86_64\goodbyedpi.exe")) { $gsrc = $cand }
    }
}
if ($gsrc -and (Test-Path (Join-Path $gsrc "x86_64\goodbyedpi.exe"))) {
    $gdst = Join-Path $app "tools\goodbyedpi"
    New-Item -ItemType Directory -Force $gdst | Out-Null
    foreach ($sub in "x86_64", "x86", "licenses") {
        if (Test-Path (Join-Path $gsrc $sub)) { Copy-Item (Join-Path $gsrc $sub) $gdst -Recurse -Force }
    }
    "GoodbyeDPI paketlendi: $gsrc"
} else {
    Write-Warning "GoodbyeDPI bulunamadi (AUXY_GOODBYEDPI_DIR ayarla); kurulumda hizmet kaydedilmeyecek."
}

$zip = Join-Path $out "payload.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $app "*") -DestinationPath $zip -CompressionLevel Optimal
$mb = [math]::Round((Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
$zmb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
"Uygulama klasoru: $app ($mb MB)"
"payload.zip     : $zip ($zmb MB)"
