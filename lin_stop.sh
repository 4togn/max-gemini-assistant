#!/usr/bin/env bash
cd "$(dirname "$0")"

echo "========================================="
echo "   MAX Gemini WebP Bot - Остановка       "
echo "========================================="

if systemctl is-active --quiet max-gemini.service 2>/dev/null; then
    echo "[+] Остановка системной службы max-gemini.service..."
    systemctl stop max-gemini.service
fi

BOT_PID=$(pgrep -f "[p]ython main.py" || true)

if [ -n "$BOT_PID" ]; then
    echo "[+] Завершение процесса бота (PID: $BOT_PID)..."
    kill $BOT_PID 2>/dev/null || true
    sleep 2
    if pgrep -f "[p]ython main.py" > /dev/null; then
        echo "[!] Принудительная остановка (kill -9)..."
        pkill -9 -f "[p]ython main.py" 2>/dev/null || true
    fi
    echo "[OK] Бот успешно остановлен."
else
    echo "[i] Процессы бота остановлены."
fi

# Очистка блокировок браузера
if [ -d "user_data" ]; then
    rm -f user_data/SingletonLock user_data/SingletonCookie user_data/SingletonSocket 2>/dev/null || true
    echo "[+] Файлы блокировки Chromium очищены."
fi

echo "========================================="
