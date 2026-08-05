@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.11 is required.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

if not exist "config.yaml" (
  python pair.py
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

python connector.py
pause
