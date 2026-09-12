import asyncio
import logging
from typing import List, Optional, Union
from google import genai
from google.genai import types
import config

logger = logging.getLogger("GeminiClient")

SYSTEM_INSTRUCTION = """Ты — умный и эрудированный ИИ-ассистент на базе модели Gemini.
Твои ответы рендерятся в графические карточки, поэтому следуй правилам оформления:
1. Математические формулы, дроби, корни, степени, интегралы ВСЕГДА форматируй строго в синтаксисе LaTeX:
   - Инлайн формулы: в одинарных знаках доллара $...$, например: $\\sqrt{x^2 + y^2}$, $x_1 = \\frac{-b \\pm \\sqrt{D}}{2a}$.
   - Блочные формулы: в двойных долларах $$...$$.
2. Блоки кода оформляй в стандартные тройные бэктики с указанием языка программирования (например, ```python).
3. Используй полноценную структуру Markdown: подробные объяснения, примеры, списки, жирный шрифт, таблицы при необходимости.
4. Если прикреплено фото (изображение задачи, рукописный конспект, график, схема, фрагмент кода или скриншот):
   - Внимательно распознай текст и условия задачи на фото.
   - Дай исчерпывающее, пошаговое решение или подробный разбор.
5. Отвечай развернуто, глубоко и информативно, в точности как в стандартной веб-версии Gemini."""


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
        Поддерживает автоматический retry при перегрузке (503 / 429) и fallback на резервную модель.
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
            contents.append("Внимательно изучи изображение. Подробно объясни, реши или проанализируй то, что на нем представлено.")

        # Список моделей для вызова: основная + резервная при 503 перегрузке
        candidate_models = [self.model_name]
        if "2.5-flash" not in self.model_name:
            candidate_models.append("gemini-2.5-flash")

        last_error = None
        for current_model in candidate_models:
            for attempt in range(1, 4):
                try:
                    if attempt > 1:
                        logger.info(f"Повторная попытка ({attempt}/3) к Gemini [{current_model}]...")
                    response = await client.aio.models.generate_content(
                        model=current_model,
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
                    if is_transient and attempt < 3:
                        wait_sec = attempt * 2
                        logger.warning(f"Модель {current_model} временно занята (503/429). Ждем {wait_sec}с перед повтором...")
                        await asyncio.sleep(wait_sec)
                        continue
                    elif is_transient and current_model != candidate_models[-1]:
                        logger.warning(f"Модель {current_model} перегружена. Переключаемся на резервную {candidate_models[-1]}...")
                        break
                    else:
                        logger.error(f"Ошибка вызова Gemini API [{current_model}]: {e}")
                        break

        if last_error:
            raise last_error
