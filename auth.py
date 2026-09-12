import asyncio
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright
import config

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

async def main():
    print("=" * 68)
    print("           АВТОРИЗАЦИЯ / ПОВТОРНЫЙ ВХОД В MAX (web.max.ru)")
    print("=" * 68)

    # Проверка наличия графического экрана при запуске на Linux
    if sys.platform.startswith("linux"):
        if "DISPLAY" not in os.environ and "WAYLAND_DISPLAY" not in os.environ:
            print("[ОШИБКА] На этом сервере отсутствует графический экран ($DISPLAY не задан)!")
            print("Авторизацию необходимо выполнять на ПК с экраном (Windows или Linux Desktop).")
            print("Запустите win_auth.bat на компьютере, а затем перенесите папку user_data на сервер.")
            sys.exit(1)

    print(f"[+] Профиль браузера: {config.USER_DATA_DIR}")
    print("[+] Запуск браузера с видимым окном...")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(config.USER_DATA_DIR),
            headless=False,
            viewport={"width": 1280, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://web.max.ru", wait_until="domcontentloaded")

        print("\n" + "=" * 68)
        print("ИНСТРУКЦИЯ:")
        print("1. В открывшемся окне браузера введите ваш номер телефона.")
        print("2. Введите код подтверждения из СМС.")
        print("3. Убедитесь, что чаты успешно загрузились.")
        print("=" * 68)

        # Ожидание ручного подтверждения в консоли без блокировки event loop
        await asyncio.to_thread(input, "\n>>> После успешного входа в MAX нажмите [ENTER] здесь для сохранения: ")

        print("\n[+] Проверка статуса входа...")
        is_in_app = False
        try:
            is_in_app = await page.evaluate("""() => {
                const text = document.body.innerText || '';
                return text.includes('Чаты') || text.includes('Избранное') || document.querySelector('.contenteditable') !== null;
            }""")
        except Exception:
            pass

        if is_in_app:
            print("[OK] Вход в аккаунт подтвержден!")
            # Пробуем открыть Избранное для фиксации сессии
            try:
                chat_loc = page.locator(f"text='{config.MAX_CHAT_NAME}'").first
                if await chat_loc.count() > 0:
                    await chat_loc.click()
                    await page.wait_for_timeout(1500)
            except Exception:
                pass
            print(f"[OK] Сессия успешно сохранена в: {config.USER_DATA_DIR}")
            print("[+] Теперь можно запускать бота (win_start.bat или lin_start.sh).")
        else:
            print("[!] Предупреждение: страница еще не показала чаты.")
            print("    Сессия сохранена в текущем состоянии.")

        print("[+] Закрываю браузер...")
        await context.close()
        print("=" * 68)
        print("Готово!")
        print("=" * 68)

if __name__ == "__main__":
    asyncio.run(main())
