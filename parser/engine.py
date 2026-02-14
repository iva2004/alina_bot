import asyncio
import re
import json
import logging
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup


async def get_product_info(url, price_selector=None):
    """
    Усиленный парсер: Сохранены ВСЕ ваши блоки + добавлены специфические калибровки.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Эмуляция (Ваш блок)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # Увеличенный таймаут (Ваш блок)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Технологическая пауза увеличена до 6с для Columbia
            await asyncio.sleep(6)

            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')

            # --- 1. Извлечение заголовка (Ваш блок) ---
            title_tag = soup.find("meta", property="og:title") or soup.find("title")
            title = title_tag["content"] if title_tag and title_tag.has_attr(
                "content") else title_tag.text if title_tag else "Назва не знайдена"

            # --- 2. Извлечение изображения (Ваш блок) ---
            image_tag = soup.find("meta", property="og:image")
            image = image_tag["content"] if image_tag else None

            # --- 3. Поиск цены (Приоритет: Специфика -> Скидка -> Обычная -> JSON -> Meta) ---
            price_raw = "0.0"

            # --- ДОПОЛНЕНИЕ: Специфика для Columbia и 6pm ---
            if "columbia.com" in url:
                # Целимся точно в блок цены, игнорируя рассрочку Klarna
                el = await page.query_selector('.price-sales .value') or await page.query_selector('.price-sales')
                if el: price_raw = await el.inner_text()

            if "6pm.com" in url:
                # Берем только текущую цену (Current Price), отсекая сумму скидки (You Save)
                el = await page.query_selector('span.price.sale') or await page.query_selector(
                    '[data-test="product-price"]')
                if el: price_raw = await el.inner_text()

            # А) Ищем селекторы скидок (Ваш блок)
            if price_raw == "0.0" or not price_raw:
                sale_selectors = [
                    'span[data-test="product-price-reduced"]',
                    '.price-new', '.special-price', '.product-price__new',
                    '.js-shoppable-price-new', 'span.price--sale'
                ]
                for selector in sale_selectors:
                    el = await page.query_selector(selector)
                    if el:
                        price_raw = await el.inner_text()
                        break

            # Б) Стандартные селекторы (Ваш блок)
            if price_raw == "0.0" or not price_raw:
                standard_selectors = [
                    'span[data-test="product-price"]',
                    '.product-price', '[data-qa="product-price"]',
                    '.price__regular', '.current-price', 'span.money'
                ]
                for selector in standard_selectors:
                    el = await page.query_selector(selector)
                    if el:
                        price_raw = await el.inner_text()
                        break

            # В) JSON-LD (Ваш блок)
            if price_raw == "0.0" or not price_raw:
                scripts = soup.find_all('script', type='application/ld+json')
                for script in scripts:
                    try:
                        data = json.loads(script.string)
                        if isinstance(data, dict):
                            offers = data.get('offers')
                            if isinstance(offers, dict):
                                price_raw = str(offers.get('price', '0.0'))
                                break
                            elif isinstance(offers, list):
                                price_raw = str(offers[0].get('price', '0.0'))
                                break
                    except:
                        continue

            # Г) Мета-теги (Ваш блок)
            if price_raw == "0.0" or not price_raw:
                meta_p = soup.find("meta", property="product:price:amount") or \
                         soup.find("meta", attrs={"name": "twitter:data1"})
                if meta_p:
                    price_raw = meta_p.get("content") or meta_p.get("value") or "0.0"

            # --- 4. Детекция валюты и очистка числа (Ваш блок + Фикс ₴) ---
            detected_currency = "USD"
            price_text_lower = str(price_raw).lower()

            if any(x in price_text_lower for x in ["грн", "uah", "₴"]) or ".ua" in url:
                detected_currency = "UAH"
            elif "€" in str(price_raw) or "eur" in price_text_lower:
                detected_currency = "EUR"
            elif "£" in str(price_raw) or "gbp" in price_text_lower:
                detected_currency = "GBP"

            # Очистка (Ваш блок)
            clean_price = "".join(re.findall(r"[\d\.,]", str(price_raw))).replace(',', '.')
            if clean_price.count('.') > 1:
                parts = clean_price.split('.')
                clean_price = "".join(parts[:-1]) + "." + parts[-1]

            return {
                "title": title.strip(),
                "price": clean_price if clean_price else "0.0",
                "currency": detected_currency,
                "image": image,
                "url": url
            }
        except Exception as e:
            return {"error": str(e)}
        finally:
            await browser.close()