import io
import re
import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import markdown
from PIL import Image
from playwright.async_api import async_playwright

import config


class WebPRenderer:
    def __init__(self):
        self.env = Environment(loader=FileSystemLoader(str(config.TEMPLATES_DIR)))
        self.template = self.env.get_template("card.html")

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

    async def render_to_webp(self, md_content: str, output_path: Path, model_name: str = None) -> Path:
        """
        Рендерит Markdown в HTML и делает скриншот в формате WebP.
        """
        html = self.generate_html(md_content, model_name)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # device_scale_factor=2 дает кристальную четкость текста (Retina)
            context = await browser.new_context(
                viewport={"width": config.CARD_WIDTH + 80, "height": 800},
                device_scale_factor=2,
            )
            page = await context.new_page()

            # Загружаем HTML контент
            await page.set_content(html, wait_until="networkidle")

            # Ожидаем отрисовки KaTeX и Highlight.js
            await page.wait_for_timeout(350)

            # Получаем элемент карточки и делаем PNG-скриншот
            card_el = page.locator("#card")
            png_bytes = await card_el.screenshot(type="png")
            await browser.close()

        # Сжимаем и сохраняем в легковесный WebP через Pillow (RGB, quality=82)
        image = Image.open(io.BytesIO(png_bytes))
        if image.mode in ("RGBA", "P"):
            # Создаем сплошной черный фон
            background = Image.new("RGB", image.size, (0, 0, 0))
            if image.mode == "RGBA":
                background.paste(image, mask=image.split()[3])
            else:
                background.paste(image)
            image = background
        else:
            image = image.convert("RGB")

        image.save(output_path, "WEBP", quality=82, method=6)

        return output_path
