@echo off
cd /d "%~dp0"
echo ======================================================
echo    MAX Gemini - Отправка templates и output в GitHub
echo ======================================================
git push origin main
if %errorlevel% equ 0 (
    echo.
    echo [OK] Все файлы и папки успешно загружены в GitHub!
) else (
    echo.
    echo [ERROR] Не удалось отправить. Проверьте авторизацию в GitHub.
)
echo.
pause
