import os
import shutil
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные из .env файла
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

MAX_CHAT_NAME = os.getenv("MAX_CHAT_NAME", "Избранное").strip()
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() in ("true", "1", "yes")

CARD_THEME = os.getenv("CARD_THEME", "dark").strip().lower()
CARD_WIDTH = int(os.getenv("CARD_WIDTH", "760"))

USER_DATA_DIR = Path(os.getenv("USER_DATA_DIR", "./user_data")).resolve()
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"

# Создаем необходимые директории
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_chromium_executable() -> Optional[str]:
    """
    Возвращает путь к системному Chromium/Chrome, если он установлен на Linux,
    чтобы не зависеть от сетевых таймаутов storage.googleapis.com при скачивании через Playwright.
    """
    if os.name != "nt":  # Linux / macOS
        for candidate in [
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/snap/bin/chromium",
        ]:
            if os.path.exists(candidate):
                return candidate
        which_path = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
        if which_path:
            return which_path
    return None
