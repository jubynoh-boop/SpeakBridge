@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SpeakBridge

:menu
if exist ".git" goto :menu_developer

:menu_user
cls
echo ==================================================
echo                   SPEAKBRIDGE
echo ==================================================
echo.
echo   1. Cai dat SpeakBridge lan dau
echo   2. Cai dat VB-CABLE
echo   3. Khoi dong SpeakBridge
echo   4. Dung SpeakBridge
echo   5. Tai/chuan bi lai model
echo   0. Thoat
echo.
choice /c 123450 /n /m "Chon mot muc: "

if errorlevel 6 goto :exit
if errorlevel 5 goto :prepare_models
if errorlevel 4 goto :stop
if errorlevel 3 goto :start
if errorlevel 2 goto :install_cable
if errorlevel 1 goto :install
goto :menu

:menu_developer
cls
echo ==================================================
echo             SPEAKBRIDGE - SOURCE REPO
echo ==================================================
echo.
echo   1. Cai dat SpeakBridge lan dau
echo   2. Cai dat VB-CABLE
echo   3. Khoi dong SpeakBridge
echo   4. Dung SpeakBridge
echo   5. Tai/chuan bi lai model
echo.
echo   6. Build hotkey helper       [Nha phat trien]
echo   7. Build release             [Nha phat trien]
echo   0. Thoat
echo.
choice /c 12345670 /n /m "Chon mot muc: "

if errorlevel 8 goto :exit
if errorlevel 7 goto :build_release
if errorlevel 6 goto :build_hotkey
if errorlevel 5 goto :prepare_models
if errorlevel 4 goto :stop
if errorlevel 3 goto :start
if errorlevel 2 goto :install_cable
if errorlevel 1 goto :install
goto :menu

:install
call :header "CAI DAT SPEAKBRIDGE"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 goto :failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare-models.ps1"
if errorlevel 1 goto :failed
echo.
echo Cai dat SpeakBridge hoan tat.
echo Neu chua co VB-CABLE, chon muc 2 trong menu chinh.
goto :done

:install_cable
call :header "CAI DAT VB-CABLE"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-vb-cable.ps1"
if errorlevel 1 goto :failed
goto :done

:start
call :header "KHOI DONG SPEAKBRIDGE"
if not exist ".venv\Scripts\python.exe" (
  echo SpeakBridge chua duoc cai dat. Hay chon muc 1 truoc.
  goto :done
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 goto :failed
goto :done

:stop
call :header "DUNG SPEAKBRIDGE"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
if errorlevel 1 goto :failed
timeout /t 2 /nobreak >nul
goto :done

:prepare_models
call :header "CHUAN BI MODEL"
if not exist ".venv\Scripts\python.exe" (
  echo SpeakBridge chua duoc cai dat. Hay chon muc 1 truoc.
  goto :done
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare-models.ps1"
if errorlevel 1 goto :failed
goto :done

:build_hotkey
call :header "BUILD HOTKEY HELPER"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\build-hotkey.ps1"
if errorlevel 1 goto :failed
goto :done

:build_release
call :header "BUILD RELEASE"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-release.ps1"
if errorlevel 1 goto :failed
goto :done

:failed
echo.
echo Tac vu that bai. Xem thong bao loi o tren.

:done
echo.
pause
goto :menu

:header
cls
echo ==================================================
echo  %~1
echo ==================================================
echo.
exit /b 0

:exit
endlocal
exit /b 0
