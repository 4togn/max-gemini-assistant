import asyncio
from pathlib import Path
from renderer import WebPRenderer
import config

TEST_MARKDOWN = """# 🚀 Тест рендеринга карточки

Привет! Это демонстрация рендеринга сложных математических формул и форматирования в формат **WebP**.

### 📐 Математические формулы (KaTeX):
1. Инлайн-формула корня и дроби: $x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$
2. Степени и пределы: $\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1$
3. Интеграл Гаусса:
$$\\int_{-\\infty}^{\\infty} e^{-x^2} dx = \\sqrt{\\pi}$$

### 💻 Пример кода с подсветкой:
```python
def solve_quadratic(a, b, c):
    d = b**2 - 4*a*c
    if d < 0:
        return None
    root_d = d**0.5
    return (-b - root_d)/(2*a), (-b + root_d)/(2*a)
```

### 📊 Таблица характеристик:
| Параметр | Значение |
| :--- | :--- |
| Формат изображения | **WebP** |
| Разрешение | 2x Retina |
| Средний вес | **~30-50 Кб** |
| Скорость рендера | **~300 мс** |

> Карточка легко открывается в галерее любого смартфона даже при белых списках!
"""

async def main():
    print("[+] Инициализация WebPRenderer...")
    renderer = WebPRenderer()

    output_path = config.OUTPUT_DIR / "test_sample.webp"
    print(f"[+] Рендеринг тестовой карточки в {output_path}...")

    await renderer.render_to_webp(
        md_content=TEST_MARKDOWN,
        output_path=output_path,
        model_name="Gemini 3.8 Flash (Test)",
    )

    if output_path.exists():
        size_kb = output_path.stat().st_size / 1024
        print(f"[OK] УСПЕХ: Карточка сгенерирована!")
        print(f"    Путь: {output_path.resolve()}")
        print(f"    Размер: {size_kb:.2f} Кб")
    else:
        print("[FAIL] ОШИБКА: Файл не был создан.")

if __name__ == "__main__":
    asyncio.run(main())
