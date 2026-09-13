import io
import re
import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import markdown
from PIL import Image
from playwright.async_api import async_playwright

import config


from history_manager import compute_dhash

class WebPRenderer:
    def __init__(self, context_getter=None):
        self.env = Environment(loader=FileSystemLoader(str(config.TEMPLATES_DIR)))
        self.template = self.env.get_template("card.html")
        self.context_getter = context_getter
        self._fallback_playwright = None
        self._fallback_browser = None
        self._fallback_context = None
        self._render_page = None
        self.last_card_dhash = None

    def set_context_getter(self, getter):
        """Устанавливает функцию получения активного контекста браузера."""
        self.context_getter = getter

    async def _get_render_page(self, context):
        """Возвращает постоянно открытую вкладку для рендеринга без накладных расходов на открытие/закрытие."""
        if self._render_page and not self._render_page.is_closed():
            return self._render_page
        self._render_page = await context.new_page()
        return self._render_page

    def _protect_math(self, text: str):
        """
        Защищает формулы LaTeX ($...$ и $$...$$) от парсера Markdown,
        чтобы символы _ и * внутри формул не превращались в курсив/жирный шрифт.
        """
        math_blocks = []

        def replace_block(match):
            math_blocks.append(match.group(0))
            return f"%%MATH_BLOCK_{len(math_blocks) - 1}%%"

        # Сначала блочные $$...$$, затем инлайн $...$
        text = re.sub(r"\$\$(.*?)\$\$", replace_block, text, flags=re.DOTALL)
        text = re.sub(r"(?<!\\)\$(.*?)(?<!\\)\$", replace_block, text)

        return text, math_blocks

    def _restore_math(self, html: str, math_blocks: list) -> str:
        """Восстанавливает защищенные формулы обратно в HTML."""
        for i, block in enumerate(math_blocks):
            html = html.replace(f"%%MATH_BLOCK_{i}%%", block)
        return html

    def markdown_to_html(self, md_text: str) -> str:
        """Конвертирует Markdown в HTML с поддержкой таблиц и блоков кода."""
        protected_text, math_blocks = self._protect_math(md_text)

        html = markdown.markdown(
            protected_text,
            extensions=[
                "extra",
                "tables",
                "fenced_code",
                "nl2br",
                "sane_lists",
            ],
        )

        return self._restore_math(html, math_blocks)

    def generate_html(self, md_content: str, model_name: str = None) -> str:
        """Генерирует полный HTML-документ карточки."""
        content_html = self.markdown_to_html(md_content)
        now_str = datetime.datetime.now().strftime("%H:%M")

        return self.template.render(
            content_html=content_html,
            model_name=model_name or config.GEMINI_MODEL,
            timestamp=now_str,
            theme=config.CARD_THEME,
            width=config.CARD_WIDTH,
        )

    async def render_to_webp(self, md_content: str, output_path: Path, model_name: str = None) -> tuple[Path, int]:
        """
        Рендерит Markdown в HTML через постоянную прогретую вкладку браузера
        и компилирует карточку в WebP за ~1-2 секунды.
        Возвращает кортеж (output_path, card_dhash).
        """
        html = self.generate_html(md_content, model_name)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        context = self.context_getter() if self.context_getter else None
        if not context:
            if not self._fallback_context:
                self._fallback_playwright = await async_playwright().start()
                launch_kwargs = {
                    "headless": True,
                    "args": [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                }
                exe = config.get_chromium_executable()
                if exe:
                    launch_kwargs["executable_path"] = exe
                self._fallback_browser = await self._fallback_playwright.chromium.launch(**launch_kwargs)
                self._fallback_context = await self._fallback_browser.new_context(
                    viewport={"width": config.CARD_WIDTH + 80, "height": 800},
                    device_scale_factor=1,
                )
            context = self._fallback_context

        # Рендерим через постоянную вкладку (без повторного создания/закрытия)
        page = await self._get_render_page(context)
        base_html = html.replace("<head>", f'<head><base href="file://{config.TEMPLATES_DIR}/">')
        await page.set_content(base_html, wait_until="domcontentloaded")
        await page.wait_for_timeout(50)

        # Получаем элемент карточки и делаем моментальный снимок
        card_el = page.locator("#card")
        png_bytes = await card_el.screenshot(type="png")

        # Вычисляем перцептивный dHash карточки для защиты от самоответов
        card_dhash = compute_dhash(png_bytes)
        self.last_card_dhash = card_dhash

        # Сжимаем в WebP (quality=82, method=0 — моментальное сохранение за 50мс)
        image = Image.open(io.BytesIO(png_bytes))
        if image.mode in ("RGBA", "P"):
            background = Image.new("RGB", image.size, (0, 0, 0))
            if image.mode == "RGBA":
                background.paste(image, mask=image.split()[3])
            else:
                background.paste(image)
            image = background
        else:
            image = image.convert("RGB")

        image.save(output_path, "WEBP", quality=82, method=0)

        return output_path, card_dhash

    async def close(self):
        """Очистка ресурсов при завершении."""
        if self._render_page and not self._render_page.is_closed():
            try:
                await self._render_page.close()
            except Exception:
                pass
        if self._fallback_context:
            try:
                await self._fallback_context.close()
            except Exception:
                pass
        if self._fallback_browser:
            try:
                await self._fallback_browser.close()
            except Exception:
                pass
        if self._fallback_playwright:
            try:
                await self._fallback_playwright.stop()
            except Exception:
                pass
