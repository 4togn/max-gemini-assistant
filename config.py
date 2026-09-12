import os
from pathlib import Path
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
