@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Khong tim thay .venv. Hay tao moi truong truoc.
  pause
  exit /b 1
)
start "" cmd /c "ping -n 6 127.0.0.1 >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" server.py
pause