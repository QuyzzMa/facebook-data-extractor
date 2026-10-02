@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Facebook Data Extractor

echo ============================================================
echo   FACEBOOK DATA EXTRACTOR
echo ============================================================
echo.
echo  LUU Y:
echo   - Tool dung phien dang nhap da luu: data\session\facebook_state.json
echo   - Neu ket qua bao "Parsed 0 records" hoac file xuat ra trong:
echo     ^> phien dang nhap da het han, hay chay cookie.bat de dan cookie moi.
echo.

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [LOI] Khong tim thay moi truong ao:
  echo     %VENV_PY%
  echo.
  echo Hay tao moi truong truoc:
  echo     py -3 -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo     .venv\Scripts\python.exe -m playwright install chromium
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0data\session\facebook_state.json" (
  echo [CANH BAO] Chua co file phien dang nhap:
  echo     data\session\facebook_state.json
  echo Neu bi loi dang nhap hoac 0 bai, hay chay cookie.bat truoc.
  echo.
)

echo Dang chay... cua so trinh duyet se tu mo. Vui long doi.
echo.
"%VENV_PY%" "%~dp0main.py"
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
if "%RC%"=="0" (
  echo   HOAN TAT. Xem ket qua trong thu muc: output\
) else (
  echo   KET THUC VOI LOI - ma %RC%. Xem log: logs\pipeline.log
)
echo.
echo   Nhac lai: ket qua "0 records" = phien da het han - chay cookie.bat.
echo ============================================================
echo.

if exist "%~dp0output" start "" "%~dp0output"
pause
exit /b %RC%
