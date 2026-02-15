import asyncio
import re
import json
from playwright.async_api import async_playwright


async def get_product_info(url):
    """
    Оптимизированный парсер: высокая скорость + защита от блокировок.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Эмуляция реального пользователя
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Ускоряем загрузку: отключаем картинки и шрифты при парсинге цены
        await page.route("**/*.{png,jpg,jpeg,svg,woff,woff2}", lambda route: route.abort())

        try:
            # Переход на страницу
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            # Короткая пауза для подгрузки JS-цен (для Columbia достаточно 3-4 сек в headless режиме)
            await asyncio.sleep(4)

            # 1. Извлечение заголовка (через Meta или Title)
            title = await page.title()
            og_title = await page.get_attribute('meta[property="og:title"]', "content")
            final_title = og_title or title or "Назва не знайдена"

            # 2. Извлечение изображения
            image = await page.get_attribute('meta[property="og:image"]', "content")

            # 3. Поиск цены (Приоритетная логика)
            price_raw = None

            # --- Специфика магазинов ---
            if "columbia.com" in url:
                price_raw = await page.inner_text('.price-sales .value') or await page.inner_text('.price-sales')
            elif "6pm.com" in url:
                price_raw = await page.inner_text('span.price.sale') or await page.inner_text(
                    '[data-test="product-price"]')

            # --- Общие селекторы (если специфика не сработала) ---
            if not price_raw:
                selectors = [
                    'span[data-test*="price-reduced"]', '.price-new', '.special-price',
                    'span[data-test*="price"]', '.product-price', '.current-price', 'span.money'
                ]
                for s in selectors:
                    try:
                        el = await page.query_selector(s)
                        if el:
                            price_raw = await el.inner_text()
                            if price_raw: break
                    except:
                        continue

            # --- Поиск в JSON-LD (если селекторы подвели) ---
            if not price_raw:
                scripts = await page.query_selector_all('script[type="application/ld+json"]')
                for script in scripts:
                    try:
                        data = json.loads(await script.inner_text())
                        if isinstance(data, dict):
                            offers = data.get('offers')
                            if isinstance(offers, dict):
                                price_raw = str(offers.get('price'))
                            elif isinstance(offers, list):
                                price_raw = str(offers[0].get('price'))
                    except:
                        continue

            # 4. Детекция валюты
            detected_currency = "USD"
            price_str = str(price_raw).lower() if price_raw else ""

            if any(x in price_str for x in ["грн", "uah", "₴"]) or ".ua" in url:
                detected_currency = "UAH"
            elif "€" in price_str or "eur" in price_str:
                detected_currency = "EUR"
            elif "£" in price_str or "gbp" in price_str:
                detected_currency = "GBP"

            # 5. Чистка цены (только цифры и точка)
            clean_price = "0.0"
            if price_raw:
                # Убираем всё кроме цифр, точек и запятых
                nums = re.sub(r"[^\d\.,]", "", str(price_raw)).replace(',', '.')
                # Если точек несколько (ошибка парсинга), оставляем только последнюю
                if nums.count('.') > 1:
                    parts = nums.split('.')
                    nums = "".join(parts[:-1]) + "." + parts[-1]
                clean_price = nums if nums else "0.0"

            return {
                "title": final_title.strip(),
                "price": clean_price,
                "currency": detected_currency,
                "image": image,
                "url": url
            }

        except Exception as e:
            return {"error": f"Парсинг не удался: {str(e)}"}
        finally:
            await browser.close()
