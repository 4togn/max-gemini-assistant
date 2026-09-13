#!/usr/bin/env bash
cd "$(dirname "$0")"

echo "========================================="
echo "   MAX Gemini WebP Bot - Логи            "
echo "   (Для выхода нажмите Ctrl+C)           "
echo "========================================="

if systemctl is-active --quiet max-gemini.service 2>/dev/null; then
    journalctl -u max-gemini -f
elif [ -f "nohup.out" ]; then
    tail -f nohup.out
else
    echo "[!] Логи не найдены."
fi
