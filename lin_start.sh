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
export PYTHONUNBUFFERED=1

# Проверка, не запущен ли уже бот
EXISTING_PID=$(pgrep -f "[m]ain\.py" || true)
if [ -n "$EXISTING_PID" ]; then
    echo "[!] ВНИМАНИЕ: Бот уже работает в системе (PID: $EXISTING_PID)!"
    echo "[!] Чтобы остановить или перезапустить, используйте: ./lin_stop.sh"
    exit 1
fi

# Очистка устаревших блокировок Chromium при мертвом процессе
if [ -d "user_data" ]; then
    rm -f user_data/SingletonLock user_data/SingletonCookie user_data/SingletonSocket 2>/dev/null || true
fi

# Проверка и установка зависимостей (быстрый запуск, если уже ставилось)
if [ ! -f ".venv/.deps_installed" ]; then
    echo "[+] Первая настройка: проверка и установка зависимостей из requirements.txt..."
    pip install -r requirements.txt --quiet
    
    echo "[+] Загрузка автономного Chromium для Playwright..."
    python -m playwright install chromium
    
    if [ "$(uname)" == "Linux" ]; then
        echo "[+] Проверка системных библиотек Chromium..."
        python -m playwright install-deps chromium 2>/dev/null || true
    fi
    touch .venv/.deps_installed
fi

# Дополнительная проверка: если автономный Chromium еще не загружен
PLAYWRIGHT_CHROME=$(find "$HOME/.cache/ms-playwright" -name "chrome" -type f 2>/dev/null | head -n 1 || true)
if [ -z "$PLAYWRIGHT_CHROME" ]; then
    echo "[+] Загрузка автономного Chromium для Playwright..."
    python -m playwright install chromium
fi

if [ -n "$PLAYWRIGHT_CHROME" ]; then
    echo "[+] Автономный Chromium (Playwright) готов к работе: $PLAYWRIGHT_CHROME"
elif command -v chromium &>/dev/null || command -v chromium-browser &>/dev/null || [ -f "/snap/bin/chromium" ]; then
    echo "[+] Системный Chromium готов к работе."
fi

# Проверка .env файла
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "[!] Файл .env не найден. Создаю из .env.example..."
        cp .env.example .env
        echo "[!] ВНИМАНИЕ: Пожалуйста, откройте .env и укажите ваш GEMINI_API_KEY!"
    fi
fi

FOREGROUND=0
for arg in "$@"; do
    if [ "$arg" == "-f" ] || [ "$arg" == "--foreground" ]; then
        FOREGROUND=1
    fi
done

if [ "$FOREGROUND" -eq 0 ] && command -v systemctl &>/dev/null && [ -f "/etc/systemd/system/max-gemini.service" ]; then
    echo "[+] Запуск службы max-gemini.service в фоновом режиме (systemd)..."
    systemctl restart max-gemini.service
    sleep 2
    if systemctl is-active --quiet max-gemini.service; then
        echo "============================================================"
        echo " [OK] Бот успешно запущен в фоновом режиме (24/7 daemon)!"
        echo "============================================================"
        echo " [i] Бот защищен от закрытия SSH и перезагрузок сервера."
        echo " [i] Смотреть живые логи: journalctl -u max-gemini -f"
        echo " [i] Проверить статус:    systemctl status max-gemini"
        echo " [i] Остановить бота:     ./lin_stop.sh"
        echo " [i] Для отладки в окне:  ./lin_start.sh -f"
        echo "============================================================"
        exit 0
    else
        echo "[!] Предупреждение: служба systemd не запустилась, переключаюсь на прямой запуск..."
    fi
fi

# Запуск бота
echo "========================================="
echo "        Запуск основного процесса...     "
echo "========================================="
exec python main.py
