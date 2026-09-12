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
    unset PLAYWRIGHT_DOWNLOAD_HOST
    if ! command -v chromium &>/dev/null && ! command -v chromium-browser &>/dev/null; then
        if command -v apt-get &>/dev/null; then
            apt-get update -qq && (apt-get install -y chromium-browser || apt-get install -y chromium) || true
        fi
    fi
    if ! command -v chromium &>/dev/null && ! command -v chromium-browser &>/dev/null; then
        python -m playwright install chromium || true
    fi
    python -m playwright install-deps chromium 2>/dev/null || true
else
    source .venv/bin/activate
fi

python auth.py
