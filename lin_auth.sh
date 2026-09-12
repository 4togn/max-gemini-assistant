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
    python -m playwright install chromium
else
    source .venv/bin/activate
fi

python auth.py
