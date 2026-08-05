@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "VENV_DIR=%CD%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PYTHONW_EXE=%VENV_DIR%\Scripts\pythonw.exe"
set "STAMP_FILE=%VENV_DIR%\.openakita-deps-installed"

echo [OpenAkita] 正在准备微信连接器 GUI...

if not exist "%PYTHON_EXE%" (
    echo [OpenAkita] 首次运行，正在创建 Python 3.11 虚拟环境...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.11 -m venv "%VENV_DIR%"
    ) else (
        where python >nul 2>nul
        if errorlevel 1 goto :python_missing
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
        if errorlevel 1 goto :python_missing
        python -m venv "%VENV_DIR%"
    )

    if errorlevel 1 goto :venv_failed
)

if not exist "%STAMP_FILE%" (
    echo [OpenAkita] 正在安装所需依赖，首次运行可能需要几分钟...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    if errorlevel 1 goto :dependency_failed

    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 goto :dependency_failed

    >"%STAMP_FILE%" echo installed
)

echo [OpenAkita] 正在启动 GUI...
if exist "%PYTHONW_EXE%" (
    start "" "%PYTHONW_EXE%" "%CD%\main.py"
) else (
    start "" "%PYTHON_EXE%" "%CD%\main.py"
)

if errorlevel 1 goto :launch_failed
exit /b 0

:python_missing
echo.
echo [错误] 未检测到 Python 3.11。
echo 请先安装 Python 3.11，并在安装时勾选 Add Python to PATH，然后重新双击本文件。
pause
exit /b 1

:venv_failed
echo.
echo [错误] 创建 Python 虚拟环境失败。
pause
exit /b 1

:dependency_failed
echo.
echo [错误] 安装依赖失败。请检查网络连接后重试。
pause
exit /b 1

:launch_failed
echo.
echo [错误] GUI 启动失败。
pause
exit /b 1
