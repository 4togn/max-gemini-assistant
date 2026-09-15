@echo off
setlocal
cd /d "%~dp0"

echo =========================================
echo    MAX Gemini - Authorization / Re-Auth
echo =========================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH! Please install Python.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [+] Creating virtual environment .venv...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt --quiet
    python -m playwright install chromium
) else (
    call .venv\Scripts\activate.bat
)

python auth.py

pause
