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
   - Математические формулы, дроби, корни, интегралы, переменные уравнений ВСЕГДА форматируй в LaTeX:
     Инлайн формулы: в одинарных долларах $...$, например: $I = \\frac{U}{R}$, $R = \\text{const}$, $\\sqrt{x^2 + y^2}$, $x = \\frac{-b \\pm \\sqrt{D}}{2a}$.
     Блочные формулы: в двойных долларах $$...$$.
   - ВАЖНО: Обычные числа (3, 7, 12, 100), диапазоны (20–25) и стрелки химических/биологических процессов (→) пиши ОБЫЧНЫМ ТЕКСТОМ без знаков доллара (НЕ пиши $3$, НЕ пиши $20\\text{–}25$, НЕ пиши $\\rightarrow$). Используй стандартный юникод-символ стрелки →.
   - Блоки кода оформляй в стандартные тройные бэктики с указанием языка программирования (например, ```python, ```cpp).
   - Используй аккуратную структуру Markdown: заголовки, списки, жирный шрифт, таблицы.

2. АВТОНОМНОСТЬ И АНТИГАЛЛЮЦИНАЦИЯ:
   - КОГДА ЕСТЬ ФОТО ИЛИ ТЕКСТ МАТЕРИАЛА:
     Самостоятельно понимай намерение пользователя. Никогда не задавай пустых встречных вопросов («Чем помочь?», «На фото белый лист»). Сразу выдавай готовый, профессиональный результат:
     * Задачи, тесты, вопросы: сразу дай четкие ответы с подробным пошаговым решением.
     * Учебники, параграфы, конспекты: сделай подробный структурированный конспект, выпиши все ключевые определения и ответь на все вопросы к параграфу.
     * Предметы, гаджеты, техника, растения, животные: определи объект, укажи модель, вид, характеристики.
     * Код и ошибки: укажи причину ошибки и приведи исправленный код.
   - СТРОГИЙ ЗАПРЕТ НА ВЫДУМЫВАНИЕ (АНТИГАЛЛЮЦИНАЦИЯ):
     Если пользователь присылает чисто текстовый запрос вида «Расскажи этот параграф», «Сделай по нему конспект», «Реши задачу на фото», но при этом к запросу НЕ прикреплено ни одного изображения и в тексте нет самого материала параграфа/задачи — КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать случайный параграф или тему (например, закон Ома или параграф по физике).
     В таком случае четко и вежливо ответь: «Пожалуйста, прикрепите фото страницы/параграфа или напишите его текст/номер и тему учебника — сейчас файл не прикрепился к сообщению.»

3. ПРИНЦИП ОТВЕТА:
   Сразу к сути, глубоко, структурировано и без лишней «воды»."""


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
        self._model_cooldowns = {}  # {model_name: expiry_timestamp}

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
        1. Проверяет модели на кулдаун (если модель выдавала 503/429 в последние минуты,
           она временно пропускается, чтобы пользователь не ждал по 3 минуты).
        2. На каждую модель делается максимум 2 попытки с жестким таймаутом 25 сек.
        3. При перегрузке (503) модель ставится на 3-минутный кулдаун и бот мгновенно
           переключается на следующую резервную модель.
        """
        import time

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
            contents.append("Внимательно изучи прикрепленные изображения. Проанализируй их суть и автономно определи, что требуется: реши задачи/тесты со всех страниц, определи точную модель и характеристики предметов/устройств, исправь код или извлеки информацию. Дай исчерпывающий структурированный ответ по существу.")

        # Составляем список моделей: основная + заданные резервные
        all_models = [self.primary_model] + self.backup_models
        now = time.time()

        # Фильтруем модели, находящиеся на временном кулдауне
        models_to_try = []
        for m in all_models:
            cooldown_until = self._model_cooldowns.get(m, 0)
            if now >= cooldown_until:
                models_to_try.append(m)
            else:
                rem = int(cooldown_until - now)
                logger.info(f"Модель [{m}] на кулдауне из-за недавней перегрузки ({rem}с осталось) -> быстрый переход к следующей")

        # Если все модели на кулдауне, пробуем все заново
        if not models_to_try:
            logger.info("Все модели были на кулдауне. Сбрасываем таймеры и пробуем заново.")
            models_to_try = all_models
            self._model_cooldowns.clear()

        last_error = None
        for model_idx, current_model in enumerate(models_to_try, start=1):
            is_primary = (current_model == self.primary_model)
            model_type = "Основная" if is_primary else "Резервная"

            # Максимум 2 попытки (1 запрос + 1 быстрый повтор), чтобы не держать пользователя
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        logger.info(f"Быстрый повтор ({attempt}/{max_attempts}) к {model_type.lower()} модели [{current_model}]...")
                    else:
                        logger.info(f"Запрос к {model_type.lower()} модели [{current_model}] (попытка 1/{max_attempts})...")

                    # Жесткий таймаут 25с, чтобы запрос никогда не зависал на 5-15 минут
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=current_model,
                            contents=contents,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTION,
                                temperature=0.7,
                            ),
                        ),
                        timeout=25.0,
                    )
                    if response and response.text:
                        self.last_used_model = current_model
                        logger.info(f"Успешный ответ от [{current_model}] (попытка {attempt}/{max_attempts}).")
                        # Очищаем кулдаун при успешном ответе
                        self._model_cooldowns.pop(current_model, None)
                        return response.text
                    else:
                        raise ValueError(f"Получен пустой ответ от [{current_model}].")

                except asyncio.TimeoutError:
                    last_error = TimeoutError(f"Превышено время ожидания ответа от [{current_model}] (25с).")
                    logger.warning(f"Таймаут (25с) при обращении к [{current_model}]. Ставлю на кулдаун на 3 мин.")
                    self._model_cooldowns[current_model] = time.time() + 180
                    break

                except Exception as e:
                    last_error = e
                    err_str = str(e).lower()
                    logger.warning(
                        f"{model_type} модель [{current_model}] (попытка {attempt}/{max_attempts}) ошибка: {e}"
                    )

                    # 1. Лимиты запросов (429 Resource Exhausted)
                    if "perday" in err_str or "quota exceeded" in err_str or "429" in err_str or "resource_exhausted" in err_str:
                        logger.warning(
                            f"Лимит запросов для [{current_model}] исчерпан (429). "
                            f"Ставлю на кулдаун на 10 минут и перехожу к следующей."
                        )
                        self._model_cooldowns[current_model] = time.time() + 600
                        break

                    # 2. Перегрузка серверов Google (503 Unavailable / High demand)
                    if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
                        if attempt >= max_attempts:
                            logger.warning(
                                f"Модель [{current_model}] перегружена (503). "
                                f"Ставлю на кулдаун на 3 минуты и мгновенно переключаюсь дальше."
                            )
                            self._model_cooldowns[current_model] = time.time() + 180
                            break
                        else:
                            await asyncio.sleep(0.5)
                            continue

                    # Пауза перед следующей попыткой
                    if attempt < max_attempts:
                        await asyncio.sleep(0.5)

            # Переход к следующей модели
            has_next = (model_idx < len(models_to_try))
            if has_next:
                next_model = models_to_try[model_idx]
                logger.warning(
                    f"Модель [{current_model}] недоступна. "
                    f"Мгновенно переключаюсь на следующую: [{next_model}]..."
                )
            else:
                logger.error(
                    f"Все доступные модели из каскада исчерпаны."
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
            await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.primary_model,
                    contents="1+1=?",
                    config=types.GenerateContentConfig(temperature=0.1),
                ),
                timeout=10.0,
            )
            logger.info(f"Основная модель [{self.primary_model}] успешно прогрета.")
            self.last_used_model = self.primary_model
            return
        except Exception as e:
            logger.warning(f"Основная модель [{self.primary_model}] недоступна при прогреве: {e}")

        # Если основная недоступна, пробуем резервные по очереди
        for backup_model in self.backup_models:
            try:
                logger.info(f"Прогрев соединения с резервной моделью [{backup_model}]...")
                await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=backup_model,
                        contents="1+1=?",
                        config=types.GenerateContentConfig(temperature=0.1),
                    ),
                    timeout=10.0,
                )
                logger.info(f"Резервная модель [{backup_model}] успешно прогрета.")
                self.last_used_model = backup_model
                return
            except Exception as e:
                logger.warning(f"Резервная модель [{backup_model}] недоступна при прогреве: {e}")
