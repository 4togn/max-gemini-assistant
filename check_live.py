import asyncio
import sys
import json
from pathlib import Path
from playwright.async_api import async_playwright
sys.path.insert(0, "/root/MAX_GEMINI")
import config

async def check_live_chat():
    clean_locks = config.USER_DATA_DIR / "SingletonLock"
    if clean_locks.exists() or clean_locks.is_symlink():
        try:
            clean_locks.unlink()
        except Exception:
            pass

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(config.USER_DATA_DIR),
            headless=True,
            viewport={"width": 1280, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
            executable_path=config.get_chromium_executable()
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://web.max.ru", wait_until="domcontentloaded", timeout=45000)

        for _ in range(20):
            has_chats = await page.evaluate("() => (document.body.innerText || '').includes('Избранное')")
            if has_chats:
                break
            await asyncio.sleep(1)

        chat = page.locator("text=/Избранное/").first
        await chat.click(no_wait_after=True)
        await asyncio.sleep(3)

        # Screenshot
        await page.screenshot(path="/root/MAX_GEMINI/output/live_chat.png")

        # Read last 8 messages
        info = await page.evaluate("""() => {
            const history = document.querySelector('[class*="history"]') || document.querySelector('main') || document.body;
            const items = Array.from(history.querySelectorAll('[data-index]'));
            return items.slice(-8).map(it => {
                return {
                    idx: it.getAttribute('data-index'),
                    text: (it.innerText || '').replace(/\\n/g, ' ')
                };
            });
        }""")

        print("Last messages in chat:")
        for m in info:
            print(f"[{m['idx']}]: {m['text']}")

        await context.close()

if __name__ == "__main__":
    asyncio.run(check_live_chat())
