@echo off
rem ============================================================================
rem  AuxySecurity - Hizli Kurulum (baslat.bat)
rem  Cift tikla: adim adim kurar. Yonetici izni (UAC) ister. Hicbir sey sormadan:  baslat.bat /auto
rem  Secenekler: /auto  /nogdpi  /nowarp  /nostart
rem  Test icin ortam degiskenleri: AUXY_SETUP (kurucu yolu), AUXY_INSTALLDIR, AUXY_BAT_TEST=1
rem ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title AuxySecurity Hızlı Kurulum
cd /d "%~dp0"

set "TOTAL=7"
set "AUTO=0"
set "NOGDPI=0"
set "NOWARP=0"
set "NOSTART=0"
for %%A in (%*) do (
  if /i "%%~A"=="/auto" set "AUTO=1"
  if /i "%%~A"=="/nogdpi" set "NOGDPI=1"
  if /i "%%~A"=="/nowarp" set "NOWARP=1"
  if /i "%%~A"=="/nostart" set "NOSTART=1"
)
set "SETUP=%~dp0AuxySecurity-Setup.exe"
if defined AUXY_SETUP set "SETUP=%AUXY_SETUP%"
set "APPDIR=%ProgramFiles%\AuxySecurity"
if defined AUXY_INSTALLDIR set "APPDIR=%AUXY_INSTALLDIR%"
set "TESTMODE=0"
if defined AUXY_BAT_TEST set "TESTMODE=1"

cls
echo.
echo   ╔══════════════════════════════════════════════════╗
echo   ║           AuxySecurity  -  Hızlı Kurulum         ║
echo   ╚══════════════════════════════════════════════════╝
echo.
echo   Bu sihirbaz AuxySecurity'yi adım adım kurar. Her adımda ne yapıldığı yazılır.
echo   İstediğin an pencereyi kapatarak vazgeçebilirsin ^(kurulum başlamadan hiçbir şey değişmez^).
echo.
if "%AUTO%"=="0" if "%TESTMODE%"=="0" pause

rem ---------------------------------------------------------------- 1. sistem
call :step 1 "Sistem denetleniyor"
if /i not "%PROCESSOR_ARCHITECTURE%"=="AMD64" if /i not "%PROCESSOR_ARCHITEW6432%"=="AMD64" (
  call :fail "Bu kurulum 64 bit Windows gerektirir."
  goto :end
)
for /f "delims=" %%V in ('powershell -NoProfile -Command "[Environment]::OSVersion.Version.Major" 2^>nul') do set "OSMAJOR=%%V"
if not defined OSMAJOR set "OSMAJOR=0"
if %OSMAJOR% LSS 10 (
  call :fail "Windows 10 ya da üzeri gerekir."
  goto :end
)
call :ok "64 bit Windows %OSMAJOR% bulundu"

rem ---------------------------------------------------------------- 2. yonetici izni
call :step 2 "Yönetici izni denetleniyor"
net session >nul 2>&1
if errorlevel 1 (
  if "%TESTMODE%"=="1" (
    call :info "Test kipi: yükseltme atlandı"
  ) else (
    call :info "Yönetici izni gerekiyor: Windows'un onay penceresi (UAC) açılacak, Evet de."
    if "%~1"=="" (
      powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
    ) else (
      powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs" >nul 2>&1
    )
    if errorlevel 1 (
      call :fail "Yönetici izni verilmedi. Kurulum iptal edildi."
      goto :end
    )
    exit /b 0
  )
) else (
  call :ok "Yönetici olarak çalışıyor"
)

rem ---------------------------------------------------------------- 3. dosya dogrulama
call :step 3 "Kurulum dosyası doğrulanıyor"
if not exist "%SETUP%" (
  call :fail "AuxySecurity-Setup.exe bulunamadı. Zip'i tamamen çıkardığından emin ol."
  goto :end
)
set "WANT="
if exist "%~dp0SHA256SUMS.txt" (
  for /f "tokens=1,2" %%H in ('findstr /i "AuxySecurity-Setup.exe" "%~dp0SHA256SUMS.txt"') do set "WANT=%%H"
)
set "GOT="
for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "%SETUP%" SHA256 2^>nul') do if not defined GOT set "GOT=%%H"
set "GOT=!GOT: =!"
if not defined WANT (
  call :info "SHA256SUMS.txt bulunamadı: bütünlük denetimi atlandı"
) else (
  if /i not "!GOT!"=="!WANT!" (
    call :fail "Dosya bozuk ya da değiştirilmiş (SHA-256 uyuşmuyor). Güvenli bir kaynaktan yeniden indir."
    goto :end
  )
  call :ok "SHA-256 doğrulandı"
)

rem ---------------------------------------------------------------- 4. secimler
call :step 4 "Kurulum seçenekleri"
set "FLAGS=/S"
call :ask "Windows açılışında otomatik başlasın mı" E AUTOSTART
if "!ANS!"=="E" set "FLAGS=!FLAGS! /AUTOSTART"
call :ask "Dosyalara sağ tık menüsüne 'Auxy ile tara' eklensin mi" E CTX
if "!ANS!"=="E" set "FLAGS=!FLAGS! /CONTEXTMENU"
call :ask "Masaüstüne kısayol konulsun mu" H DESK
if "!ANS!"=="E" set "FLAGS=!FLAGS! /DESKTOP"
if "%NOGDPI%"=="1" (
  set "FLAGS=!FLAGS! /NOGDPI"
) else (
  call :ask "GoodbyeDPI hizmeti kurulsun mu (uygulamayla birlikte gelir)" E GDPI
  if not "!ANS!"=="E" set "FLAGS=!FLAGS! /NOGDPI"
)
if "%NOWARP%"=="1" (
  set "FLAGS=!FLAGS! /NOWARP"
) else (
  call :ask "Cloudflare WARP yoksa internetten indirilip kurulsun mu (winget, ~70 MB)" E WARP
  if not "!ANS!"=="E" set "FLAGS=!FLAGS! /NOWARP"
)
call :ok "Seçenekler: !FLAGS!"

rem ---------------------------------------------------------------- 5. kurulum
call :step 5 "AuxySecurity kuruluyor (30-90 sn, WARP indirilecekse daha uzun)"
call :info "Dosyalar kopyalanıyor, kısayollar ve kayıtlar oluşturuluyor..."
call "%SETUP%" !FLAGS!
set "RC=!errorlevel!"
if not "!RC!"=="0" (
  call :fail "Kurulum programı hata verdi (çıkış kodu !RC!)."
  goto :end
)
call :ok "Kurulum programı tamamlandı"

rem ---------------------------------------------------------------- 6. dogrulama
call :step 6 "Kurulum denetleniyor"
if not exist "%APPDIR%\AuxySecurity.exe" (
  call :fail "%APPDIR% altında AuxySecurity.exe bulunamadı."
  goto :end
)
call :ok "Dosyalar %APPDIR% klasörüne kuruldu"
if "%TESTMODE%"=="0" (
  for /f "delims=" %%V in ('call "%APPDIR%\auxy.exe" --version 2^>nul') do call :ok "Sürüm %%V"
  for /f "delims=" %%S in ('call "%APPDIR%\auxy.exe" doctor 2^>nul ^| findstr /i "zet:"') do call :info "Tanı: %%S"
)

rem ---------------------------------------------------------------- 7. baslat
call :step 7 "Uygulama başlatılıyor"
if "%NOSTART%"=="1" (
  call :info "Başlatma atlandı"
) else if "%TESTMODE%"=="1" (
  call :info "Test kipi: başlatma atlandı"
) else (
  call :ask "AuxySecurity şimdi açılsın mı" E START
  if "!ANS!"=="E" (
    rem yukseltilmemis kullanici olarak ac ^(explorer araciligiyla^)
    start "" explorer.exe "%APPDIR%\AuxySecurity.exe"
    call :ok "AuxySecurity açıldı"
  )
)

echo.
echo   ══════════════════════════════════════════════════
echo     Kurulum tamamlandı. Başlat menüsünden "AuxySecurity" ile açabilirsin.
echo     Kaldırmak için: Ayarlar ^> Uygulamalar ^> AuxySecurity
echo   ══════════════════════════════════════════════════
echo.
set "EXITCODE=0"
goto :finish

:end
set "EXITCODE=1"
echo.
echo   Kurulum tamamlanamadı. Yukarıdaki hatayı düzeltip başlat.bat'ı yeniden çalıştır.
echo.

:finish
if "%AUTO%"=="0" if "%TESTMODE%"=="0" pause
endlocal & exit /b %EXITCODE%

rem ============================================================================
:step
echo.
echo   [%~1/%TOTAL%] %~2
goto :eof

:ok
echo        √ %~1
goto :eof

:info
echo        • %~1
goto :eof

:fail
echo        X HATA: %~1
goto :eof

:ask
rem  kullanim: call :ask "soru" varsayilan(E/H) ad   -> ANS=E/H ; /auto ve test kipinde varsayilan
set "ANS=%~2"
if "%AUTO%"=="1" goto :eof
if "%TESTMODE%"=="1" goto :eof
if /i "%~2"=="E" (set "HINT=[E]vet / [H]ayır - 60 sn sonra: Evet") else (set "HINT=[E]vet / [H]ayır - 60 sn sonra: Hayır")
choice /c EH /d %~2 /t 60 /n /m "        ? %~1 %HINT% : "
if errorlevel 2 (set "ANS=H") else (set "ANS=E")
goto :eof
