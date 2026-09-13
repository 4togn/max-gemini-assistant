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


class GeminiClient:
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model_name = model or config.GEMINI_MODEL
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
        Поддерживает автоматический быстрый retry при 503 / 429.
        """
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
            logger.info(f"Мультимодальный запрос к Gemini [{self.model_name}] с фото ({len(images)} шт.): {log_text}")
        else:
            logger.info(f"Текстовый запрос к Gemini [{self.model_name}]: {prompt[:60]}...")

        # Текст запроса / подпись к фото
        if prompt and prompt.strip():
            contents.append(prompt.strip())
        elif images:
            # Универсальный prompt для фото без текста: ИИ сам автономно определяет суть
            contents.append("Внимательно изучи изображение. Проанализируй его суть и автономно определи, что требуется: реши задачи/тесты, определи точную модель и характеристики предмета/устройства, исправь код или извлеки информацию. Дай исчерпывающий структурированный ответ по существу.")

        # Строго используем указанную пользователем модель (gemini-3.8-flash)
        last_error = None
        for attempt in range(1, 5):
            try:
                if attempt > 1:
                    logger.info(f"Повторная попытка ({attempt}/4) к Gemini [{self.model_name}]...")
                response = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.7,
                    ),
                )
                if response and response.text:
                    return response.text
                else:
                    raise ValueError("Получен пустой ответ от Gemini API.")
            except Exception as e:
                last_error = e
                err_str = str(e)
                is_transient = any(
                    term in err_str.lower()
                    for term in ["503", "429", "unavailable", "high demand", "resourceexhausted"]
                )
                if is_transient and attempt < 4:
                    wait_sec = 0.5 * (2 ** (attempt - 1))
                    logger.warning(f"Модель {self.model_name} временно занята (503/429). Быстрый повтор через {wait_sec:.1f}с...")
                    await asyncio.sleep(wait_sec)
                    continue
                else:
                    logger.error(f"Ошибка вызова Gemini API [{self.model_name}]: {e}")
                    break

        if last_error:
            raise last_error

    async def warmup(self):
        """Прогревает HTTP-клиент и SSL-сессию к Gemini при старте бота."""
        try:
            client = self._get_client()
            logger.info(f"Прогрев соединения с Gemini [{self.model_name}]...")
            await client.aio.models.generate_content(
                model=self.model_name,
                contents="1+1=?",
                config=types.GenerateContentConfig(temperature=0.1),
            )
            logger.info("Соединение с Gemini успешно прогрето (готов к мгновенному ответу).")
        except Exception as e:
            logger.warning(f"Прогрев Gemini завершился с предупреждением: {e}")
