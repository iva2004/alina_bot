from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import select, func
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# Импортируем всё необходимое из вашей базы данных
from database.db_setup import async_session
from database.models import Category, SiteSetting, Order
from sqlalchemy import func # Нужно добавить в импорты вверху файла
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# Карта емодзі для категорій
CATEGORY_EMOJIS = {
    "Електроніка": "💻",
    "Одяг та взуття": "👗",
    "Косметика": "💄",
    "Годинники": "⌚️",
    "Автозапчастини": "⚙️",
    "Інше": "📦",
    "default": "🛍"
}

# --- БЛОК АДМІН-ПАНЕЛІ (6 ПУНКТІВ + НАЗАД) ---
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_admin_main_kb(new_count: int = 0, promo_count: int = 0):
    # ТЕХКОНТРОЛЬ: Возвращаем ReplyKeyboardBuilder (кнопки снизу)
    builder = ReplyKeyboardBuilder()

    status_text = f"📑 Статусы ({new_count})" if new_count > 0 else "📑 Статусы"
    promo_text = f"🔥 Акции ({promo_count})"

    # --- РЯД 1: ОПЕРАТИВНОЕ УПРАВЛЕНИЕ ---
    builder.button(text=status_text)
    builder.button(text=promo_text)
    builder.button(text="🏘 Товары в наличии")  # Внесли категорию!

    # --- РЯД 2: НАСТРОЙКИ И ПАРСИНГ ---
    builder.button(text="🎯 Модерация сайтов")
    builder.button(text="💰 Курсы Валют")
    builder.button(text="✉️ Письма (Рассылка)")

    # --- РЯД 3: КОМАНДА И АНАЛИТИКА ---
    builder.button(text="👥 Список админов")
    builder.button(text="➕ Добавить админа")
    builder.button(text="📊 Статистика")

    # --- РЯД 4: ВЫХОД ---
    builder.button(text="🏠 В главное меню")

    # Настраиваем 3 колонки. Последняя кнопка (В меню) автоматически растянется,
    # если общее количество не делится на 3, или можно оставить 3-3-3-1.
    builder.adjust(3)

    return builder.as_markup(resize_keyboard=True)

def get_admin_mailing_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Письмо конкретному пользователю")
    builder.button(text="👥 Письмо всем")
    builder.button(text="⬅️ Назад в админку")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

# --- БЛОК КОРИСТУВАЧА (КАТЕГОРІЇ ТА МАГАЗИНИ) ---
async def get_categories_kb() -> InlineKeyboardMarkup:
    """Меню категорий для пользователя: показывает только те, где есть активные сайты."""
    builder = InlineKeyboardBuilder()

    async with async_session() as session:
        # 1. Получаем все категории
        result = await session.execute(select(Category))
        categories = result.scalars().all()

        for cat in categories:
            # 2. ПРОВЕРКА: есть ли в этой категории хотя бы один активный сайт?
            # Считаем количество сайтов, где category_id совпадает и is_active = True
            sites_count_stmt = await session.execute(
                select(SiteSetting)
                .where(SiteSetting.category_id == cat.id)
                .where(SiteSetting.is_active == True)
                .limit(1) # Нам достаточно найти хотя бы один
            )
            has_active_sites = sites_count_stmt.scalar_one_or_none()

            # 3. Добавляем кнопку только если нашли активные сайты
            if has_active_sites:
                emoji = CATEGORY_EMOJIS.get(cat.name, CATEGORY_EMOJIS.get("default", "🛍"))
                builder.button(
                    text=f"{emoji} {cat.name}",
                    callback_data=f"cat_{cat.id}"
                )

    builder.adjust(2)
    return builder.as_markup()


async def get_shops_grid_kb(category_id: int, only_active: bool = False):
    builder = InlineKeyboardBuilder()
    async with async_session() as session:
        # Если True — берем только ✅, если False (для админки) — берем всё
        query = select(SiteSetting).where(SiteSetting.category_id == category_id)
        if only_active:
            query = query.where(SiteSetting.is_active == True)

        result = await session.execute(query)
        shops = result.scalars().all()

    for shop in shops:
        builder.button(text=f"{shop.name}", callback_data=f"shop_{shop.id}")

    builder.adjust(2)
    builder.button(text="⬅️ Назад", callback_data="back_to_cats")
    return builder.as_markup()

def get_shop_action_kb(shop_url: str, category_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌐 Перейти на сайт", url=shop_url))
    builder.row(InlineKeyboardButton(text="⬅️ До списку брендів", callback_data=f"cat_{category_id}"))
    return builder.as_markup()


def get_final_menu_v2(is_admin: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()

    # Переименовываем кнопки для ясности
    builder.add(KeyboardButton(text="🏘 Товары в наличии"))  # Было "Товар в Магазине"
    builder.add(KeyboardButton(text="🌍 Товары из Европы и США"))  # Было "Категории"
    builder.add(KeyboardButton(text="📦 Статус заказа"))
    builder.add(KeyboardButton(text="ℹ️ О нас"))
    builder.add(KeyboardButton(text="🆘 Поддержка"))

    if is_admin:
        builder.add(KeyboardButton(text="🔐 Админ-панель"))

    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def get_admin_sites_moderation_kb(category_id: int, sites: list):
    builder = InlineKeyboardBuilder()

    # 1. Сначала добавляем две сервисные кнопки в один ряд
    builder.row(
        InlineKeyboardButton(text="✅ Включить все", callback_data=f"mass_on_{category_id}"),
        InlineKeyboardButton(text="❌ Выключить все", callback_data=f"mass_off_{category_id}")
    )

    # 2. Затем добавляем все сайты из списка
    for site in sites:
        emoji = "✅" if site.is_active else "❌"
        builder.button(
            text=f"{emoji} {site.name}",
            callback_data=f"toggle_site_{site.id}_{category_id}"
        )

    # 3. Настраиваем сетку: кнопки массового управления (row) не трогаем,
    # остальные выстраиваем по 2 в ряд
    builder.adjust(2)

    # 4. Добавляем кнопку "Назад" отдельным рядом в самый низ
    builder.row(InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="admin_content_cats"))

    return builder.as_markup()

async def get_admin_categories_kb() -> InlineKeyboardMarkup:
    """Меню категорий специально для админа (с префиксом mod_cat_)"""
    builder = InlineKeyboardBuilder()

    async with async_session() as session:
        result = await session.execute(select(Category))
        categories = result.scalars().all()

        # Если цех пуст — сообщаем об этом кнопкой
        if not categories:
            builder.button(text="❌ Категории не найдены", callback_data="none")
        else:
            for cat in categories:
                # Используем вашу карту эмодзи CATEGORY_EMOJIS
                emoji = CATEGORY_EMOJIS.get(cat.name, CATEGORY_EMOJIS.get("default", "🛍"))
                builder.button(
                    text=f"⚙️ {emoji} {cat.name}",
                    callback_data=f"mod_cat_{cat.id}"
                )

    builder.adjust(1)
    # Исправляем callback возврата, чтобы он совпадал с вашим основным меню админки
    builder.row(InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="admin_panel"))
    return builder.as_markup()

def get_admin_order_statuses_kb(new_count: int = 0, shipping_count: int = 0):
    builder = InlineKeyboardBuilder()
    statuses = [
        ("🆕 Новые", "orders_view_НОВЫЙ"),
        ("📦 На складе", "orders_view_НА_СКЛАДЕ"),
        (f"📨 Отправка ({shipping_count})", "orders_view_ОТПРАВКА"), # Новый этап
        ("🚛 В пути", "orders_view_В_ПУТИ"),
        ("✅ Завершенные", "orders_view_ЗАВЕРШЕН")
    ]
    for text, callback in statuses:
        builder.button(text=text, callback_data=callback)
    builder.adjust(1)
    return builder.as_markup()


def get_admin_sites_moderation_kb(cat_id, sites):
    builder = InlineKeyboardBuilder()

    # 1. Верхний ряд: Массовое управление (2 кнопки)
    builder.row(
        InlineKeyboardButton(text="✅ Вкл все", callback_data=f"mass_on_{cat_id}"),
        InlineKeyboardButton(text="❌ Выкл все", callback_data=f"mass_off_{cat_id}")
    )

    # 2. Сетка сайтов (будет 3 в ряд)
    for site in sites:
        status_emoji = "✅" if site.is_active else "❌"
        builder.button(
            text=f"{status_emoji} {site.name}",
            callback_data=f"manage_site_{site.id}"
        )

    # Сначала упаковываем кнопки сайтов по 3 в ряд
    builder.adjust(2, 3)  # 2 для верхних кнопок, затем по 3 для сайтов

    # 3. Кнопка возврата (отдельной строкой внизу)
    builder.row(InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="admin_content_cats"))

    return builder.as_markup()


# --- НОВЫЙ БЛОК МОНИТОРИНГА ДЛЯ ПОЛЬЗОВАТЕЛЯ ---
async def get_user_monitoring_kb(user_tg_id: int):
    async with async_session() as session:
        # 1. Сначала находим внутренний ID пользователя в таблице User
        user_stmt = await session.execute(select(User.id).where(User.tg_id == user_tg_id))
        internal_user_id = user_stmt.scalar()

        if not internal_user_id:
            return None

        # 2. Универсальная функция подсчета по статусам (с учетом пробелов)
        async def count_by_status(status_name):
            res = await session.execute(
                select(func.count(Order.id)).where(
                    Order.user_id == internal_user_id,
                    func.upper(Order.status) == status_name.upper()
                )
            )
            return res.scalar() or 0

        # Считаем данные для клиента
        c_new = await count_by_status("НОВЫЙ")
        c_way = await count_by_status("В ПУТИ")
        c_stock = await count_stat("НА СКЛАДЕ")  # Здесь мы ловим заказы для отправки
        c_done = await count_by_status("ЗАВЕРШЕН")

    builder = InlineKeyboardBuilder()
    # callback_data должна содержать нижнее подчеркивание, которое main.py превратит в пробел
    builder.button(text=f"⏳ В обработке ({c_new})", callback_data="my_orders_НОВЫЙ")
    builder.button(text=f"🚚 В пути ({c_way})", callback_data="my_orders_В_ПУТИ")
    builder.button(text=f"📦 На складе ({c_stock})", callback_data="my_orders_НА_СКЛАДЕ")
    builder.button(text=f"✅ Завершенные ({c_done})", callback_data="my_orders_ЗАВЕРШЕН")

    builder.adjust(1)
    return builder.as_markup()

