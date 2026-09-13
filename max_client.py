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
        self.known_bot_image_urls: set = set()
        self._load_known_output_hashes()

    def _load_known_output_hashes(self):
        """Загружает хеши всех ранее сгенерированных карточек из output/, чтобы бот никогда не читал свои ответы."""
        if config.OUTPUT_DIR.exists():
            for p in config.OUTPUT_DIR.glob("*.webp"):
                try:
                    b = p.read_bytes()
                    self.known_bot_hashes.add(hashlib.sha256(b).hexdigest())
                    from history_manager import compute_dhash
                    dh = compute_dhash(b)
                    if dh:
                        self.tracker.add_bot_dhash(dh)
                except Exception:
                    pass
            logger.info(f"Загружено {len(self.known_bot_hashes)} хешей и {len(self.tracker.known_bot_dhashes)} dHash собственных карточек бота.")

    def _get_launch_kwargs(self) -> dict:
        kwargs = {}
        exe = config.get_chromium_executable()
        if exe:
            logger.info(f"Используется системный Chromium: {exe}")
            kwargs["executable_path"] = exe
        return kwargs

    @staticmethod
    def clean_stale_locks():
        """Очищает устаревший SingletonLock от аварийно завершенных процессов Chromium."""
        lock_file = config.USER_DATA_DIR / "SingletonLock"
        if lock_file.exists() or lock_file.is_symlink():
            try:
                target = os.readlink(lock_file) if lock_file.is_symlink() else ""
                pid = int(target.split("-")[-1]) if "-" in target else None
                if pid:
                    os.kill(pid, 0)
                    logger.warning(f"Внимание: процесс Chromium с PID {pid} всё ещё работает.")
                    return
            except (ProcessLookupError, ValueError):
                logger.info("Обнаружен устаревший SingletonLock. Очистка перед запуском...")
                for name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                    p = config.USER_DATA_DIR / name
                    if p.exists() or p.is_symlink():
                        try:
                            p.unlink()
                        except Exception:
                            pass
            except Exception:
                pass

    async def start(self):
        """Запускает браузер в невидимом режиме, при необходимости открывая видимое окно для авторизации на ПК."""
        self.clean_stale_locks()
        self.playwright = await async_playwright().start()

        # 1. Запускаем браузер в фоновом (невидимом) режиме
        logger.info(f"Запуск браузера в невидимом режиме (headless=True, профиль: {config.USER_DATA_DIR})...")
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.USER_DATA_DIR),
            headless=True,
            device_scale_factor=2,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
            **self._get_launch_kwargs(),
        )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        logger.info("Открытие https://web.max.ru...")
        await self.page.goto("https://web.max.ru", wait_until="domcontentloaded", timeout=45000)

        # 2. Проверяем, есть ли уже сохраненная авторизация (даем до 25 секунд на загрузку SPA на VDS)
        logger.info("Проверка статуса авторизации в MAX (ожидание загрузки интерфейса)...")
        is_authorized = False
        for i in range(12):
            if await self._is_in_app():
                is_authorized = True
                break
            await asyncio.sleep(2)

        # 3. Если пользователь НЕ авторизован — обрабатываем интерактивный вход
        if not is_authorized:
            logger.info("Сессия не найдена или страница долго загружается...")
            # Сохраняем отладочный скриншот страницы
            try:
                debug_screen = config.OUTPUT_DIR / "auth_failed.png"
                await self.page.screenshot(path=str(debug_screen))
                logger.info(f"Скриншот текущего состояния сохранен в: {debug_screen}")
            except Exception:
                pass

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
                logger.error(f"Скриншот экрана сохранен в: {config.OUTPUT_DIR / 'auth_failed.png'}")
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
                device_scale_factor=2,
                viewport={"width": 1280, "height": 850},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
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

        all_existing_messages = await self._get_unhandled_messages()

        if len(self.tracker.handled_signatures) == 0:
            all_sigs = [m["signature"] for m in all_existing_messages]
            self.tracker.sync_baseline(all_sigs)
            logger.info(
                f"Первичный запуск: зафиксировано {len(all_sigs)} существующих сообщений как базовые."
            )
        else:
            logger.info(
                f"Повторный запуск бота: в базе {len(self.tracker.handled_signatures)} обработанных сообщений. "
                f"Новых недавних сообщений для обработки: {len(all_existing_messages)}."
            )

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
        try:
            await chat_loc.wait_for(state="visible", timeout=15000)
            await chat_loc.click(no_wait_after=True)
            await self.page.wait_for_timeout(2000)
            logger.info(f"Чат '{chat_name}' успешно открыт.")
        except Exception as e:
            logger.warning(f"Не удалось открыть чат '{chat_name}': {e}")

    async def send_webp_card(self, webp_path: Path, card_dhash: Optional[int] = None):
        """
        Отправляет сгенерированный WebP файл в открытый чат через меню вложений
        и сразу фиксирует сигнатуру и хеш отправленного сообщения для защиты от самоответов.
        """
        webp_path = Path(webp_path).resolve()
        if not webp_path.exists():
            raise FileNotFoundError(f"Файл {webp_path} не найден!")

        logger.info(f"Отправка карточки {webp_path.name} в чат...")
        self.is_uploading = True

        try:
            # Запоминаем хеш и dHash отправляемой карточки
            try:
                raw_bytes = webp_path.read_bytes()
                self.known_bot_hashes.add(hashlib.sha256(raw_bytes).hexdigest())
                if card_dhash:
                    self.tracker.add_bot_dhash(card_dhash)
                else:
                    from history_manager import compute_dhash
                    dh = compute_dhash(raw_bytes)
                    if dh:
                        self.tracker.add_bot_dhash(dh)
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

            # 5. Ожидаем появления сообщения в DOM и отмечаем его сигнатуру как обработанную
            await asyncio.sleep(1.5)
            new_msgs = await self._get_unhandled_messages()
            for m in new_msgs:
                self.tracker.mark_handled(m["signature"])
                for img_url in m.get("images", []):
                    self.known_bot_image_urls.add(img_url)
                logger.info(f"Собственная карточка бота [ID {m.get('index')}] зафиксирована и помечена как обработанная.")

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
                    sig = msg["signature"]
                    idx = msg.get("index", 0)
                    text = msg["text"]
                    images = msg.get("images", [])

                    # Отмечаем сообщение как обработанное по сигнатуре
                    self.tracker.mark_handled(sig)

                    # 1. Если сообщение содержит фото от пользователя
                    if images:
                        image_bytes_list = []
                        for img_url in images:
                            if img_url in self.known_bot_image_urls:
                                logger.info(f"Пропущена собственная карточка бота [ID {idx}] (совпадение URL).")
                                continue
                            try:
                                resp = await self.page.request.get(img_url, timeout=10000)
                                if resp.status == 200:
                                    b = await resp.body()
                                    h = hashlib.sha256(b).hexdigest()
                                    if h in self.known_bot_hashes:
                                        logger.info(f"Пропущена собственная карточка бота [ID {idx}] (SHA256).")
                                        continue
                                    if self.tracker.is_bot_card_dhash(b):
                                        logger.info(f"Пропущена собственная карточка бота [ID {idx}] (перцептивный dHash совпал с карточкой).")
                                        continue
                                    image_bytes_list.append(b)
                            except Exception as err:
                                logger.warning(f"Не удалось скачать фото {img_url}: {err}")

                        # Если все изображения сообщения оказались собственными карточками бота
                        if not image_bytes_list:
                            continue

                        # Пользовательское фото с телефона
                        prompt = text if self._is_valid_user_prompt(text) else ""
                        log_desc = f"'{prompt[:80]}'" if prompt else "[без подписи, прямое решение]"
                        logger.info(f"==> НОВОЕ ФОТО С ТЕЛЕФОНА [ID {idx}] ({len(image_bytes_list)} шт.): {log_desc}")
                        if self.on_message_callback:
                            asyncio.create_task(self.on_message_callback(prompt, image_bytes_list))
                        continue

                    # 2. Чисто текстовый вопрос
                    if text:
                        if self._is_valid_user_prompt(text):
                            logger.info(f"==> НОВЫЙ ТЕКСТОВЫЙ ВОПРОС С ТЕЛЕФОНА [ID {idx}]: '{text[:80]}'")
                            if self.on_message_callback:
                                asyncio.create_task(self.on_message_callback(text, None))
                        else:
                            logger.info(f"Пропущено служебное сообщение/разделитель [ID {idx}]: '{text}'")

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
                const occurrences = {};

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
                    const textSpan = it.querySelector('.text.svelte-1htnb3l') || it.querySelector('[class*="text"]');
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

                    // Время сообщения
                    const metaEl = it.querySelector('.meta.svelte-1htnb3l, [class*="meta"]');
                    const timeStr = metaEl ? metaEl.innerText.trim() : '';

                    const baseKey = `${text}:::${timeStr}`;
                    const occ = (occurrences[baseKey] || 0) + 1;
                    occurrences[baseKey] = occ;

                    const signature = `${baseKey}:::${occ}:::${imageUrls.length}`;

                    res.push({
                        signature: signature,
                        index: idx,
                        images: imageUrls,
                        text: text,
                        time: timeStr
                    });
                });
                return res;
            }""")

            unhandled = [m for m in items if not self.tracker.is_handled(m["signature"])]
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

        # 1. Игнорируем чистые проценты загрузки ("100%", "45%")
        if re.fullmatch(r"^\d+([.,]\d+)?%$", clean):
            return False

        # 2. Игнорируем чистые размеры файлов (например "8.44 МБ", "2.1 КБ", "500 KB")
        if re.fullmatch(r"^\d+([.,]\d+)?\s*(?:kb|mb|gb|кб|мб|гб|b|б)$", clean, re.IGNORECASE):
            return False

        # 3. Игнорируем соотношения чисел/прогресс (например: 8.44 / 11.13 или 8.44 из 11.13)
        if re.fullmatch(r"^\d+\.?\d*\s*(?:\/|из|к|-|\\)\s*\d+\.?\d*$", clean, re.IGNORECASE):
            return False

        # 4. Игнорируем чистое время сообщений ("12:43")
        if re.fullmatch(r"^\d{1,2}:\d{2}$", clean):
            return False

        # 5. Игнорируем системные разделители дат ("Сегодня", "Вчера", "9 сентября 2026")
        if re.fullmatch(r"^(?:сегодня|вчера|\d{1,2}\s+[а-яё]+(?:\s+\d{4})?)$", clean, re.IGNORECASE):
            return False

        # 6. Игнорируем служебные слова и плейсхолдеры интерфейса
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
            try:
                await self.context.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
        logger.info("Браузер MAX закрыт.")
