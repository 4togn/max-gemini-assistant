#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "========================================="
echo "   MAX Gemini - Авторизация (Linux)      "
echo "========================================="

if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[ОШИБКА] Python 3 не найден!"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[+] Создание .venv..."
    $PYTHON_CMD -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt --quiet
    echo "[+] Загрузка автономного Chromium для Playwright..."
    python -m playwright install chromium
    python -m playwright install-deps chromium 2>/dev/null || true
else
    source .venv/bin/activate
fi

PLAYWRIGHT_CHROME=$(find "$HOME/.cache/ms-playwright" -name "chrome" -type f 2>/dev/null | head -n 1 || true)
if [ -z "$PLAYWRIGHT_CHROME" ]; then
    echo "[+] Загрузка автономного Chromium для Playwright..."
    python -m playwright install chromium
fi

python auth.py
