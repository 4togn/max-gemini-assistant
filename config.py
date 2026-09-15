import os
import shutil
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные из .env файла (при отсутствии автоматически создаем из шаблона .env.example)
BASE_DIR = Path(__file__).resolve().parent
env_file = BASE_DIR / ".env"
env_example = BASE_DIR / ".env.example"

if not env_file.exists() and env_example.exists():
    try:
        shutil.copy(env_example, env_file)
    except Exception:
        pass

load_dotenv(env_file)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

def _clean_model_name(val: Optional[str]) -> Optional[str]:
    """
    Очищает название модели. Если значение пустое, none, off, false,
    возвращает None (модель не используется).
    """
    if not val:
        return None
    val = val.strip()
    if not val or val.lower() in ("none", "off", "false", "no", "disable", "disabled", "-"):
        return None
    return val


# Основная модель GEMINI_MODEL_1 (по умолчанию: gemini-2.5-flash)
_m1_raw = os.getenv("GEMINI_MODEL_1")
if _m1_raw is None:
    _m1_raw = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
PRIMARY_MODEL = _clean_model_name(_m1_raw) or "gemini-2.5-flash"
GEMINI_MODEL_1 = PRIMARY_MODEL

# Резервные модели (2, 3, 4 и т.д.): если переменная пустая в .env — она пропускается!
GEMINI_MODEL_2 = _clean_model_name(os.getenv("GEMINI_MODEL_2"))
GEMINI_MODEL_3 = _clean_model_name(os.getenv("GEMINI_MODEL_3"))
GEMINI_MODEL_4 = _clean_model_name(os.getenv("GEMINI_MODEL_4"))

# Формируем список только заданных резервных моделей
BACKUP_MODELS = []
for m in [GEMINI_MODEL_2, GEMINI_MODEL_3, GEMINI_MODEL_4]:
    if m and m not in BACKUP_MODELS and m != PRIMARY_MODEL:
        BACKUP_MODELS.append(m)

# Поддержка дополнительных резервных моделей (GEMINI_MODEL_5, GEMINI_MODEL_6 и т.д., если указаны)
_i = 5
while True:
    _extra_raw = os.getenv(f"GEMINI_MODEL_{_i}")
    if _extra_raw is None:
        break
    _extra = _clean_model_name(_extra_raw)
    if _extra and _extra not in BACKUP_MODELS and _extra != PRIMARY_MODEL:
        BACKUP_MODELS.append(_extra)
    _i += 1

# Полный список моделей (основная + резервные)
MODELS_CASCADE = ([PRIMARY_MODEL] if PRIMARY_MODEL else []) + BACKUP_MODELS

# Для обратной совместимости
GEMINI_MODEL = PRIMARY_MODEL or (BACKUP_MODELS[0] if BACKUP_MODELS else "")

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
    Возвращает путь к Chromium/Chrome на Linux.
    В первую очередь ищет автономный Chromium от Playwright (~/.cache/ms-playwright)
    или нативный системный deb-пакет Google Chrome/Chromium, так как Snap-пакеты
    привязаны к сессии SSH и аварийно завершаются systemd-logind при закрытии соединения.
    """
    if os.name != "nt":  # Linux / macOS
        # 1. Проверяем автономный бинарник Playwright (без привязки к Snap/systemd-сессии)
        home = Path.home()
        ms_cache = home / ".cache" / "ms-playwright"
        if ms_cache.exists():
            for p in sorted(ms_cache.glob("chromium-*/chrome-linux*/chrome"), reverse=True):
                if p.exists() and os.access(p, os.X_OK):
                    return str(p)

        # 2. Проверяем нативный deb-пакет Google Chrome
        for candidate in [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
        ]:
            if os.path.exists(candidate):
                return candidate

        # 3. Проверяем системный chromium (только если не snap-скрипт)
        for candidate in [
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]:
            if os.path.exists(candidate):
                try:
                    with open(candidate, "r", errors="ignore") as f:
                        content = f.read(512)
                        if "snap" in content.lower():
                            continue  # Пропускаем snap-обертку
                except Exception:
                    pass
                return candidate

        # 4. Резервный вариант: Snap (если ничего другого нет)
        for snap_candidate in ["/snap/bin/chromium", "/usr/bin/chromium-browser"]:
            if os.path.exists(snap_candidate):
                return snap_candidate

        which_path = shutil.which("google-chrome") or shutil.which("chromium")
        if which_path:
            return which_path

    return None
