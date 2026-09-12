import asyncio
import hashlib
import logging
import os
import re
import sys
from pathlib import Path
from typing import Callable, Optional
from playwright.async_api import async_playwright, BrowserContext, Page

import config
from history_manager import MessageTracker

logger = logging.getLogger("MaxClient")


class MaxClient:
    def __init__(self, on_message_callback: Optional[Callable[[str], None]] = None):
        self.on_message_callback = on_message_callback
        self.tracker = MessageTracker()
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_running = False
        self.is_uploading = False
        self.known_bot_hashes: set = set()
        self._load_known_output_hashes()

    def _load_known_output_hashes(self):
        """Загружает хеши всех ранее сгенерированных карточек из output/, чтобы бот никогда не читал свои ответы."""
        if config.OUTPUT_DIR.exists():
            for p in config.OUTPUT_DIR.glob("*.webp"):
                try:
                    h = hashlib.sha256(p.read_bytes()).hexdigest()
                    self.known_bot_hashes.add(h)
                except Exception:
                    pass
            logger.debug(f"Загружено {len(self.known_bot_hashes)} хешей собственных карточек бота.")

    def _get_launch_kwargs(self) -> dict:
        kwargs = {}
        exe = config.get_chromium_executable()
        if exe:
            logger.info(f"Используется системный Chromium: {exe}")
            kwargs["executable_path"] = exe
        return kwargs

    async def start(self):
        """Запускает браузер в невидимом режиме, при необходимости открывая видимое окно для авторизации на ПК."""
        self.playwright = await async_playwright().start()

        # 1. Запускаем браузер в фоновом (невидимом) режиме
        logger.info(f"Запуск браузера в невидимом режиме (headless=True, профиль: {config.USER_DATA_DIR})...")
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.USER_DATA_DIR),
            headless=True,
            viewport={"width": 1280, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            **self._get_launch_kwargs(),
        )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        logger.info("Открытие https://web.max.ru...")
        await self.page.goto("https://web.max.ru", wait_until="networkidle")

        # 2. Проверяем, есть ли уже сохраненная авторизация
        logger.info("Проверка статуса авторизации в MAX...")
        is_authorized = False
        for _ in range(5):
            if await self._is_in_app():
                is_authorized = True
                break
            await asyncio.sleep(1)

        # 3. Если пользователь НЕ авторизован — обрабатываем интерактивный вход
        if not is_authorized:
            logger.info("Сессия не найдена. Требуется первичная авторизация...")
            # Закрываем фоновый браузер перед открытием окна
            await self.context.close()
            self.context = None
            self.page = None
            await asyncio.sleep(1)

            # Проверяем наличие графического дисплея (сервер без монитора)
            has_display = True
            if sys.platform.startswith("linux"):
                has_display = ("DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ)

            if not has_display:
                logger.error("=" * 68)
                logger.error("ОШИБКА: Авторизация не найдена, а запуск произведен на сервере без экрана!")
                logger.error("В консоли сервера отсутствует графическая оболочка ($DISPLAY не задан).")
                logger.error("")
                logger.error("НАПОМИНАНИЕ: Первую авторизацию необходимо выполнять на устройстве с экраном!")
                logger.error("ИНСТРУКЦИЯ:")
                logger.error("1. Запустите win_start.bat на вашем ПК (Windows или Linux с графическим экраном).")
                logger.error("2. В открывшемся окне браузера введите ваш номер телефона и СМС-код.")
                logger.error("3. Закройте бота и скопируйте созданную папку 'user_data' на этот сервер.")
                logger.error("4. Запустите бот командой: ./lin_start.sh — он сразу заработает в фоне!")
                logger.error("=" * 68)
                sys.exit(1)

            # На устройстве с экраном — предупреждаем и открываем ВИДИМОЕ окно
            logger.warning("=" * 68)
            logger.warning("ВНИМАНИЕ: Авторизация в MAX не найдена!")
            logger.warning("НАПОМИНАНИЕ: Первую авторизацию необходимо выполнять на устройстве с экраном.")
            logger.warning("Сейчас откроется окно браузера MAX (web.max.ru).")
            logger.warning("Пожалуйста, введите ваш номер телефона и код подтверждения из СМС.")
            logger.warning("После успешного входа окно автоматически закроется, и бот перейдет в невидимый режим.")
            logger.warning("=" * 68)

            login_context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(config.USER_DATA_DIR),
                headless=False,
                viewport={"width": 1280, "height": 850},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                **self._get_launch_kwargs(),
            )
            login_page = login_context.pages[0] if login_context.pages else await login_context.new_page()
            await login_page.goto("https://web.max.ru", wait_until="networkidle")

            logger.info("Ожидание входа в открытом окне браузера (до 5 минут)...")
            logged_in = False
            for _ in range(150):
                is_in = await login_page.evaluate("""() => {
                    const text = document.body.innerText || '';
                    return text.includes('Чаты') || text.includes('Избранное') || document.querySelector('.contenteditable') !== null;
                }""")
                if is_in:
                    logged_in = True
                    break
                await asyncio.sleep(2)

            if not logged_in:
                await login_context.close()
                raise TimeoutError("Время ожидания авторизации в браузере истекло (5 минут).")

            logger.info("Вход успешно выполнен! Открываю чат 'Избранное' для закрепления профиля...")
            await login_page.wait_for_timeout(2000)
            chat_loc = login_page.locator(f"text='{config.MAX_CHAT_NAME}'").first
            if await chat_loc.count() > 0:
                await chat_loc.click()
                await login_page.wait_for_timeout(2000)

            await login_context.close()
            await asyncio.sleep(1)

            logger.info("Авторизация сохранена в user_data! Перезапуск в невидимом фоновом режиме...")

            # Перезапускаем постоянный контекст в невидимом режиме
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(config.USER_DATA_DIR),
                headless=True,
                viewport={"width": 1280, "height": 850},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                **self._get_launch_kwargs(),
            )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            await self.page.goto("https://web.max.ru", wait_until="networkidle")

        logger.info("Пользователь успешно авторизован.")

        # 4. Открываем чат Избранное
        await self._open_chat(config.MAX_CHAT_NAME)

        # 5. Ожидаем полной загрузки сообщений истории чата и фиксируем стартовую точку
        logger.info("Синхронизация истории сообщений: ожидание загрузки сообщений чата...")
        for _ in range(3):
            await self.page.evaluate("""() => {
                const history = document.querySelector('[class*="history"]') || document.body;
                history.scrollTop = history.scrollHeight;
                window.scrollTo(0, document.body.scrollHeight);
            }""")
            await asyncio.sleep(1)

        all_existing_indices = await self.page.evaluate("""() => {
            const history = document.querySelector('[class*="history"]') || document.querySelector('main') || document.body;
            const items = history.querySelectorAll('[data-index]');
            const indices = [];
            items.forEach(it => {
                const idxStr = it.getAttribute('data-index');
                if (idxStr !== null) {
                    const idx = parseInt(idxStr, 10);
                    if (!isNaN(idx)) indices.push(idx);
                }
            });
            return indices;
        }""")

        if all_existing_indices:
            max_idx = max(all_existing_indices)
            for idx in all_existing_indices:
                self.tracker.mark_handled(idx)
            self.tracker.sync_baseline(max_idx)
            logger.info(
                f"Стартовая синхронизация: зафиксировано {len(all_existing_indices)} существующих сообщений "
                f"(базовый ID: {max_idx}). Старые сообщения проигнорированы."
            )
        else:
            logger.info("В чате пока нет сообщений.")

        logger.info("=" * 60)
        logger.info("Бот готов к работе! Он работает в НЕВИДИМОМ режиме и ожидает сообщений.")
        logger.info("=" * 60)

        self.is_running = True

    async def _is_in_app(self) -> bool:
        """Проверяет, загрузился ли основной интерфейс мессенджера."""
        if not self.page:
            return False
        try:
            return await self.page.evaluate("""() => {
                const text = document.body.innerText || '';
                return text.includes('Чаты') || text.includes('Избранное') || document.querySelector('.contenteditable') !== null;
            }""")
        except Exception:
            return False

    async def _open_chat(self, chat_name: str):
        """Находит и открывает чат 'Избранное'."""
        logger.info(f"Открытие чата '{chat_name}'...")
        await self.page.wait_for_timeout(1000)

        # Проверяем, открыт ли уже чат (кнопка прикрепления видна)
        attach_btn = self.page.locator('button:has(svg use[href="#icon_attachment"])')
        if await attach_btn.count() > 0:
            logger.info("Чат уже открыт.")
            return

        chat_loc = self.page.locator(f"text='{chat_name}'").first
        if await chat_loc.count() > 0:
            await chat_loc.click()
            await self.page.wait_for_timeout(1500)
            logger.info(f"Чат '{chat_name}' успешно открыт.")
        else:
            logger.warning(f"Не удалось найти элемент с текстом '{chat_name}'.")

    async def send_webp_card(self, webp_path: Path):
        """
        Отправляет сгенерированный WebP файл в открытый чат через меню вложений.
        """
        webp_path = Path(webp_path).resolve()
        if not webp_path.exists():
            raise FileNotFoundError(f"Файл {webp_path} не найден!")

        logger.info(f"Отправка карточки {webp_path.name} в чат...")
        self.is_uploading = True

        try:
            # Запоминаем хеш отправляемой карточки, чтобы бот гарантированно игнорировал её
            try:
                self.known_bot_hashes.add(hashlib.sha256(webp_path.read_bytes()).hexdigest())
            except Exception:
                pass

            start_max = await self._get_current_max_index() or 0

            # 1. Нажимаем кнопку скрепки (вложение)
            attach_btn = self.page.locator('button:has(svg use[href="#icon_attachment"])').first
            await attach_btn.click()
            await self.page.wait_for_timeout(400)

            # 2. Выбираем пункт "Фото или видео" через перехват диалога файлов
            async with self.page.expect_file_chooser() as fc_info:
                await self.page.locator("text='Фото или видео'").click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(webp_path))

            # 3. Ожидаем появления предпросмотра
            await self.page.wait_for_timeout(800)

            # 4. Нажимаем Enter для отправки
            await self.page.keyboard.press("Enter")
            await self.page.wait_for_timeout(1000)

            # Fallback: клик по кнопке "Отправить"
            await self.page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button'));
                for (const b of btns) {
                    const t = (b.innerText || '').toLowerCase();
                    const a = (b.getAttribute('aria-label') || '').toLowerCase();
                    if (t.includes('отправить') || a.includes('отправить')) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")

            logger.info(f"Карточка {webp_path.name} успешно отправлена в MAX!")

            # Ожидаем появления нового индекса сообщения в DOM и отмечаем его как обработанный
            for _ in range(12):
                await asyncio.sleep(0.5)
                cur_max = await self._get_current_max_index()
                if cur_max is not None and cur_max > start_max:
                    for idx in range(start_max + 1, cur_max + 1):
                        self.tracker.mark_handled(idx)
                    break
            else:
                cur_max = await self._get_current_max_index()
                if cur_max is not None:
                    self.tracker.mark_handled(cur_max)

        except Exception as e:
            logger.error(f"Ошибка при отправке WebP в чат: {e}", exc_info=True)
        finally:
            self.is_uploading = False

    async def monitor_messages(self, interval_sec: float = 1.0):
        """
        Фоновый цикл мониторинга новых сообщений по уникальным индексам (data-index).
        Поддерживает как текстовые запросы, так и прикрепленные фотографии с подписями.
        """
        logger.info("Мониторинг активен: ожидаю новых сообщений с уникальным data-index...")

        while self.is_running:
            try:
                # Если прямо сейчас идет отправка ответа — ждем
                if getattr(self, "is_uploading", False):
                    await asyncio.sleep(interval_sec)
                    continue

                new_messages = await self._get_unhandled_messages()

                for msg in new_messages:
                    idx = msg["index"]
                    text = msg["text"]
                    images = msg.get("images", [])

                    # Отмечаем индекс как обработанный
                    self.tracker.mark_handled(idx)

                    # 1. Если сообщение содержит фото от пользователя
                    if images:
                        image_bytes_list = []
                        for img_url in images:
                            try:
                                resp = await self.page.request.get(img_url, timeout=10000)
                                if resp.status == 200:
                                    image_bytes_list.append(await resp.body())
                            except Exception as err:
                                logger.warning(f"Не удалось скачать фото {img_url}: {err}")

                        # Фильтрация: отсекаем собственные WebP-карточки бота
                        filtered_bytes = []
                        for b in image_bytes_list:
                            h = hashlib.sha256(b).hexdigest()
                            if h in self.known_bot_hashes:
                                logger.info(f"Пропущена собственная карточка бота [ID {idx}] (hash: {h[:8]}).")
                                continue
                            filtered_bytes.append(b)

                        if filtered_bytes:
                            # Проверяем, есть ли осмысленный текст подписи
                            prompt = text if self._is_valid_user_prompt(text) else ""
                            if not prompt:
                                prompt = "Внимательно изучи изображение. Подробно объясни, реши или проанализируй то, что на нем представлено."

                            logger.info(f"==> НОВОЕ ФОТО С ТЕЛЕФОНА [ID {idx}] ({len(filtered_bytes)} шт.): '{prompt[:80]}'")
                            if self.on_message_callback:
                                asyncio.create_task(self.on_message_callback(prompt, filtered_bytes))
                            continue

                    # 2. Чисто текстовый вопрос
                    if text and self._is_valid_user_prompt(text):
                        logger.info(f"==> НОВЫЙ ТЕКСТОВЫЙ ВОПРОС С ТЕЛЕФОНА [ID {idx}]: '{text[:80]}'")
                        if self.on_message_callback:
                            asyncio.create_task(self.on_message_callback(text, None))

                await asyncio.sleep(interval_sec)
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(2)

    async def _get_current_max_index(self) -> Optional[int]:
        """Возвращает максимальный data-index сообщений в истории чата."""
        if not self.page:
            return None
        try:
            return await self.page.evaluate("""() => {
                const history = document.querySelector('[class*="history"]') || document.querySelector('main') || document.body;
                const items = history.querySelectorAll('[data-index]');
                let maxIdx = -1;
                items.forEach(it => {
                    const idxStr = it.getAttribute('data-index');
                    if (idxStr !== null) {
                        const idx = parseInt(idxStr, 10);
                        if (!isNaN(idx) && idx > maxIdx) {
                            maxIdx = idx;
                        }
                    }
                });
                return maxIdx >= 0 ? maxIdx : null;
            }""")
        except Exception:
            return None

    async def _get_unhandled_messages(self) -> list:
        """
        Сканирует DOM истории чата на наличие сообщений с data-index.
        Возвращает только те сообщения, чей индекс еще не был обработан трекером.
        """
        if not self.page:
            return []

        try:
            items = await self.page.evaluate("""() => {
                const history = document.querySelector('[class*="history"]') || document.querySelector('main') || document.body;
                const items = history.querySelectorAll('[data-index]');
                const res = [];
                items.forEach(it => {
                    const idxStr = it.getAttribute('data-index');
                    if (idxStr === null) return;
                    const idx = parseInt(idxStr, 10);
                    if (isNaN(idx)) return;

                    // Поиск прикрепленных изображений
                    const imgElements = Array.from(it.querySelectorAll('div.media img, button.tile img, .media img, img'));
                    const imageUrls = imgElements
                        .map(i => i.src)
                        .filter(s => s && s.startsWith('http') && !s.includes('icon') && !s.includes('avatar') && !s.includes('emoji'));

                    // Поиск текста сообщения или подписи к фото
                    const textSpan = it.querySelector('.text.svelte-1htnb3l');
                    let text = '';
                    if (textSpan) {
                        text = textSpan.innerText.trim();
                    } else if (imageUrls.length === 0) {
                        const bubble = it.querySelector('[class*="bubbleContent"]');
                        if (bubble) {
                            const clone = bubble.cloneNode(true);
                            const cloneMeta = clone.querySelector('[class*="meta"]');
                            if (cloneMeta) cloneMeta.remove();
                            text = clone.innerText.trim();
                        }
                    }

                    res.push({
                        index: idx,
                        images: imageUrls,
                        text: text
                    });
                });
                res.sort((a, b) => a.index - b.index);
                return res;
            }""")

            unhandled = [m for m in items if not self.tracker.is_handled(m["index"])]
            return unhandled
        except Exception as e:
            logger.debug(f"Ошибка при получении сообщений: {e}")
            return []

    def _is_valid_user_prompt(self, text: str) -> bool:
        """
        Проверяет, является ли текст сообщения реальным вопросом от пользователя,
        а не системной плашкой, процентами загрузки, временем или размером файлов.
        """
        clean = text.strip()
        if not clean:
            return False

        # 1. Должно содержать хотя бы одну букву (отсекает 100%, 8.44/11.13, 12:45 и т.д.)
        if not re.search(r"[a-zA-Zа-яА-ЯёЁ]", clean):
            return False

        # 2. Игнорируем размеры файлов и индикаторы передачи (КБ, МБ, KB, MB, GB)
        if re.search(r"(?:kb|mb|gb|кб|мб|гб)", clean, re.IGNORECASE):
            return False

        # 3. Игнорируем соотношения чисел (например: 8.44 / 11.13 или 8.44 к 11.13)
        if re.search(r"\d+\.?\d*\s*(?:\/|из|к|-|\\)\s*\d+\.?\d*", clean, re.IGNORECASE):
            return False

        # 4. Игнорируем время сообщений ("12:43")
        if re.match(r"^\d{1,2}:\d{2}$", clean):
            return False

        # 5. Игнорируем даты ("Сегодня", "Вчера", "9 сентября 2026")
        if re.match(r"^(?:сегодня|вчера|\d{1,2}\s+[а-я]+(?:\s+\d{4})?)$", clean, re.IGNORECASE):
            return False

        # 6. Игнорируем служебные слова и плейсхолдеры
        lower = clean.lower()
        if lower in {"скачать", "сообщение", "фото", "файл", "видео"}:
            return False
        if "сохраните" in lower or "сообщения для себя" in lower:
            return False

        return True

    async def close(self):
        """Корректное завершение работы браузера."""
        self.is_running = False
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Браузер MAX закрыт.")
