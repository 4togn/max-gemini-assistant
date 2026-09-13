import asyncio
import logging
from typing import List, Optional, Union
from google import genai
from google.genai import types
import config

logger = logging.getLogger("GeminiClient")

SYSTEM_INSTRUCTION = """Ты — интеллектуальный мультимодальный ИИ-ассистент на базе модели Gemini.
Твои ответы оформляются в графические карточки, поэтому строго соблюдай правила:

1. ОФОРМЛЕНИЕ:
   - Математические формулы, дроби, корни, интегралы ВСЕГДА форматируй строго в LaTeX:
     Инлайн формулы: в одинарных долларах $...$, например: $\\sqrt{x^2 + y^2}$, $x = \\frac{-b \\pm \\sqrt{D}}{2a}$.
     Блочные формулы: в двойных долларах $$...$$.
   - Блоки кода оформляй в стандартные тройные бэктики с указанием языка программирования (например, ```python, ```cpp).
   - Используй аккуратную структуру Markdown: заголовки, списки, жирный шрифт, таблицы.

2. АВТОНОМНОСТЬ И УНИВЕРСАЛЬНОСТЬ (САМ ДОГАДЫВАЙСЯ О СУТИ И ЦЕЛИ):
   Действуй точно так же, как в нативном веб-интерфейсе Gemini: самостоятельно понимай намерение пользователя по контексту изображения. Никогда не задавай встречных вопросов, не говори «Что мне нужно сделать?», «Уточните запрос», «Чем я могу помочь?», «Здесь нет задач» или «На фото белый лист». Сразу выдавай готовый, профессиональный результат:
   
   - ЗАДАЧИ, ТЕСТЫ, УПРАЖНЕНИЯ, ВОПРОСЫ:
     Если на изображении задача, тест, контрольная, уравнение или вопросы — сразу дай четкие, правильные ответы с подробным пошаговым решением и объяснением каждого пункта.

   - ПРЕДМЕТЫ, ГАДЖЕТЫ, УСТРОЙСТВА, ТЕХНИКА (компьютерная мышь, клавиатура, смартфон, плата, инструмент, часы, одежда, автомобиль и др.):
     Сразу точно определи объект, назови его точную модель и производителя (если различимы логотипы, форма или детали), подробно опиши назначение, ключевые характеристики, спецификации, особенности и функционал.

   - РАСТЕНИЯ, ЖИВОТНЫЕ, ДОСТОПРИМЕЧАТЕЛЬНОСТИ, ПРОИЗВЕДЕНИЯ ИСКУССТВА:
     Сразу назови вид, породу, название места или объекта, укажи интересные факты, происхождение и важные детали.

   - ПРОГРАММНЫЙ КОД И ОШИБКИ:
     Кратко укажи причину ошибки/бага и приведи полностью исправленный рабочий код.

   - ДОКУМЕНТЫ, ТАБЛИЦЫ, КОНСПЕКТЫ, СКРИНШОТЫ ИНТЕРФЕЙСА:
     Структурируй, переведи, выдели главное или перескажи суть информации.

3. ПРИНЦИП ОТВЕТА:
   Сразу к сути, глубоко, структурировано и без лишней «воды» и пустых описаний окружения."""


def _detect_mime_type(data: bytes) -> str:
    """Определяет MIME-тип изображения по магическим байтам."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    if data.startswith(b"GIF"):
        return "image/gif"
    return "image/jpeg"


MODELS_CASCADE = getattr(
    config,
    "MODELS_CASCADE",
    [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ],
)


class GeminiClient:
    def __init__(
        self,
        api_key: str = None,
        primary_model: str = None,
        backup_models: Optional[List[str]] = None,
    ):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.primary_model = primary_model or config.PRIMARY_MODEL
        self.backup_models = backup_models if backup_models is not None else list(config.BACKUP_MODELS)
        self.model_name = self.primary_model or ""
        self.last_used_model = self.primary_model or "Assistant"
        self._client = None

    def _get_client(self):
        if not self._client:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY не установлен! Укажите его в .env файле.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate_response(
        self,
        prompt: str = "",
        images: Optional[Union[bytes, List[bytes]]] = None,
    ) -> str:
        """
        Отправляет запрос к модели Gemini (текстовый или мультимодальный с фото).
        Правила выполнения:
        1. К основной модели (GEMINI_MODEL_1) делается ровно 3 попытки.
        2. Если основная модель не ответила после 3 попыток:
           - если резервные модели не заданы (GEMINI_MODEL_2..4 пустые) -> сразу выбрасывается ошибка.
           - если заданы -> переходит по очереди к резервным моделям (пустые переменные уже пропущены).
        3. Если и последняя резервная модель не ответила -> выбрасывается ошибка (бот отправляет карточку в чат).
        """
        if not self.primary_model:
            raise ValueError("Основная модель (GEMINI_MODEL_1) не указана в .env!")

        client = self._get_client()
        contents = []

        # Обработка изображений
        if images:
            if isinstance(images, bytes):
                images = [images]

            for img_bytes in images:
                if img_bytes:
                    mime = _detect_mime_type(img_bytes)
                    contents.append(
                        types.Part.from_bytes(
                            data=img_bytes,
                            mime_type=mime,
                        )
                    )

            log_text = prompt[:60] if prompt else "[Фото без текста]"
            logger.info(f"Мультимодальный запрос к Gemini [{self.primary_model}] с фото ({len(images)} шт.): {log_text}")
        else:
            logger.info(f"Текстовый запрос к Gemini [{self.primary_model}]: {prompt[:60]}...")

        # Текст запроса / подпись к фото
        if prompt and prompt.strip():
            contents.append(prompt.strip())
        elif images:
            # Универсальный prompt для фото без текста: ИИ сам автономно определяет суть
            contents.append("Внимательно изучи изображение. Проанализируй его суть и автономно определи, что требуется: реши задачи/тесты, определи точную модель и характеристики предмета/устройства, исправь код или извлеки информацию. Дай исчерпывающий структурированный ответ по существу.")

        # Составляем список моделей: основная + заданные резервные (пустые уже отфильтрованы)
        models_to_try = [self.primary_model] + self.backup_models

        last_error = None
        for model_idx, current_model in enumerate(models_to_try, start=1):
            is_primary = (model_idx == 1)
            model_type = "Основная" if is_primary else f"Резервная #{model_idx - 1}"

            # Делаем до 4 попыток на каждую модель (поскольку модель часто отвечает с 3-4 попытки)
            for attempt in range(1, 5):
                try:
                    if attempt > 1:
                        logger.info(f"Повторная попытка ({attempt}/4) к {model_type.lower()} модели [{current_model}]...")
                    else:
                        logger.info(f"Запрос к {model_type.lower()} модели [{current_model}] (попытка 1/4)...")

                    response = await client.aio.models.generate_content(
                        model=current_model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.7,
                        ),
                    )
                    if response and response.text:
                        self.last_used_model = current_model
                        logger.info(f"Успешный ответ от [{current_model}] (попытка {attempt}/4).")
                        return response.text
                    else:
                        raise ValueError(f"Получен пустой ответ от [{current_model}].")

                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    logger.warning(
                        f"{model_type} модель [{current_model}] (попытка {attempt}/4) ошибка: {e}"
                    )

                    # Если исчерпан суточный лимит запросов (20 req/day per project), повторять бессмысленно
                    is_daily_limit = "perday" in err_str.lower() or ("quota exceeded" in err_str.lower() and "limit: 20" in err_str.lower())
                    if is_daily_limit:
                        logger.warning(
                            f"Суточный лимит для [{current_model}] исчерпан (429 perday). "
                            f"Прекращаю повторы к этой модели и перехожу к следующей."
                        )
                        break

                    # Пауза перед следующей попыткой к той же модели (0.5с)
                    if attempt < 4:
                        await asyncio.sleep(0.5)

            # Если все попытки к текущей модели завершились неудачей
            has_next = (model_idx < len(models_to_try))
            if has_next:
                next_model = models_to_try[model_idx]
                logger.warning(
                    f"Все 4 попытки к [{current_model}] исчерпаны. "
                    f"Переключаюсь на следующую модель: [{next_model}]..."
                )
            else:
                logger.error(
                    f"Все 4 попытки к последней доступной модели [{current_model}] исчерпаны. "
                    f"Других моделей в .env нет."
                )

        # Если все доступные модели завершились ошибкой
        raise last_error

    async def warmup(self):
        """Прогревает HTTP-клиент и SSL-сессию к Gemini при старте бота."""
        if not self.primary_model:
            return

        client = self._get_client()

        # Сначала пробуем прогреть основную модель
        try:
            logger.info(f"Прогрев соединения с основной моделью [{self.primary_model}]...")
            await client.aio.models.generate_content(
                model=self.primary_model,
                contents="1+1=?",
                config=types.GenerateContentConfig(temperature=0.1),
            )
            logger.info(f"Основная модель [{self.primary_model}] успешно прогрета.")
            self.last_used_model = self.primary_model
            return
        except Exception as e:
            logger.warning(f"Основная модель [{self.primary_model}] недоступна при прогреве (квота/занято): {e}")

        # Если основная недоступна, пробуем резервные по очереди
        for backup_model in self.backup_models:
            try:
                logger.info(f"Прогрев соединения с резервной моделью [{backup_model}]...")
                await client.aio.models.generate_content(
                    model=backup_model,
                    contents="1+1=?",
                    config=types.GenerateContentConfig(temperature=0.1),
                )
                logger.info(f"Резервная модель [{backup_model}] успешно прогрета.")
                self.last_used_model = backup_model
                return
            except Exception as e:
                logger.warning(f"Резервная модель [{backup_model}] недоступна при прогреве: {e}")
