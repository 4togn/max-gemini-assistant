import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional, List

import config
from gemini_client import GeminiClient
from renderer import WebPRenderer
from max_client import MaxClient

# Обеспечиваем корректный вывод UTF-8 в консоли Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("MAX-GEMINI")


class BotApp:
    def __init__(self):
        self.gemini = GeminiClient()
        self.renderer = WebPRenderer()
        self.max_client = MaxClient(on_message_callback=self.handle_incoming_message)
        self.is_processing = False

    async def handle_incoming_message(self, user_text: str, images: Optional[list] = None):
        """Обработка входящего текстового или фото-сообщения."""
        if self.is_processing:
            logger.info("Уже идет генерация предыдущего ответа, пропускаем повторный вызов.")
            return

        self.is_processing = True
        msg_type = f"фото ({len(images)} шт.) с текстом" if (images and user_text) else ("фото" if images else "текст")
        logger.info(f"==> Принято сообщение [{msg_type}]: '{user_text[:80]}'")

        try:
            # 1. Запрос к Gemini (текстовый или мультимодальный с фото)
            logger.info("Обращение к Gemini 3.8 Flash...")
            ai_response = await self.gemini.generate_response(prompt=user_text, images=images)
            logger.info(f"Ответ от Gemini получен ({len(ai_response)} симв.)")

            # 2. Рендеринг в WebP
            timestamp = int(time.time())
            webp_file = config.OUTPUT_DIR / f"answer_{timestamp}.webp"

            logger.info(f"Компиляция карточки в {webp_file.name}...")
            await self.renderer.render_to_webp(
                md_content=ai_response,
                output_path=webp_file,
                model_name=config.GEMINI_MODEL,
            )
            logger.info(f"Карточка успешно скомпилирована (размер: {webp_file.stat().st_size / 1024:.1f} Кб)")

            # 3. Отправка в MAX
            await self.max_client.send_webp_card(webp_file)
            logger.info("==> Ответ успешно доставлен в чат MAX!")

        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
            # В случае ошибки отправляем понятную карточку с подсказкой
            try:
                err_msg = str(e)
                if "503" in err_msg or "unavailable" in err_msg.lower() or "high demand" in err_msg.lower():
                    user_facing_err = "⚠️ **Сервер Google Gemini временно перегружен** (ошибка 503).\n\nНагрузка спадает за несколько секунд. Пожалуйста, отправьте сообщение или фото ещё раз."
                elif "429" in err_msg or "quota" in err_msg.lower():
                    user_facing_err = "⚠️ **Превышен лимит запросов Gemini API** (ошибка 429).\n\nПожалуйста, подождите минуту перед следующим запросом."
                else:
                    user_facing_err = f"⚠️ **Не удалось обработать запрос:**\n\n```\n{err_msg[:250]}\n```"

                err_file = config.OUTPUT_DIR / f"error_{int(time.time())}.webp"
                await self.renderer.render_to_webp(
                    md_content=user_facing_err,
                    output_path=err_file,
                    model_name="Assistant",
                )
                await self.max_client.send_webp_card(err_file)
            except Exception:
                pass
        finally:
            self.is_processing = False

    async def run(self):
        """Главный цикл работы приложения."""
        logger.info("=========================================")
        logger.info("   Запуск бота MAX Gemini WebP Assistant ")
        logger.info("=========================================")

        # Проверка наличия API ключа
        if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your_gemini_api_key_here":
            logger.warning("=" * 60)
            logger.warning("ВНИМАНИЕ: GEMINI_API_KEY не указан в файле .env!")
            logger.warning("Пожалуйста, откройте .env и вставьте ваш ключ Google Gemini.")
            logger.warning("=" * 60)

        try:
            # Запуск клиента MAX
            await self.max_client.start()

            # Запуск мониторинга
            await self.max_client.monitor_messages()
        except KeyboardInterrupt:
            logger.info("Остановка бота пользователем...")
        except Exception as e:
            logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        finally:
            await self.max_client.close()


if __name__ == "__main__":
    app = BotApp()
    try:
        asyncio.run(app.run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот успешно остановлен. До связи!")
