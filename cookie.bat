@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Facebook Cookie Import

echo ============================================================
echo   CAP NHAT COOKIE FACEBOOK - khi phien het han dang nhap
echo ============================================================
echo.
echo  Cac buoc:
echo   1. Mo Edge - dang dang nhap Facebook - vao https://www.facebook.com
echo   2. Bam icon Cookie-Editor - bam nut Export - chon "Export as JSON"
echo      Noi dung JSON se duoc COPY vao clipboard.
echo   3. Quay lai cua so nay va nhan phim bat ky.
echo.
echo  LUU Y BAO MAT: cookie la thong tin dang nhap. KHONG chia se cho ai.
echo.

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [LOI] Khong tim thay moi truong ao: %VENV_PY%
  pause
  exit /b 1
)

set "PASTE=%~dp0cookie_paste.json"

pause

echo Dang doc cookie tu clipboard...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-Clipboard -Raw; if ([string]::IsNullOrWhiteSpace($c)) { exit 2 }; [IO.File]::WriteAllText('%PASTE%', $c, (New-Object System.Text.UTF8Encoding($false)))"
if errorlevel 2 goto manual
if errorlevel 1 goto manual

"%VENV_PY%" "%~dp0scripts\cookie_to_state.py" "%PASTE%" "%~dp0data\session\facebook_state.json"
if errorlevel 1 goto fail
goto done

:manual
echo.
echo [Clipboard khong co JSON] Se mo Notepad de dan cookie thu cong.
echo   Dan Ctrl+V noi dung JSON, luu Ctrl+S, roi dong Notepad.
echo.
if not exist "%PASTE%" type nul > "%PASTE%"
start /wait notepad "%PASTE%"
if not exist "%PASTE%" goto fail
"%VENV_PY%" "%~dp0scripts\cookie_to_state.py" "%PASTE%" "%~dp0data\session\facebook_state.json"
if errorlevel 1 goto fail
goto done

:fail
echo.
echo [LOI] Chuyen doi cookie that bai. Hay chac chan noi dung da dan la JSON.
echo File tam giu lai de kiem tra: cookie_paste.json
pause
exit /b 1

:done
del "%PASTE%" >nul 2>&1
echo.
echo [OK] Da cap nhat phien dang nhap: data\session\facebook_state.json
echo Bay gio co the chay: run.bat
echo.
pause
exit /b 0
