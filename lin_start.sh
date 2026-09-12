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
echo "[+] Проверка браузера Chromium..."

# Сбрасываем PLAYWRIGHT_DOWNLOAD_HOST, так как на Azure нет сборок Chrome for Testing (код 400)
unset PLAYWRIGHT_DOWNLOAD_HOST

# 1. Проверяем наличие системного Chromium или устанавливаем его через apt
if ! command -v chromium &>/dev/null && ! command -v chromium-browser &>/dev/null; then
    echo "[+] Системный Chromium не найден. Устанавливаю через пакетный менеджер..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && (apt-get install -y chromium-browser || apt-get install -y chromium) || true
    elif command -v dnf &>/dev/null; then
        dnf install -y chromium || true
    elif command -v yum &>/dev/null; then
        yum install -y chromium || true
    fi
fi

# 2. Проверяем результат установки
if command -v chromium &>/dev/null || command -v chromium-browser &>/dev/null; then
    echo "[+] Успешно подключен системный Chromium: $(command -v chromium || command -v chromium-browser)"
else
    echo "[+] Попытка установки через стандартный Playwright..."
    python -m playwright install chromium || true
fi

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
