import asyncio
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import config

def clean_stale_locks():
    """Удаляет устаревший SingletonLock, если процесс Chromium не запущен."""
    lock_file = config.USER_DATA_DIR / "SingletonLock"
    if lock_file.exists() or lock_file.is_symlink():
        try:
            target = os.readlink(lock_file) if lock_file.is_symlink() else ""
            pid = int(target.split("-")[-1]) if "-" in target else None
            if pid:
                os.kill(pid, 0)
                print(f"[!] Внимание: процесс Chromium с PID {pid} активен.")
        except (ProcessLookupError, ValueError):
            print("[+] Очистка устаревшего SingletonLock...")
            for name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                p = config.USER_DATA_DIR / name
                if p.exists() or p.is_symlink():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        except Exception:
            pass

async def take_screenshot():
    clean_stale_locks()
    output_file = config.OUTPUT_DIR / "screen.png"
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[+] Запуск Chromium для проверки экрана...")
    launch_kwargs = {}
    exe = config.get_chromium_executable()
    if exe:
        launch_kwargs["executable_path"] = exe

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(config.USER_DATA_DIR),
                headless=True,
                viewport={"width": 1280, "height": 850},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
                **launch_kwargs,
            )
        except Exception as e:
            print(f"[ОШИБКА] Не удалось запустить Chromium: {e}")
            if "SingletonLock" in str(e):
                print("[Подсказка] Профиль заблокирован другим процессом. Остановите бота перед запуском screenshot.py.")
            return

        try:
            page = context.pages[0] if context.pages else await context.new_page()
            print("[+] Открытие https://web.max.ru...")
            await page.goto("https://web.max.ru", wait_until="domcontentloaded", timeout=45000)
            
            # Ждем появления контента или стабилизации
            print("[+] Ожидание отрисовки страницы...")
            for _ in range(15):
                await asyncio.sleep(1)
                text = await page.evaluate("() => document.body.innerText || ''")
                if "Чаты" in text or "Избранное" in text or "Войти" in text:
                    break

            await page.screenshot(path=str(output_file), full_page=False)
            print(f"\n[УСПЕХ] Скриншот успешно сохранен в: {output_file}")
            print(f"Размер файла: {output_file.stat().st_size / 1024:.1f} Кб")

            # Проверка статуса авторизации
            text = await page.evaluate("() => document.body.innerText || ''")
            if "Чаты" in text or "Избранное" in text:
                print("[СТАТУС] Пользователь АВТОРИЗОВАН в MAX! (чаты загружены)")
            elif "Войти" in text or "телефон" in text.lower():
                print("[СТАТУС] Внимание: требуется вход (открыто окно авторизации).")
            else:
                print("[СТАТУС] Страница в процессе загрузки или неизвестное состояние.")

        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(take_screenshot())
