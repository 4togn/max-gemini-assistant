import json
import logging
from pathlib import Path
from typing import Set

logger = logging.getLogger("MessageTracker")

DATA_FILE = Path(__file__).resolve().parent / "state.json"


class MessageTracker:
    """
    Менеджер состояния сообщений на основе уникальных индексов data-index из MAX Web.
    Позволяет пользователю задавать один и тот же вопрос любое количество раз,
    при этом гарантируя, что старые сообщения из истории никогда не будут повторно обработаны.
    """

    def __init__(self, filepath: Path = DATA_FILE):
        self.filepath = filepath
        self.last_handled_index: int = -1
        self.handled_indices: Set[int] = set()
        self.load()

    def load(self):
        """Загружает сохраненное состояние из JSON файла."""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.last_handled_index = data.get("last_handled_index", -1)
                    self.handled_indices = set(data.get("handled_indices", []))
                    logger.info(
                        f"Загружено состояние: последний индекс={self.last_handled_index}, "
                        f"обработано сообщений={len(self.handled_indices)}"
                    )
            except Exception as e:
                logger.warning(f"Не удалось прочитать {self.filepath}: {e}")
                self.last_handled_index = -1
                self.handled_indices = set()
        else:
            self.last_handled_index = -1
            self.handled_indices = set()

    def save(self):
        """Сохраняет состояние в файл state.json."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "last_handled_index": self.last_handled_index,
                        "handled_indices": sorted(list(self.handled_indices)),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Ошибка сохранения состояния: {e}")

    def is_handled(self, index: int) -> bool:
        """
        Проверяет, было ли сообщение с данным индексом уже обработано.
        Любой индекс <= last_handled_index или уже занесенный в handled_indices считается обработанным.
        """
        return index <= self.last_handled_index or index in self.handled_indices

    def mark_handled(self, index: int):
        """Отмечает сообщение с указанным индексом как обработанное."""
        if index > self.last_handled_index:
            self.last_handled_index = index
        self.handled_indices.add(index)
        self.save()

    def sync_baseline(self, current_max_index: int):
        """
        Устанавливает базовую точку при старте бота.
        Все сообщения в чате до этого индекса считаются старыми и не обрабатываются.
        """
        if current_max_index > self.last_handled_index:
            logger.info(f"Синхронизация базовой точки: {self.last_handled_index} -> {current_max_index}")
            self.last_handled_index = current_max_index
            self.handled_indices.add(current_max_index)
            self.save()


# Алиас для обратной совместимости
BlacklistManager = MessageTracker
