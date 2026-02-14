import asyncio
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator

from database.db_setup import async_session, init_db
from database.models import Category, SiteSetting
from sqlalchemy import select

# Инициализируем современный переводчик
translator = GoogleTranslator(source='auto', target='ru')

# ТОЧНЫЕ АДРЕСА РАЗДЕЛОВ (Синхронизировано с сайтом)
TARGET_PAGES = {
    "Електроніка": "https://exp-shop.com/electronik.html",
    "Одяг та взуття": "https://exp-shop.com/clothing.html",
    "Косметика": "https://exp-shop.com/cosmetic.html",
    "Годинники": "https://exp-shop.com/watch.html",
    "Автозапчастини": "https://exp-shop.com/autoparts.html",
    "Інше": "https://exp-shop.com/other.html"
}


async def translate_text(text: str) -> str:
    """Асинхронный перевод текста на русский язык."""
    try:
        if not text or len(text) < 3:
            return text
        # deep-translator работает синхронно, запускаем в отдельном потоке
        translated = await asyncio.to_thread(translator.translate, text)
        return translated if translated else text
    except Exception as e:
        print(f"⚠️ Ошибка перевода: {e}")
        return text


async def get_site_info(context, url):
    """Заходит на сайт магазина для получения 'паспорта' (описания)."""
    page = await context.new_page()
    try:
        # Устанавливаем таймаут 15 сек, чтобы не тормозить общую миграцию
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)

        # Ищем Meta Description
        description = await page.get_attribute('meta[name="description"]', "content")
        if not description:
            description = await page.title()

        if description:
            # Переводим на русский для 'блеска и шика'
            translated = await translate_text(description.strip())
            return translated[:180]

        return "Премиальный выбор товаров с доставкой в Украину. Высокое качество и лучшие бренды."
    except Exception:
        return "Магазин доступен для заказа через наш сервис. Гарантия качества и быстрая доставка."
    finally:
        await page.close()


async def get_clean_name(link_tag, domain):
    """Очищает название магазина, убирая мусор типа 'Shop' или 'T'."""
    img = link_tag.find('img')
    raw_name = ""
    if img:
        raw_name = img.get('alt') or img.get('title') or ""

    clean_name = raw_name.strip()

    # Если на сайте нет внятного названия, делаем его из домена
    if not clean_name or clean_name.lower() in ['shop', 'us', 'site', 'link', 't', 'index']:
        parts = domain.split('.')
        clean_name = parts[-2].capitalize() if len(parts) > 1 else parts[0].capitalize()

    return clean_name


async def scrape_and_migrate():
    print("🚀 Запуск глубокой миграции с автопереводом (Стандарт: Техконтроль)...")
    await init_db()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        catalog_page = await context.new_page()

        async with async_session() as session:
            for cat_name, url in TARGET_PAGES.items():
                print(f"\n📂 Обработка раздела: {cat_name.upper()}")

                res = await session.execute(select(Category).where(Category.name == cat_name))
                category = res.scalar_one_or_none()
                if not category:
                    category = Category(name=cat_name);
                    session.add(category);
                    await session.flush()

                try:
                    await catalog_page.goto(url, wait_until="networkidle", timeout=60000)

                    # Прокрутка для активации всех логотипов (Lazy Loading)
                    for _ in range(8):
                        await catalog_page.mouse.wheel(0, 1500)
                        await asyncio.sleep(0.7)

                    soup = BeautifulSoup(await catalog_page.content(), 'html.parser')

                    shops_added = 0
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if not href.startswith('http') or "exp-shop" in href:
                            continue

                        domain = urlparse(href).netloc.replace('www.', '')
                        if any(x in domain for x in ["facebook", "google", "instagram", "youtube", "t.me"]):
                            continue

                        # Проверка на дубликаты
                        check = await session.execute(select(SiteSetting).where(SiteSetting.domain == domain))
                        if check.scalar_one_or_none():
                            continue

                        shop_name = await get_clean_name(a, domain)
                        img = a.find('img')
                        logo = None
                        if img:
                            src = img.get('src') or img.get('data-src') or img.get('data-original')
                            if src:
                                logo = urljoin("https://exp-shop.com", src)

                        print(f"   🔎 Анализ и перевод для: {shop_name}...")
                        description = await get_site_info(context, href)

                        new_shop = SiteSetting(
                            category_id=category.id,
                            name=shop_name,
                            domain=domain,
                            url=href,
                            logo_url=logo,
                            description=description
                        )
                        session.add(new_shop)
                        shops_added += 1

                        # Сохраняем порциями
                        if shops_added % 5 == 0:
                            await session.commit()

                    print(f"📈 Итог по {cat_name}: +{shops_added} магазинов")
                    await session.commit()

                except Exception as e:
                    print(f"❌ Сбой в {cat_name}: {e}")

        await browser.close()
    print("\n✨ Миграция по стандартам техконтроля завершена!")


if __name__ == "__main__":
    asyncio.run(scrape_and_migrate())