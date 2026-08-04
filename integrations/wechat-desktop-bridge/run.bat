@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv || exit /b 1
)

call ".venv\Scripts\activate.bat" || exit /b 1
python -m pip install --disable-pip-version-check -r requirements.txt || exit /b 1

if not exist "config.yaml" (
  copy /Y "config.example.yaml" "config.yaml" >nul
  echo Created config.yaml. Edit groups and agent_id, then run this file again.
  pause
  exit /b 2
)

python main.py --config config.yaml
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
