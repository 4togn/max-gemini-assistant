#!/usr/bin/env bash
cd "$(dirname "$0")"

echo "========================================="
echo "   MAX Gemini WebP Bot - Статус          "
echo "========================================="

if systemctl is-active --quiet max-gemini.service 2>/dev/null; then
    echo "[+] Статус службы systemd (max-gemini):"
    systemctl status max-gemini.service --no-pager
else
    echo "[-] Служба systemd не активна."
    PID=$(pgrep -f "[p]ython main.py" || true)
    if [ -n "$PID" ]; then
        echo "[i] Запущен локальный процесс (PID: $PID)"
    else
        echo "[i] Бот не запущен."
    fi
fi
