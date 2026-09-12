#!/usr/bin/env bash
set -e

# Переход в директорию скрипта
cd "$(dirname "$0")"

echo "========================================="
echo "   MAX Gemini WebP Bot - Запуск (Linux)   "
echo "========================================="

# Определение команды python
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[ОШИБКА] Python 3 не найден! Пожалуйста, установите Python 3."
    exit 1
fi

# Проверка и создание виртуального окружения (.venv)
if [ ! -d ".venv" ]; then
    echo "[+] Создание виртуального окружения (.venv)..."
    $PYTHON_CMD -m venv .venv
    echo "[+] Виртуальное окружение успешно создано."
fi

# Активация виртуального окружения
echo "[+] Активация виртуального окружения..."
source .venv/bin/activate

# Проверка и установка зависимостей
echo "[+] Проверка и установка зависимостей из requirements.txt..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# Проверка и установка браузера Chromium для Playwright
echo "[+] Проверка браузера Playwright Chromium..."
python -m playwright install chromium
if [ "$(uname)" == "Linux" ]; then
    echo "[+] Проверка системных библиотек для Chromium (Linux)..."
    python -m playwright install-deps chromium 2>/dev/null || true
fi

# Проверка .env файла
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "[!] Файл .env не найден. Создаю из .env.example..."
        cp .env.example .env
        echo "[!] ВНИМАНИЕ: Пожалуйста, откройте .env и укажите ваш GEMINI_API_KEY!"
    fi
fi

# Запуск бота
echo "========================================="
echo "        Запуск основного процесса...     "
echo "========================================="
exec python main.py
