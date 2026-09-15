import io
import json
import logging
from pathlib import Path
from typing import Set, List, Optional, Union
from PIL import Image

logger = logging.getLogger("MessageTracker")

DATA_FILE = Path(__file__).resolve().parent / "state.json"


def compute_dhash(img_bytes: bytes) -> int:
    """
    Вычисляет 64-битный разностный хеш (dHash).
    Иммунен к масштабированию, сжатию JPEG/WebP и изменению метаданных мессенджером.
    """
    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(im.getdata())
        diff = []
        for row in range(8):
            for col in range(8):
                diff.append(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
        return sum([1 << i for i, v in enumerate(diff) if v])
    except Exception:
        return 0


def hamming_distance(h1: int, h2: int) -> int:
    """Вычисляет расстояние Хэмминга (число различающихся бит между двумя хешами)."""
    return bin(h1 ^ h2).count("1")


class MessageTracker:
    """
    Менеджер состояния сообщений на основе уникальных сигнатур (текст + время + вложения)
    и перцептивных хешей (dHash) карточек для 100% предотвращения самоответов бота.
    """

    def __init__(self, filepath: Path = DATA_FILE):
        self.filepath = filepath
        self.handled_signatures: Set[str] = set()
        self.last_handled_index: int = -1
        self.handled_indices: Set[int] = set()
        self.known_bot_dhashes: Set[int] = set()
        self.load()

    def load(self):
        """Загружает сохраненное состояние из JSON файла."""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.handled_signatures = set(data.get("handled_signatures", []))
                    self.last_handled_index = data.get("last_handled_index", -1)
                    self.handled_indices = set(data.get("handled_indices", []))
                    self.known_bot_dhashes = set(data.get("known_bot_dhashes", []))
                    logger.info(f"Загружено состояние: {len(self.handled_signatures)} сообщений, {len(self.known_bot_dhashes)} хешей карточек бота.")
            except Exception as e:
                logger.warning(f"Не удалось прочитать {self.filepath}: {e}")
                self.handled_signatures = set()
                self.last_handled_index = -1
                self.handled_indices = set()
                self.known_bot_dhashes = set()
        else:
            self.handled_signatures = set()
            self.last_handled_index = -1
            self.handled_indices = set()
            self.known_bot_dhashes = set()

    def save(self):
        """Сохраняет состояние в файл state.json."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "handled_signatures": sorted(list(self.handled_signatures))[-1500:],
                        "last_handled_index": self.last_handled_index,
                        "handled_indices": sorted(list(self.handled_indices))[-1000:],
                        "known_bot_dhashes": sorted(list(self.known_bot_dhashes))[-500:],
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Ошибка сохранения состояния: {e}")

    def is_handled(self, item: Union[str, int], idx: Optional[int] = None) -> bool:
        """
        Проверяет, обработано ли сообщение.
        Если передан idx, проверяет как сигнатуру, так и числовой индекс data-index.
        """
        if idx is not None and idx in self.handled_indices:
            return True
        if isinstance(item, str):
            return item in self.handled_signatures
        elif isinstance(item, int):
            return item in self.handled_indices
        return False

    def mark_handled(self, item: Union[str, int], idx: Optional[int] = None):
        """Отмечает сообщение как обработанное (по сигнатуре и/или индексу)."""
        if isinstance(item, str):
            self.handled_signatures.add(item)
        elif isinstance(item, int):
            self.handled_indices.add(item)
            if item > self.last_handled_index:
                self.last_handled_index = item
        if idx is not None:
            self.handled_indices.add(idx)
            if idx > self.last_handled_index:
                self.last_handled_index = idx
        self.save()

    def add_bot_dhash(self, dhash: int):
        """Регистрирует перцептивный dHash отправленной ботом карточки."""
        if dhash:
            self.known_bot_dhashes.add(dhash)
            self.save()

    def is_bot_card_dhash(self, img_bytes: bytes, max_distance: int = 4) -> bool:
        """
        Проверяет, совпадает ли перцептивный dHash изображения с какой-либо
        из ранее созданных карточек бота (с допуском погрешности сжатия).
        """
        if not self.known_bot_dhashes:
            return False
        img_h = compute_dhash(img_bytes)
        if not img_h:
            return False
        for bot_h in self.known_bot_dhashes:
            if hamming_distance(img_h, bot_h) <= max_distance:
                return True
        return False

    def sync_baseline(self, signatures: List[str], indices: Optional[List[int]] = None):
        """
        Фиксирует историю сообщений чата при старте браузера:
        сигнатуры добавляются в постоянную базу, а индексы инициализируют
        текущую сессию.
        """
        for sig in signatures:
            self.handled_signatures.add(sig)
        if indices is not None:
            self.handled_indices = set(indices)
            self.last_handled_index = max(indices) if indices else -1
        self.save()


# Алиас для обратной совместимости
BlacklistManager = MessageTracker
