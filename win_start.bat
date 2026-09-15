@echo off
setlocal
cd /d "%~dp0"

echo =========================================
echo    MAX Gemini WebP Bot - Launcher
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
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [+] Virtual environment created.
)

echo [+] Activating .venv...
call .venv\Scripts\activate.bat

echo [+] Checking dependencies...
python -m pip install -r requirements.txt --quiet

echo [+] Checking Playwright Chromium...
python -m playwright install chromium

if not exist ".env" (
    if exist ".env.example" (
        echo [!] Creating .env from .env.example...
        copy .env.example .env >nul
        echo [!] Please configure your GEMINI_API_KEY in .env file!
    )
)

echo =========================================
echo         Starting MAX Gemini Bot...
echo =========================================
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Bot process exited with code %errorlevel%.
    pause
)
