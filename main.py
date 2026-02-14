# === 1. СИСТЕМНЫЕ И СТАНДАРТНЫЕ БИБЛИОТЕКИ ===
import asyncio
import logging
import sys
import re
import os
from datetime import datetime
from urllib.parse import urlparse
from os import getenv # Добавляем ЭТУ строку, чтобы getenv() работала напрямую

# === 2. СТОРОННИЕ БИБЛИОТЕКИ (BS4, HTTP, DOTENV) ===
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# === 3. SQLALCHEMY (РАБОТА С БАЗОЙ) ===
from sqlalchemy import (
    select, update, delete, func, text, Column, Integer,
    String, DateTime, Boolean, Float, ForeignKey, BigInteger, Text
)
from sqlalchemy.orm import relationship

# === 4. AIOGRAM (ЛОГИКА БОТА) ===
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InputMediaPhoto, TelegramObject,
    InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# === 5. ЛОКАЛЬНЫЕ МОДУЛИ ПРОЕКТА ===
from database.db_setup import init_db, async_session
from database.models import (
    Base, User, Admin, Order, Category, SiteSetting,
    GlobalSetting, Promotion, StockItem, StockCategory,
    CartItem, SupportTicket, Site
)
from parser.engine import get_product_info
from bot.keyboards import (
    get_final_menu_v2, get_categories_kb, get_shops_grid_kb,
    get_shop_action_kb, get_admin_main_kb, get_admin_categories_kb,
    get_admin_sites_moderation_kb, get_admin_mailing_kb,
    get_admin_order_statuses_kb
)

# Загрузка переменных окружения
load_dotenv()

# 2. Получаем токен
TOKEN = os.getenv("BOT_TOKEN")

# Проверка: если токена нет, бот не должен даже пытаться запускаться
if not TOKEN or ":" not in TOKEN:
    print("❌ ОШИБКА: Токен бота не найден или имеет неверный формат!")
    print(f"Текущее значение TOKEN: '{TOKEN}'") # Поможет понять, что там реально
    sys.exit(1)

# 3. Получаем ID админа
# Безопасное получение ADMIN_ID
raw_admin_id = getenv("ADMIN_ID")
ADMIN_ID = int(raw_admin_id) if raw_admin_id and raw_admin_id.isdigit() else 0


dp = Dispatcher(storage=MemoryStorage())


# --- СОСТОЯНИЯ ---
class OrderFlow(StatesGroup):
    waiting_for_details = State()
    admin_setting_usd = State()
    admin_setting_eur = State()

class OrderState(StatesGroup):
    waiting_for_url = State()
    waiting_for_category = State() # Обувь или Одежда
    waiting_for_gender = State()   # Мужское или Женское
    waiting_for_size = State()     # Выбор размера
    waiting_for_color = State()    # Цвет
    waiting_for_size_country = State()  # ДОБАВЬТЕ ЭТУ СТРОКУ 👈

class AdminSettings(StatesGroup):
    waiting_for_usd = State()
    waiting_for_eur = State()
    waiting_for_gbp = State()
    waiting_for_ask_text = State()  # <-- ДОБАВЬТЕ ЭТУ СТРОКУ
    waiting_for_mail_text = State()  # <-- ДОБАВИТЬ ЭТУ СТРОКУ
    waiting_for_new_site_url = State()  # Для ввода ссылки на новый бренд
    waiting_for_new_site_category = State()  # Выбор категории для нового сайта
    waiting_for_new_category_name = State()  # Ввод имени новой категории
    waiting_for_edit_site_name = State()  # Редактирование названия
    waiting_for_edit_site_desc = State()  # Редактирование описания
    waiting_for_ttn_search = State()
    waiting_for_proxy_url = State()  # Новое состояние

class MailingStates(StatesGroup):
    waiting_for_global_text = State()   # Текст для всех
    waiting_for_user_id = State()       # ID конкретного пользователя
    waiting_for_private_text = State()  # Текст для конкретного пользователя

class AdminStates(StatesGroup):
    waiting_for_ttn = State() # Состояние для ввода номера накладной
    waiting_for_promo_ids = State()  # Ожидание ID пользователей для рассылки
    waiting_for_promo_ids = State()  # Для рассылки "Избранным"

# ДОБАВЬТЕ ЭТИ ДВЕ СТРОКИ ЗДЕСЬ:
class SupportState(StatesGroup):
    waiting_for_support_msg = State()

# Класс для управления процессом заказа (ТТН и логистика)
class OrderProcessStates(StatesGroup):
    # Этап 3-4: Выставление счета
    waiting_for_invoice_sum = State()
    # ВОТ ЭТУ СТРОКУ НУЖНО ДОБАВИТЬ ⬇️
    waiting_for_cancel_reason = State()
    # Этап 5: Добавление трек-номера выкупа
    waiting_for_track_number = State()
    # Этап 6: Прием на склад и запрос данных
    searching_by_track = State()
    # Этап 7: Выставление счета за вес
    waiting_for_weight_sum = State()
    # Этап 8: Ввод ТТН
    waiting_for_receipt = State()  # Ожидание фото чека от клиента
    waiting_for_shipping_details = State()  # Ожидание адреса НП от клиента
    waiting_for_ttn = State()  # Ожидание ввода ТТН админом
    # Сбор данных от клиента
    waiting_for_shipping_data = State()
    waiting_for_receipt = State()  # Ожидание фото чека
    waiting_for_weight = State()  # Ожидание ввода веса админом
    waiting_for_weight = State()  # Ввод веса
    waiting_for_currency = State()  # Выбор валюты тарифа
    waiting_for_rate = State()  # Ввод самого тарифа
    waiting_for_weight_receipt = State()

# 1. Состояние для поиска
class SearchStates(StatesGroup):
    waiting_for_query = State()

class AddProductState(StatesGroup):
    waiting_for_category = State()
    waiting_for_photo = State()
    waiting_for_description = State()
    waiting_for_size = State()
    waiting_for_price = State()


# === СОСТОЯНИЯ МАГАЗИНА ===
class StockStates(StatesGroup):
    waiting_for_cat_name = State()
    waiting_for_product_cat = State()
    waiting_for_product_photo = State()
    waiting_for_product_desc = State()
    waiting_for_product_size = State()
    waiting_for_product_price = State()
    waiting_for_product_currency = State()


# === MIDDLEWARE ДЛЯ АВТО-РЕГИСТРАЦИИ ===
class RegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        tg_user = data.get("event_from_user")
        if not tg_user or tg_user.is_bot:
            return await handler(event, data)

        async with async_session() as session:
            # Проверяем наличие пользователя
            res = await session.execute(select(User).where(User.tg_id == tg_user.id))
            user = res.scalar_one_or_none()

            if not user:
                user = User(
                    tg_id=tg_user.id,
                    full_name=tg_user.full_name,
                    username=tg_user.username,
                    is_admin=False
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)

            # Сохраняем пользователя в data, чтобы он был доступен в хендлерах
            data["db_user"] = user

        return await handler(event, data)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def get_current_rate(key: str, default: float) -> float:
    async with async_session() as session:
        result = await session.execute(select(GlobalSetting).where(GlobalSetting.key == key))
        setting = result.scalar_one_or_none()
        return setting.value if setting else default


# --- ОБРАБОТЧИКИ МЕНЮ ---
@dp.message(CommandStart())
async def cmd_start(message: Message, db_user: User): # db_user прилетает сюда сам!
    if db_user.is_admin:
        await message.answer("Привет, Админ! Твоя панель готова.", reply_markup=get_admin_main_kb())
    else:
        await message.answer("Привет! Я твой помощник по покупкам.", reply_markup=get_user_main_kb())


# --- ГЛАВНОЕ МЕНЮ И КАТЕГОРИИ ---
@dp.message(CommandStart(), StateFilter("*"))
async def cmd_start(message: Message, state: FSMContext):
    # 1. Очищаем состояния (чтобы сбросить старые заказы)
    await state.clear()




    # 2. ТЕХКОНТРОЛЬ: РЕГИСТРАЦИЯ В БАЗЕ ДАННЫХ

    class RegisterCheckMiddleware(BaseMiddleware):
        async def __call__(self, handler, event, data):
            # Достаем пользователя из события (сообщения или колбэка)
            tg_user = data.get("event_from_user")
            if not tg_user:
                return await handler(event, data)

            async_session = data.get("async_session")  # Берем сессию из data

            async with async_session() as session:
                # Ищем пользователя по tg_id
                res = await session.execute(select(User).where(User.tg_id == tg_user.id))
                user = res.scalar_one_or_none()

                # Если пользователя нет — создаем его прямо сейчас
                if not user:
                    user = User(
                        tg_id=tg_user.id,
                        full_name=tg_user.full_name,
                        username=tg_user.username,
                        is_admin=False  # По умолчанию все не админы
                    )
                    session.add(user)
                    await session.commit()
                    # Перезагружаем объект, чтобы он был привязан к сессии
                    await session.refresh(user)

                # Передаем объект пользователя в хендлеры через data
                data["db_user"] = user

            return await handler(event, data)

    async with async_session() as session:
        # Ищем пользователя по tg_id
        res = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = res.scalar_one_or_none()

        # Если его нет — создаем запись
        if not user:
            new_user = User(
                tg_id=message.from_user.id,
                full_name=message.from_user.full_name,
                username=message.from_user.username,
                is_admin=False # По умолчанию не админ
            )
            session.add(new_user)
            await session.commit()
            print(f"✅ Новый пользователь {message.from_user.full_name} добавлен в БД")
        else:
            # Обновляем имя или юзернейм, если они изменились
            user.full_name = message.from_user.full_name
            user.username = message.from_user.username
            await session.commit()

    # 3. Проверяем статус администратора для клавиатуры
    admin_status = await is_admin(message.from_user.id)

    # 4. Отправляем приветствие
    await message.answer(
        f"✅ <b>МЕНЮ ОБНОВЛЕНО, {message.from_user.first_name}!</b>\n\n"
        f"Добро пожаловать в сервис доставки товаров из Европы и США.",
        reply_markup=get_final_menu_v2(is_admin=admin_status),
        parse_mode="HTML"
    )

    # 5. Предлагаем категории
    kb_cats = await get_categories_kb()
    if kb_cats.inline_keyboard:
        await message.answer("📍 <b>Выберите категорию:</b>", reply_markup=kb_cats, parse_mode="HTML")


# 1. Обработка кнопки "О нас"
@dp.message(F.text == "ℹ️ О нас")
async def about_us_handler(message: Message):
    about_text = (
        "<b>ℹ️ О нашем сервисе</b>\n"
        "───────────────────\n"
        "Мы обеспечиваем надежную доставку товаров из лучших магазинов Европы и Турции.\n\n"
        "✅ <b>Наши преимущества:</b>\n"
        "• Проверенные ссылки на бренды\n"
        "• Быстрый расчет стоимости\n"
        "• Контроль качества на каждом этапе\n\n"
        "📍 <i>Ваш надежный партнер в мире шопинга.</i>"
    )
    await message.answer(about_text, parse_mode="HTML")

# 2. Обработка кнопки "Товар в Магазине"
@dp.message(F.text == "🛍 Товар в Магазине")
async def shop_catalog_start(message: Message):
    async with async_session() as session:
        # Берем первый товар из базы
        res = await session.execute(select(StockItem).where(StockItem.is_available == True).limit(1))
        product = res.scalar_one_or_none()

    if not product:
        return await message.answer("🏘 <b>Магазин пуст.</b> Скоро здесь появятся новинки!", parse_mode="HTML")

    text = (
        f"🏷 <b>{product.description}</b>\n\n"
        f"📏 Размер: <code>{product.size}</code>\n"
        f"💰 Цена: <b>{product.price} $</b>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️", callback_data=f"shop_prev_{product.id}")
    builder.button(text="💳 КУПИТЬ", callback_data=f"shop_buy_{product.id}")
    builder.button(text="➡️", callback_data=f"shop_next_{product.id}")
    builder.adjust(3)

    await message.answer_photo(
        photo=product.photo_id,
        caption=text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


# --- ГЛАВНОЕ МЕНЮ МАГАЗИНА ---
@dp.callback_query(F.data == "admin_stock_manage")
async def admin_stock_manage(callback: CallbackQuery):
    text = "🏘 <b>Управление товарами в наличии</b>\n\nЗдесь вы можете добавлять новые позиции и управлять категориями."
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить товар", callback_data="prod_add_start")
    builder.button(text="📁 Создать категорию", callback_data="prod_cat_add")
    builder.button(text="🏠 В админку", callback_data="admin_panel")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# --- ДОБАВЛЕНИЕ КАТЕГОРИИ ---
@dp.callback_query(F.data == "prod_cat_add")
async def prod_cat_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Введите название новой категории (например: Обувь):")
    await state.set_state(StockStates.waiting_for_cat_name)
    await callback.answer()


@dp.message(StockStates.waiting_for_cat_name)
async def prod_cat_save(message: Message, state: FSMContext):
    async with async_session() as session:
        session.add(StockCategory(name=message.text))
        await session.commit()
    await message.answer(f"✅ Категория «{message.text}» создана!")
    await state.clear()


# --- ДОБАВЛЕНИЕ ТОВАРА: ШАГ 1 (Выбор категории) ---
@dp.callback_query(F.data == "prod_add_start")
async def prod_add_start(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        res = await session.execute(select(StockCategory))
        cats = res.scalars().all()

    if not cats:
        return await callback.message.answer("⚠️ Сначала создайте хотя бы одну категорию!")

    builder = InlineKeyboardBuilder()
    for c in cats:
        builder.button(text=c.name, callback_data=f"sel_cat_{c.id}")
    builder.adjust(2)

    await callback.message.answer("📍 Выберите категорию товара:", reply_markup=builder.as_markup())
    await state.set_state(StockStates.waiting_for_product_cat)


# --- ШАГ 2: ФОТО ---
@dp.callback_query(StockStates.waiting_for_product_cat, F.data.startswith("sel_cat_"))
async def prod_step_photo(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.update_data(cat_id=cat_id)
    await callback.message.answer("📸 Отправьте фото товара:")
    await state.set_state(StockStates.waiting_for_product_photo)


# --- ШАГ 3: ОПИСАНИЕ ---
@dp.message(StockStates.waiting_for_product_photo, F.photo)
async def prod_step_desc(message: Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("📝 Введите описание товара:")
    await state.set_state(StockStates.waiting_for_product_desc)


# --- ШАГ 4: РАЗМЕР ---
@dp.message(StockStates.waiting_for_product_desc)
async def prod_step_size(message: Message, state: FSMContext):
    await state.update_data(desc=message.text)
    await message.answer("📏 Введите доступные размеры:")
    await state.set_state(StockStates.waiting_for_product_size)


# --- ШАГ 5: ВВОД ЦЕНЫ ---
@dp.message(StockStates.waiting_for_product_size)
async def prod_step_price(message: Message, state: FSMContext):
    await state.update_data(size=message.text)
    await message.answer("💰 Введите стоимость товара (только число):")
    await state.set_state(StockStates.waiting_for_product_price)


# --- НОВЫЙ ШАГ 6: ВЫБОР ВАЛЮТЫ ---
@dp.message(StockStates.waiting_for_product_price)
async def prod_step_currency(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        await state.update_data(price=price)

        builder = InlineKeyboardBuilder()
        builder.button(text="₴ ГРИВНА (UAH)", callback_data="set_curr_UAH")
        builder.button(text="$ ДОЛЛАР (USD)", callback_data="set_curr_USD")
        builder.adjust(2)

        await message.answer("💱 Выберите валюту для этой цены:", reply_markup=builder.as_markup())
        await state.set_state(StockStates.waiting_for_product_currency)
    except ValueError:
        await message.answer("❌ Введите цену числом (например: 1500)")


# --- ФИНАЛ: СОХРАНЕНИЕ ---
@dp.callback_query(StockStates.waiting_for_product_currency, F.data.startswith("set_curr_"))
async def prod_final_save(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("_")[2]  # UAH или USD
    data = await state.get_data()

    async with async_session() as session:
        new_item = StockItem(
            category_id=data['cat_id'],
            photo_id=data['photo_id'],
            description=data['desc'],
            size=data['size'],
            price=data['price'],
            currency=currency  # Сохраняем выбранную валюту
        )
        session.add(new_item)
        await session.commit()

    await state.clear()
    await callback.message.answer(f"✅ Товар успешно добавлен! Цена: {data['price']} {currency}")
    await callback.answer()
    # Возвращаем в хаб
    await admin_stock_hub(callback.message, state)


# 3. Обработка кнопки "Статус заказа"
@dp.message(F.text == "📦 Статус заказа")
async def show_order_status_menu(message: Message):
    async with async_session() as session:
        # 1. Получаем ID пользователя
        user_stmt = await session.execute(
            select(User.id).where(User.tg_id == message.from_user.id)
        )
        internal_user_id = user_stmt.scalar()

        if not internal_user_id:
            await message.answer("📦 <b>У вас пока нет оформиленных заказов.</b>", parse_mode="HTML")
            return

        # 2. УНИВЕРСАЛЬНЫЙ ПОДСЧЕТ (Техконтроль: теперь считает списки статусов)
        async def get_count(status_list):
            # Переводим всё в верхний регистр для точности базы
            upper_statuses = [s.upper() for s in status_list]
            res = await session.execute(
                select(func.count(Order.id)).where(
                    Order.user_id == internal_user_id,
                    func.upper(Order.status).in_(upper_statuses)  # Ищем в списке
                )
            )
            return res.scalar() or 0

        # Считаем категории
        c_new = await get_count(["НОВЫЙ"])
        c_way = await get_count(["В ПУТИ"])

        # МАГИЯ ЗДЕСЬ: Теперь считаем и товар, и вес вместе!
        c_wait = await get_count(["ОЖИДАЕТ ОПЛАТЫ", "ОЖИДАЕТ ОПЛАТЫ ВЕСА"])

        c_stock = await get_count(["НА СКЛАДЕ"])
        c_done = await get_count(["ЗАВЕРШЕН"])

    # 3. Строим инлайн-клавиатуру
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⏳ В обработке ({c_new})", callback_data="my_orders_НОВЫЙ")

    # Кнопка теперь покажет (1), если есть хотя бы один долг (за товар или за вес)
    builder.button(text=f"💳 Неоплаченные счета ({c_wait})", callback_data="my_orders_ОЖИДАЕТ_ОПЛАТЫ")

    builder.button(text=f"🚚 В пути ({c_way})", callback_data="my_orders_В_ПУТИ")
    builder.button(text=f"📦 На складе ({c_stock})", callback_data="my_orders_НА_СКЛАДЕ")
    builder.button(text=f"✅ Завершенные ({c_done})", callback_data="my_orders_ЗАВЕРШЕН")
    builder.adjust(1)

    await message.answer(
        "🔎 <b>Мониторинг ваших заказов</b>\n"
        "───────────────────\n"
        "Выберите категорию, чтобы увидеть подробности:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# --- 1. КЛИЕНТ: Нажимает "Отправить чек" ---
@dp.callback_query(F.data.startswith("user_pay_check_"))
async def user_start_receipt_upload(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[3]
    await state.update_data(payment_order_id=order_id)
    await state.set_state(OrderProcessStates.waiting_for_receipt)

    await callback.message.answer("📸 Пожалуйста, отправьте фото или скриншот чека об оплате:")
    await callback.answer()


# --- 3. АДМИН (ВЫ): Подтверждение оплаты ---
@dp.callback_query(F.data.startswith("adm_pay_ok_"))
async def admin_confirm_payment(callback: CallbackQuery, bot: Bot):
    # Извлекаем ID заказа
    oid = int(callback.data.split("_")[3])

    async with async_session() as session:
        # 1. Загружаем заказ из базы
        order = await session.get(Order, oid)

        # 2. МЕНЯЕМ СТАТУС (теперь он точно совпадет со счетчиком в меню)
        order.status = "ЖДЕТ ТРЕК"

        # 3. ФИКСИРУЕМ ИЗМЕНЕНИЯ (без этого счетчик не обновится!)
        session.add(order)
        await session.commit()

        # Получаем данные клиента для уведомления
        user_res = await session.execute(select(User).where(User.id == order.user_id))
        user_data = user_res.scalar()

    # 4. ОБНОВЛЯЕМ ИНТЕРФЕЙС АДМИНА
    await callback.message.edit_reply_markup(reply_markup=None)  # Убираем кнопки, чтобы не жать повторно
    await callback.message.answer(
        f"💳 Оплата заказа №{oid} подтверждена!\n"
        f"Заказ перемещен в категорию 'ЖДУТ ТРЕК'.\n"
        f"Теперь введите трек-номер через меню статусов."
    )

    # 5. УВЕДОМЛЯЕМ КЛИЕНТА
    if user_data:
        await bot.send_message(
            user_data.tg_id,
            f"✅ <b>Ваша оплата №{oid} принята!</b>\n\n"
            f"Товар выкуплен. Ожидайте доставку товара на склад.",
            parse_mode="HTML"
        )
    await callback.answer("Статус обновлен!")


# --- 4. АДМИН (ВЫ): Отклонение оплаты ---
@dp.callback_query(F.data.startswith("adm_pay_bad_"))
async def admin_reject_payment(callback: CallbackQuery, bot: Bot):
    oid = int(callback.data.split("_")[3])

    async with async_session() as session:
        order = await session.get(Order, oid)
        user_res = await session.execute(select(User).where(User.id == order.user_id))
        user_tg_id = user_res.scalar().tg_id

    await bot.send_message(user_tg_id,
                           f"⚠️ <b>Проблема с оплатой заказа №{oid}</b>\nВаш чек не прошел проверку. Пожалуйста, свяжитесь с админом или отправьте верный чек.")

    await callback.message.edit_caption(caption=f"❌ Чек по заказу №{oid} ОТКЛОНЕН")
    await callback.answer("Чек отклонен")

#---Админ-панель---
# Функция получения курса из базы данных
async def get_rate(key: str, default: float = 0.0) -> float:
    async with async_session() as session:
        result = await session.execute(
            select(GlobalSetting.value).where(GlobalSetting.key == key)
        )
        val = result.scalar()
        return float(val) if val is not None else default

@dp.callback_query(F.data.startswith("mass_"))
async def admin_mass_toggle_sites(callback: CallbackQuery):
    # Разбираем сигнал: mass_on_ID или mass_off_ID
    action = callback.data.split("_")[1]  # "on" или "off"
    cat_id = int(callback.data.split("_")[2])

    new_status = True if action == "on" else False

    async with async_session() as session:
        # Обновляем статус всех сайтов в этой категории одним запросом
        await session.execute(
            update(SiteSetting)
            .where(SiteSetting.category_id == cat_id)
            .values(is_active=new_status)
        )
        await session.commit()

        # Получаем обновленный список для перерисовки меню
        result = await session.execute(
            select(SiteSetting).where(SiteSetting.category_id == cat_id)
        )
        sites = result.scalars().all()

    # Обновляем клавиатуру
    from bot.keyboards import get_admin_sites_moderation_kb
    await callback.message.edit_reply_markup(
        reply_markup=get_admin_sites_moderation_kb(cat_id, sites)
    )

    msg = "Все сайты включены ✅" if new_status else "Все сайты скрыты ❌"
    await callback.answer(msg)


# Обработка нажатия на кнопку "Изменить курс"
@dp.callback_query(F.data.startswith("set_rate_"))
async def set_rate_init(callback: CallbackQuery, state: FSMContext):
    rate_key = callback.data.replace("set_rate_", "")
    await state.update_data(rate_to_change=rate_key)

    await callback.message.answer(f"⌨️ Введите новый курс (используйте точку, например 42.5):")
    await state.set_state(AdminSettings.waiting_for_usd)  # Используем ваше существующее состояние
    await callback.answer()


# Универсальный обработчик для входа в меню курсов
@dp.callback_query(F.data == "admin_rates")
@dp.message(F.text == "💰 Курсы Валют") # ИСПРАВЛЕНО: добавлена поддержка кнопки с мешком денег
async def admin_rates_menu(event: types.CallbackQuery | types.Message):
    # Если это нажатие инлайн-кнопки, убираем "часики"
    if isinstance(event, types.CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    # Получаем актуальные данные из базы (используем ваши функции get_rate)
    usd = await get_rate("usd_rate", 42.0)
    eur = await get_rate("eur_rate", 45.5)
    gbp = await get_rate("gbp_rate", 53.0)

    text = (
        f"📊 <b>Управление курсами валют</b>\n\n"
        f"🇺🇸 USD: <code>{usd}</code> грн\n"
        f"🇪🇺 EUR: <code>{eur}</code> грн\n"
        f"🇬🇧 GBP: <code>{gbp}</code> грн\n\n"
        f"<i>Выберите валюту для изменения:</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🇺🇸 Изменить USD", callback_data="set_rate_usd_rate")
    builder.button(text="🇪🇺 Изменить EUR", callback_data="set_rate_eur_rate")
    builder.button(text="🇬🇧 Изменить GBP", callback_data="set_rate_gbp_rate")
    builder.button(text="⬅️ Назад в админку", callback_data="admin_panel")
    builder.adjust(1)

    # Логика отображения: редактируем или шлем новое сообщение
    try:
        if isinstance(event, types.CallbackQuery):
            await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception as e:
        # На случай, если сообщение нельзя редактировать (например, оно слишком старое)
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# 3. Сохранение значения (ИСПРАВЛЕНО: убраны дубли, добавлено немедленное обновление)
# Хендлер записи нового курса в базу
@dp.message(AdminSettings.waiting_for_usd)
async def process_new_rate(message: Message, state: FSMContext):
    new_value = message.text.replace(",", ".").strip()

    try:
        val = float(new_value)
    except ValueError:
        await message.answer("⚠️ Ошибка! Введите число (например: 41.9)")
        return

    data = await state.get_data()
    key = data.get("rate_to_change")

    async with async_session() as session:
        # Обновляем или создаем запись в GlobalSetting
        stmt = select(GlobalSetting).where(GlobalSetting.key == key)
        res = await session.execute(stmt)
        setting = res.scalar_one_or_none()

        if setting:
            setting.value = val
        else:
            session.add(GlobalSetting(key=key, value=val))

        await session.commit()

    await message.answer(f"✅ Курс обновлен до <b>{val}</b>", parse_mode="HTML")
    await state.clear()
    # Возвращаем админа в меню курсов
    await admin_rates_menu(message)  # Вызываем функцию выше (только подправьте её под message)


# Вспомогательная функция для обновления экрана после записи
async def admin_rates_refresh(message: Message):
    # Используем вашу функцию get_rate для получения свежих данных
    usd = await get_rate("usd_rate", 42.0)
    eur = await get_rate("eur_rate", 45.5)
    gbp = await get_rate("gbp_rate", 53.0)

    text = (
        f"⚙️ <b>Актуальные курсы в системе:</b>\n\n"
        f"🇺🇸 USD: <code>{usd}</code> грн\n"
        f"🇪🇺 EUR: <code>{eur}</code> грн\n"
        f"🇬🇧 GBP: <code>{gbp}</code> грн"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🛠 Вернуться в админку", callback_data="admin_panel")

    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


## Исправленный и полный обработчик возврата в админку
@dp.callback_query(F.data == "admin_panel")
async def back_to_admin_menu(callback: CallbackQuery):
    await callback.answer()

    async with async_session() as session:
        # 1. Считаем новые заказы
        res_orders = await session.execute(
            select(func.count(Order.id)).where(func.upper(Order.status) == "НОВЫЙ")
        )
        new_count = res_orders.scalar() or 0

        # 2. Считаем активные акции (вызываем функцию, которую создали ранее)
        promo_count = await get_promo_count(session)

    text = (
        f"🛠 <b>Панель управления:</b>\n"
        f"Новых заказов: <b>{new_count}</b>\n"
        f"Активных акций: <b>{promo_count}</b>"
    )

    # ПЕРЕДАЕМ ОБА СЧЕТЧИКА
    kb = get_admin_main_kb(new_count=new_count, promo_count=promo_count)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        # Если сообщение нельзя отредактировать, шлем новое
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


# --- 1. ВЫВОД СПИСКА АКЦИЙ И УПРАВЛЕНИЕ ---
# Пример (проверьте ваш путь к папке с моделями!)
from database.models import User, Order, Site, Promotion


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ТЕХКОНТРОЛЬ: ДОБАВЛЕНО) ---

async def is_admin(tg_id: int) -> bool:
    """Проверяет, является ли пользователь админом"""
    if tg_id == ADMIN_ID: return True
    async with async_session() as session:
        res = await session.execute(select(Admin).where(Admin.tg_id == tg_id))
        return res.scalar_one_or_none() is not None


async def get_promo_count(session) -> int:
    """Считает количество активных акций"""
    res = await session.execute(select(func.count(Promotion.id)).where(Promotion.is_active == True))
    return res.scalar() or 0


# --- ГЛАВНЫЙ СКАНЕР АКЦИЙ (ДИНАМИЧЕСКИЙ) ---
# Функция для вызова меню прокси (можно добавить кнопку в admin_panel)
@dp.callback_query(F.data == "admin_proxy_menu")
async def admin_proxy_menu(callback: CallbackQuery):
    async with async_session() as session:
        # Получаем статус и URL из базы
        res_status = await session.execute(select(GlobalSetting).where(GlobalSetting.key == "proxy_enabled"))
        status_setting = res_status.scalar_one_or_none()
        is_on = status_setting.value == 1.0 if status_setting else False

        res_url = await session.execute(select(GlobalSetting).where(GlobalSetting.key == "proxy_url"))
        url_setting = res_url.scalar_one_or_none()
        # Если прокси сохранен как строка в value, выводим его
        current_proxy = url_setting.value if url_setting else "Не установлен"

    text = (
        f"🌐 <b>УПРАВЛЕНИЕ ПРОКСИ</b>\n"
        f"───────────────────\n"
        f"Текущий статус: {'✅ <b>ВКЛЮЧЕН</b>' if is_on else '❌ <b>ВЫКЛЮЧЕН</b>'}\n"
        f"Адрес: <code>{current_proxy}</code>\n"
        f"───────────────────\n"
        f"<i>Без прокси такие сайты как Victoria's Secret выдают ошибку 403.</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Включить", callback_data="proxy_on")
    builder.button(text="❌ Выключить", callback_data="proxy_off")
    builder.button(text="⌨️ Изменить адрес", callback_data="proxy_set_input")
    builder.button(text="🏠 В админку", callback_data="admin_panel")
    builder.adjust(2, 1, 1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# --- ВКЛЮЧЕНИЕ / ВЫКЛЮЧЕНИЕ ---
@dp.callback_query(F.data.in_(["proxy_on", "proxy_off"]))
async def proxy_toggle(callback: CallbackQuery):
    new_val = 1.0 if callback.data == "proxy_on" else 0.0
    async with async_session() as session:
        stmt = insert(GlobalSetting).values(key="proxy_enabled", value=new_val)
        stmt = stmt.on_conflict_do_update(index_elements=['key'], set_=dict(value=new_val))
        await session.execute(stmt)
        await session.commit()

    await callback.answer(f"Прокси {'включен' if new_val == 1.0 else 'выключен'}")
    await admin_proxy_menu(callback)


# --- ЗАПРОС АДРЕСА ---
@dp.callback_query(F.data == "proxy_set_input")
async def proxy_input_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSettings.waiting_for_proxy_url)
    await callback.message.answer(
        "⌨️ <b>Введите данные прокси в формате:</b>\n"
        "<code>http://user:password@ip:port</code>\n\n"
        "<i>Или просто ip:port, если прокси без пароля.</i>",
        parse_mode="HTML"
    )
    await callback.answer()


# --- СОХРАНЕНИЕ АДРЕСА ---
@dp.message(AdminSettings.waiting_for_proxy_url)
async def proxy_save(message: Message, state: FSMContext):
    # 1. ЗАЩИТА: Если вместо прокси пришел текст кнопки меню
    if message.text.startswith("🏠") or message.text.startswith("⬅️"):
        await state.clear()
        return await message.answer("❌ Настройка прокси отменена.",
                                    reply_markup=get_admin_main_kb(0, 0))  # Укажите ваши счетчики

    proxy_text = message.text.strip()

    # Валидация: проверим, что это хотя бы похоже на адрес
    if "." not in proxy_text:
        return await message.answer("⚠️ Это не похоже на адрес. Введите в формате <code>ip:port</code>")

    if "http" not in proxy_text:
        proxy_text = f"http://{proxy_text}"

    async with async_session() as session:
        # 2. ПРАВИЛЬНАЯ ЗАПИСЬ: пишем в value_str, а не в числовое value
        stmt = insert(GlobalSetting).values(key="proxy_url", value_str=proxy_text)
        stmt = stmt.on_conflict_do_update(
            index_elements=['key'],
            set_=dict(value_str=proxy_text)
        )
        await session.execute(stmt)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Прокси успешно сохранен в текстовое поле базы.")
    await admin_promo_hub(message, state)  # Возврат в хаб


async def run_promo_scanner():
    """
    Сканер акций: проверяет активные сайты из таблицы SiteSetting.
    Поддерживает опциональное использование прокси из настроек базы данных.
    """
    async with async_session() as session:
        # 1. ПОЛУЧАЕМ НАСТРОЙКИ ПРОКСИ ИЗ БАЗЫ (GlobalSetting)
        # Ищем статус (включен/выключен) - тут используем .value (число)
        res_proxy_on = await session.execute(
            select(GlobalSetting).where(GlobalSetting.key == "proxy_enabled")
        )
        proxy_setting = res_proxy_on.scalar_one_or_none()
        is_proxy_active = proxy_setting.value == 1.0 if proxy_setting else False

        # Ищем сам адрес прокси
        res_proxy_url = await session.execute(
            select(GlobalSetting).where(GlobalSetting.key == "proxy_url")
        )
        url_setting = res_proxy_url.scalar_one_or_none()

        # ТЕХКОНТРОЛЬ: Берем адрес из value_str, чтобы не было ошибки конвертации в float
        proxy_address = url_setting.value_str if url_setting else None

        # Формируем объект прокси для requests
        proxies = None
        if is_proxy_active and proxy_address and "http" in str(proxy_address):
            proxies = {
                "http": proxy_address,
                "https": proxy_address
            }
            print(f"🌐 [SCANNER] Прокси ВКЛЮЧЕН: {proxy_address}")
        else:
            print("⚠️ [SCANNER] Прокси ВЫКЛЮЧЕН или не задан. Работаю напрямую.")

        # 2. ПОЛУЧАЕМ СПИСОК САЙТОВ ДЛЯ ПРОВЕРКИ
        stmt = select(SiteSetting).where(
            SiteSetting.is_active.in_([True, 1]),
            SiteSetting.url != None,
            SiteSetting.url != ""
        )
        result = await session.execute(stmt)
        active_items = result.scalars().all()

    if not active_items:
        print("🔎 [SCANNER] Нет активных сайтов с URL для сканирования.")
        return []

    print(f"🚀 [SCANNER] Запуск проверки {len(active_items)} сайтов...")
    found_promos = []

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.google.com/'
    }

    # 3. ЦИКЛ ОБХОДА САЙТОВ
    for item in active_items:
        try:
            response = requests.get(
                item.url,
                headers=headers,
                proxies=proxies,
                timeout=20,
                verify=False
            )

            print(f"📡 Сайт: {item.name:15} | Статус: {response.status_code}")

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                page_content = soup.get_text().upper()
                keywords = ["SALE", "OFF", "DISCOUNT", "CLEARANCE", "%", "АКЦИЯ", "СКИДКИ", "ПРОДАЖ"]

                if any(word in page_content for word in keywords):
                    found_promos.append({
                        "site": item.name,
                        "title": f"🔥 Найдена распродажа на {item.name}!",
                        "url": item.url
                    })
                    print(f"✅ НАЙДЕНО: {item.name}")

            elif response.status_code == 403:
                print(f"🚫 {item.name}: Доступ заблокирован (нужен другой прокси).")

        except Exception as e:
            print(f"❌ Ошибка {item.name}: {str(e)[:50]}...")

    return found_promos


# --- ЗАПУСК СКАНЕРА ИЗ АДМИНКИ ---
async def admin_promo_list(message: Message):
    async with async_session() as session:
        # Берем все активные акции, новые сверху
        res = await session.execute(
            select(Promotion)
            .where(Promotion.is_active == True)
            .order_by(Promotion.created_at.desc())
        )
        promos = res.scalars().all()

    if not promos:
        return  # Если пусто, ничего не шлем (Хаб уже всё сказал)

    for p in promos:
        text = f"📍 <b>Сайт: {p.site_name}</b>\n📢 {p.title}\n🔗 <a href='{p.url}'>Открыть сайт</a>"

        builder = InlineKeyboardBuilder()
        builder.button(text="🌍 Всем", callback_data=f"promo_broadcast_all_{p.id}")
        builder.button(text="💎 ТОП-10", callback_data=f"promo_broadcast_top_{p.id}")
        builder.button(text="👤 Избранным", callback_data=f"promo_broadcast_select_{p.id}")
        builder.button(text="🗑 Удалить", callback_data=f"promo_delete_{p.id}")
        builder.adjust(2, 1, 1)

        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=False)


# 1. Функция вывода списка (вспомогательная)
async def admin_show_all_promos(message: Message):
    async with async_session() as session:
        # Берем активные акции, новые в начале
        res = await session.execute(
            select(Promotion)
            .where(Promotion.is_active == True)
            .order_by(Promotion.created_at.desc())
        )
        promos = res.scalars().all()

    for p in promos:
        text = (
            f"📍 <b>Сайт: {p.site_name}</b>\n"
            f"📢 {p.title}\n"
            f"🔗 <a href='{p.url}'>Открыть сайт</a>"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="🌍 Всем", callback_data=f"promo_broadcast_all_{p.id}")
        builder.button(text="💎 ТОП-10", callback_data=f"promo_broadcast_top_{p.id}")
        builder.button(text="👤 Избранным", callback_data=f"promo_broadcast_select_{p.id}")
        builder.button(text="🗑 Удалить", callback_data=f"promo_delete_{p.id}")
        builder.adjust(2, 1, 1)

        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=False)


# 2. ГЛАВНЫЙ ХЕНДЛЕР (исправлен синтаксис)
@dp.message(F.text.startswith("🔥 Акции"), StateFilter("*"))
async def admin_promo_hub(message: Message, state: FSMContext):
    await state.clear()

    async with async_session() as session:
        # Считаем количество активных акций для текста
        count_res = await session.execute(
            select(func.count(Promotion.id)).where(Promotion.is_active == True)
        )
        total = count_res.scalar() or 0

    welcome_text = (
        "🔥 <b>Центр управления акциями</b>\n\n"
        "Здесь собраны распродажи, найденные на зарубежных сайтах.\n"
        "Вы можете запустить поиск вручную или настроить прокси.\n\n"
        f"📊 <i>Сейчас в базе активных акций: {total}</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Запустить поиск (Вручную)", callback_data="admin_run_scanner_manual")
    # ДОБАВЛЕНА КНОПКА УПРАВЛЕНИЯ ПРОКСИ
    builder.button(text="🌐 Настройка прокси", callback_data="admin_proxy_menu")
    builder.button(text="🏠 В админку", callback_data="admin_panel")

    # Делаем кнопки в столбик для удобства
    builder.adjust(1)

    await message.answer(welcome_text, reply_markup=builder.as_markup(), parse_mode="HTML")

    # Если акции есть — выводим список карточек
    if total > 0:
        await admin_show_all_promos(message)

@dp.callback_query(F.data == "admin_run_scanner_manual")
async def admin_run_scanner_manual(callback: CallbackQuery, state: FSMContext):
    # 1. Моментальный ответ, чтобы Telegram не выдавал ошибку таймаута
    await callback.answer("🚀 Поиск запущен...")

    # 2. Сообщение о прогрессе
    status_msg = await callback.message.answer(
        "⏳ <b>Начинаю сканирование 9 сайтов...</b>\n<i>Это может занять до 30-40 секунд.</i>",
        parse_mode="HTML"
    )

    # 3. Запуск парсера (ваша функция run_promo_scanner)
    found_items = await run_promo_scanner()
    new_added = 0

    # 4. Сохранение результатов
    async with async_session() as session:
        if found_items:
            for item in found_items:
                # Проверка по ссылке, чтобы не дублировать
                exists = await session.execute(select(Promotion).where(Promotion.url == item['url']))
                if not exists.scalar():
                    session.add(Promotion(
                        site_name=item['site'],
                        title=item['title'],
                        url=item['url'],
                        is_active=True
                    ))
                    new_added += 1
            await session.commit()

        # Получаем данные для обновления меню
        p_res = await session.execute(select(func.count(Promotion.id)).where(Promotion.is_active == True))
        p_total = p_res.scalar() or 0
        o_res = await session.execute(select(func.count(Order.id)).where(func.upper(Order.status) == "НОВЫЙ"))
        o_new = o_res.scalar() or 0

    # 5. Итоговый отчет
    await status_msg.edit_text(
        f"✅ <b>Сканирование завершено!</b>\n"
        f"Добавлено новых: <b>{new_added}</b>\n"
        f"Всего актуальных в базе: <b>{p_total}</b>",
        parse_mode="HTML"
    )

    # 6. Обновляем главное меню админа
    new_kb = get_admin_main_kb(new_count=o_new, promo_count=p_total)
    await callback.message.answer("Обновленное меню админ-панели:", reply_markup=new_kb)

    # 7. Выводим список карточек акций
    await admin_show_all_promos(callback.message)


# --- УДАЛЕНИЕ АКЦИИ ---
@dp.callback_query(F.data.startswith("promo_delete_"))
async def delete_promo_handler(callback: CallbackQuery):
    promo_id = int(callback.data.split("_")[2])

    async with async_session() as session:
        # 1. Удаляем (или деактивируем) акцию
        promo = await session.get(Promotion, promo_id)
        if promo:
            await session.delete(promo)
            await session.commit()

        # 2. ПЕРЕРАСЧЕТ: Считаем актуальные данные для клавиатуры
        p_count = await get_promo_count(session)
        o_res = await session.execute(select(func.count(Order.id)).where(func.upper(Order.status) == "НОВЫЙ"))
        n_orders = o_res.scalar() or 0

    # 3. Удаляем само сообщение с акцией
    await callback.message.delete()

    # 4. ОБНОВЛЯЕМ ГЛАВНОЕ МЕНЮ (отправляем новое с верным счетчиком)
    await callback.message.answer(
        f"🗑 Акция удалена. Обновлено количество: <b>{p_count}</b>",
        reply_markup=get_admin_main_kb(new_count=n_orders, promo_count=p_count),
        parse_mode="HTML"
    )
    await callback.answer("Удалено!")


# --- РАССЫЛКА АКЦИИ ---
@dp.callback_query(F.data.startswith("promo_broadcast_"))
async def handle_promo_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    parts = callback.data.split("_")
    action = parts[2]  # all, top или select
    promo_id = int(parts[3])

    async with async_session() as session:
        promo = await session.get(Promotion, promo_id)
        if not promo:
            return await callback.answer("❌ Акция не найдена")

        target_tg_ids = []
        label = ""

        # 1. Сценарий: Рассылка ВСЕМ
        if action == "all":
            res = await session.execute(select(User.tg_id))
            target_tg_ids = res.scalars().all()
            label = "всем пользователям"

        # 2. Сценарий: ТОП-10 активных (по количеству заказов)
        elif action == "top":
            stmt = (
                select(User.tg_id)
                .join(Order, User.id == Order.user_id)
                .where(Order.status == "ЗАВЕРШЕН")
                .group_by(User.id)
                .order_by(func.count(Order.id).desc())
                .limit(10)
            )
            res = await session.execute(stmt)
            target_tg_ids = res.scalars().all()
            label = "ТОП-10 активным клиентам"

        # 3. Сценарий: ИЗБРАННЫМ (Новая логика с кнопками)
        elif action == "select":
            # Ищем 10 последних уникальных клиентов, делавших заказы
            stmt = (
                select(User)
                .join(Order, User.id == Order.user_id)
                .order_by(Order.created_at.desc())
                .distinct()
                .limit(10)
            )
            res = await session.execute(stmt)
            recent_users = res.scalars().all()

            builder = InlineKeyboardBuilder()

            if recent_users:
                for u in recent_users:
                    # Кнопка для моментальной отправки конкретному клиенту
                    builder.button(
                        text=f"👤 {u.full_name or 'Клиент'}",
                        callback_data=f"promo_direct_{promo_id}_{u.tg_id}"
                    )

            # Всегда добавляем кнопку ручного ввода ID
            builder.button(text="⌨️ Ввести ID вручную", callback_data=f"promo_manual_{promo_id}")
            builder.adjust(1)

            await callback.message.answer(
                "🎯 <b>Выберите получателя из списка последних активных:</b>\n"
                "Или нажмите кнопку ниже, чтобы ввести ID вручную.",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            return await callback.answer()

    # --- ЗАПУСК МАССОВОЙ РАССЫЛКИ (для "all" и "top") ---
    if not target_tg_ids:
        return await callback.answer("📭 Некому отправлять (список пуст)", show_alert=True)

    await callback.answer(f"🚀 Начинаю рассылку {label}...")

    # Используем ваш вспомогательный движок рассылки
    success_count = await run_mass_broadcast(target_tg_ids, promo, bot)

    await callback.message.answer(
        f"✅ <b>Рассылка завершена!</b>\nДоставлено: {success_count} из {len(target_tg_ids)} адресатов.",
        parse_mode="HTML"
    )


# --- 2. ОБРАБОТЧИК ВВОДА ID ДЛЯ "ИЗБРАННЫХ" ---
@dp.message(AdminStates.waiting_for_promo_ids)
async def process_manual_promo_broadcast(message: Message, state: FSMContext, bot: Bot):
    import re
    # Достаем ID акции из памяти
    data = await state.get_data()
    promo_id = data.get("promo_id_to_send")

    # Собираем все числа из сообщения (это будут ID)
    target_tg_ids = [int(i) for i in re.findall(r'\d+', message.text)]

    if not target_tg_ids:
        return await message.answer("❌ Введите хотя бы один числовой ID!")

    async with async_session() as session:
        promo = await session.get(Promotion, promo_id)

    if not promo:
        await state.clear()
        return await message.answer("❌ Акция не найдена в базе.")

    await message.answer(f"🚀 Начинаю ручную рассылку для {len(target_tg_ids)} чел...")

    success_count = await run_mass_broadcast(target_tg_ids, promo, bot)

    await message.answer(f"✅ <b>Готово!</b>\nДоставлено: {success_count} чел.", parse_mode="HTML")
    await state.clear()


# --- 3. ФУНКЦИЯ-ДВИЖОК РАССЫЛКИ (чтобы всё было в одном месте) ---
async def run_mass_broadcast(target_ids, promo, bot):
    count = 0
    promo_text = f"🔥 <b>СПЕЦПРЕДЛОЖЕНИЕ!</b>\n\n{promo.title}\n\n🔗 <a href='{promo.url}'>УСПЕЙТЕ КУПИТЬ</a>"

    for uid in target_ids:
        try:
            if promo.image_url:
                await bot.send_photo(uid, promo.image_url, caption=promo_text, parse_mode="HTML")
            else:
                await bot.send_message(uid, promo_text, parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05)  # Защита от спам-фильтра Telegram
        except:
            continue
    return count


@dp.callback_query(F.data.startswith("promo_manual_"))
async def process_manual_input_start(callback: CallbackQuery, state: FSMContext):
    promo_id = int(callback.data.split("_")[2])

    await state.set_state(AdminStates.waiting_for_promo_ids)
    await state.update_data(promo_id_to_send=promo_id)

    await callback.message.answer("⌨️ Введите ID пользователя (цифрами):")
    await callback.answer()


@dp.callback_query(F.data.startswith("promo_direct_"))
async def process_direct_promo_send(callback: CallbackQuery, bot: Bot):
    # Разбираем callback: promo_direct_АКЦИЯ_ЮЗЕР
    parts = callback.data.split("_")
    promo_id = int(parts[2])
    target_tg_id = int(parts[3])

    async with async_session() as session:
        promo = await session.get(Promotion, promo_id)

    if not promo:
        return await callback.answer("❌ Акция не найдена", show_alert=True)

    # Формируем текст
    promo_text = f"🔥 <b>ПЕРСОНАЛЬНОЕ ПРЕДЛОЖЕНИЕ!</b>\n\n{promo.title}\n\n🔗 <a href='{promo.url}'>ПОСМОТРЕТЬ</a>"

    try:
        if promo.image_url:
            await bot.send_photo(target_tg_id, promo.image_url, caption=promo_text, parse_mode="HTML")
        else:
            await bot.send_message(target_tg_id, promo_text, parse_mode="HTML")

        await callback.answer("✅ Отправлено!", show_alert=False)
        # Помечаем кнопку как "отправленную", чтобы не запутаться
        await callback.message.edit_text(f"✅ Акция успешно отправлена клиенту (ID: {target_tg_id})")
    except Exception as e:
        await callback.answer(f"❌ Ошибка отправки: {e}", show_alert=True)

@dp.message(AdminStates.waiting_for_promo_ids)
async def process_select_broadcast(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    promo_id = data.get("promo_id_to_send")

    # 1. Парсим ID из текста (убираем запятые и лишние пробелы)
    import re
    input_text = message.text or ""
    # Ищем все последовательности цифр (ID пользователей)
    target_ids = re.findall(r'\d+', input_text)

    if not target_ids:
        return await message.answer(
            "❌ Я не нашел в сообщении ID пользователей. Попробуйте еще раз или нажмите /cancel.")

    async with async_session() as session:
        promo = await session.get(Promotion, promo_id)

    if not promo:
        await state.clear()
        return await message.answer("❌ Ошибка: акция больше не существует.")

    # 2. Запускаем рассылку
    await message.answer(f"🚀 Начинаю отправку для {len(target_ids)} пользователей...")

    success = 0
    promo_text = f"🔥 <b>ПЕРСОНАЛЬНОЕ ПРЕДЛОЖЕНИЕ!</b>\n\n{promo.title}\n\n🔗 <a href='{promo.url}'>КУПИТЬ СО СКИДКОЙ</a>"

    for uid in target_ids:
        try:
            if promo.image_url:
                await bot.send_photo(uid, promo.image_url, caption=promo_text, parse_mode="HTML")
            else:
                await bot.send_message(uid, promo_text, parse_mode="HTML")
            success += 1
        except:
            continue

    await message.answer(f"✅ <b>Готово!</b>\nАкция доставлена {success} пользователям из {len(target_ids)}.")
    await state.clear()


async def start_mass_send(callback, target_ids, promo, bot):
    if not target_ids:
        return await callback.answer("📭 Список получателей пуст", show_alert=True)

    await callback.answer("🚀 Рассылка запущена...")
    success = 0
    promo_text = f"🔥 <b>СПЕЦПРЕДЛОЖЕНИЕ!</b>\n\n{promo.title}\n\n🔗 <a href='{promo.url}'>УСПЕЙТЕ КУПИТЬ</a>"

    for uid in target_ids:
        try:
            if promo.image_url:
                await bot.send_photo(uid, promo.image_url, caption=promo_text, parse_mode="HTML")
            else:
                await bot.send_message(uid, promo_text, parse_mode="HTML")
            success += 1
        except:
            continue

    await callback.message.answer(f"✅ Рассылка завершена. Доставлено: {success}")

@dp.callback_query(F.data.startswith("promo_send_"))
async def handle_promo_broadcast(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    action = parts[2]  # all, top или select
    promo_id = int(parts[3])

    async with async_session() as session:
        promo = await session.get(Promotion, promo_id)
        if not promo: return

        target_users = []

        if action == "all":
            # Рассылка всем
            res = await session.execute(select(User.tg_id))
            target_users = res.scalars().all()

        elif action == "top":
            # ТОП-10 по количеству завершенных заказов
            stmt = (
                select(User.tg_id)
                .join(Order)
                .where(Order.status == "ЗАВЕРШЕН")
                .group_by(User.id)
                .order_by(func.count(Order.id).desc())
                .limit(10)
            )
            res = await session.execute(stmt)
            target_users = res.scalars().all()

    # Запуск процесса рассылки
    count = 0
    promo_text = f"🔥 <b>ГОРЯЧАЯ РАСПРОДАЖА!</b>\n\n{promo.title}\n\n🔗 <a href='{promo.url}'>УСПЕЙ КУПИТЬ</a>"

    for uid in target_users:
        try:
            if promo.image_url:
                await bot.send_photo(uid, promo.image_url, caption=promo_text, parse_mode="HTML")
            else:
                await bot.send_message(uid, promo_text, parse_mode="HTML")
            count += 1
        except:
            continue

    await callback.message.answer(f"✅ Рассылка завершена! Получателей: {count}")
    await callback.answer()

@dp.callback_query(F.data.startswith("promo_send_"))
async def handle_promo_broadcast(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    action = parts[2]  # all, top или select
    promo_id = int(parts[3])

    async with async_session() as session:
        promo = await session.get(Promotion, promo_id)
        if not promo: return

        target_users = []

        if action == "all":
            # Рассылка всем
            res = await session.execute(select(User.tg_id))
            target_users = res.scalars().all()

        elif action == "top":
            # ТОП-10 по количеству завершенных заказов
            stmt = (
                select(User.tg_id)
                .join(Order)
                .where(Order.status == "ЗАВЕРШЕН")
                .group_by(User.id)
                .order_by(func.count(Order.id).desc())
                .limit(10)
            )
            res = await session.execute(stmt)
            target_users = res.scalars().all()

    # Запуск процесса рассылки
    count = 0
    promo_text = f"🔥 <b>ГОРЯЧАЯ РАСПРОДАЖА!</b>\n\n{promo.title}\n\n🔗 <a href='{promo.url}'>УСПЕЙ КУПИТЬ</a>"

    for uid in target_users:
        try:
            if promo.image_url:
                await bot.send_photo(uid, promo.image_url, caption=promo_text, parse_mode="HTML")
            else:
                await bot.send_message(uid, promo_text, parse_mode="HTML")
            count += 1
        except:
            continue

    await callback.message.answer(f"✅ Рассылка завершена! Получателей: {count}")
    await callback.answer()


@dp.message(F.text == "📊 Статистика", StateFilter("*"))
async def show_admin_stats(message: Message):
    # Вызываем общую логику (вынесена отдельно, чтобы работала кнопка "Назад")
    await send_main_stats(message)

# Вспомогательная функция для отрисовки главной статистики
async def send_main_stats(message_or_callback):
    async with async_session() as session:
        # Считаем данные
        all_orders = await session.execute(select(func.count(Order.id)))
        done_orders = await session.execute(select(func.count(Order.id)).where(Order.status == "ЗАВЕРШЕН"))
        total_money = await session.execute(select(func.sum(Order.price_uah)).where(Order.status == "ЗАВЕРШЕН"))
        total_users = await session.execute(select(func.count(User.id)))

        money = total_money.scalar() or 0
        all_c = all_orders.scalar() or 0
        done_c = done_orders.scalar() or 0
        users = total_users.scalar() or 0
        rate = round((done_c / all_c * 100), 1) if all_c > 0 else 0

    text = (
        f"📊 <b>ФИНАНСОВАЯ СТАТИСТИКА</b>\n"
        f"───────────────────\n"
        f"💰 <b>Общая выручка:</b> {money} грн\n"
        f"✅ <b>Завершено заказов:</b> {done_c}\n"
        f"📈 <b>Всего заказов в базе:</b> {all_c}\n"
        f"👥 <b>Всего клиентов:</b> {users}\n"
        f"───────────────────\n"
        f"🏆 <b>Эффективность:</b> {rate}%"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Детально за месяц", callback_data="stats_month")
    builder.button(text="🏆 ТОП-10 клиентов", callback_data="stats_top_users") # ТЕПЕРЬ ОНА ТУТ
    builder.button(text="🏠 В админку", callback_data="admin_panel")
    builder.adjust(1)

    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


from sqlalchemy import text  # Убедитесь, что этот импорт есть в самом верху!


@dp.callback_query(F.data == "stats_top_users")
async def show_top_users(callback: CallbackQuery):
    async with async_session() as session:
        # 1. Формируем запрос
        stmt = (
            select(
                User.full_name,
                User.tg_id,
                func.count(Order.id).label("cnt"),
                func.sum(Order.price_uah).label("total_sum")  # Добавили сумму, как вы хотели
            )
            .join(Order, User.id == Order.user_id)
            .where(Order.status == "ЗАВЕРШЕН")
            .group_by(User.id)
            .order_by(text("cnt DESC"))  # Используем функцию SQLAlchemy
            .limit(10)
        )
        res = await session.execute(stmt)
        top = res.all()

    # 2. ТЕХКОНТРОЛЬ: переименовали переменную в response_text, чтобы не было ошибки
    response_text = "🏆 <b>ТОП-10 КЛИЕНТОВ (ПО ЗАКАЗАМ)</b>\n\n"

    if not top:
        response_text += "<i>Пока нет завершенных заказов.</i>"
    else:
        for i, user in enumerate(top, 1):
            name = user.full_name or f"ID: {user.tg_id}"
            # Выводим количество заказов и сумму
            response_text += f"{i}. <b>{name}</b> — {user.cnt} зак. ({int(user.total_sum or 0)} грн)\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin_stats_back")
    builder.adjust(1)

    await callback.message.edit_text(response_text, reply_markup=builder.as_markup(), parse_mode="HTML")

from datetime import datetime

@dp.callback_query(F.data == "stats_month")
async def show_monthly_stats(callback: CallbackQuery):
    # 1. Определяем временные границы (текущий месяц)
    now = datetime.now()
    start_of_month = datetime(now.year, now.month, 1)

    async with async_session() as session:
        # 2. Считаем деньги за завершенные заказы месяца
        stmt_money = select(func.sum(Order.price_uah)).where(
            Order.status == "ЗАВЕРШЕН",
            Order.created_at >= start_of_month
        )
        # 3. Считаем общее количество новых заказов за месяц
        stmt_count = select(func.count(Order.id)).where(
            Order.created_at >= start_of_month
        )
        # 4. Считаем количество успешно закрытых за месяц
        stmt_done = select(func.count(Order.id)).where(
            Order.status == "ЗАВЕРШЕН",
            Order.created_at >= start_of_month
        )

        res_money = await session.execute(stmt_money)
        res_count = await session.execute(stmt_count)
        res_done = await session.execute(stmt_done)

        money = res_money.scalar() or 0
        all_c = res_count.scalar() or 0
        done_c = res_done.scalar() or 0

    # Названия месяцев для красоты
    months = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
        7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }
    month_name = months.get(now.month, "Месяц")

    text = (
        f"📅 <b>ИТОГИ ЗА {month_name.upper()}</b>\n"
        f"───────────────────\n"
        f"💰 <b>Выручка за месяц:</b> <code>{money}</code> грн\n"
        f"📦 <b>Всего новых заказов:</b> {all_c}\n"
        f"✅ <b>Успешно закрыто:</b> {done_c}\n"
        f"───────────────────\n"
        f"<i>Данные за период с {start_of_month.strftime('%d.%m.%Y')}</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад к статистике", callback_data="admin_stats_back")
    builder.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ХЕНДЛЕР ДЛЯ КНОПКИ НАЗАД
@dp.callback_query(F.data == "admin_stats_back")
async def back_to_stats_handler(callback: CallbackQuery):
    await callback.answer()
    # Просто вызываем функцию отрисовки главной статистики
    await send_main_stats(callback)



# 1. Обработчик для текстовой кнопки "🏠 В главное меню" (ReplyKeyboard)
# 1. Обработчик для текстовой кнопки "🏠 В главное меню"
@dp.message(F.text == "🏠 В главное меню")
async def back_to_user_menu_text(message: Message, state: FSMContext):
    # 1. Сбрасываем все состояния FSM (особенно важно после админ-панели)
    await state.clear()

    # 2. Проверяем, является ли пользователь админом, чтобы вернуть кнопку "Админ-панель"
    # Это удобно для вашего iPhone 13, чтобы быстро переключаться
    is_admin_user = await is_admin(message.from_user.id)

    # 3. Отправляем полноценное меню (get_final_menu_v2 уже импортирована вверху файла)
    await message.answer(
        "🏠 Вы вернулись в <b>главное меню</b>.\nВсе функции магазина снова доступны.",
        reply_markup=get_final_menu_v2(is_admin=is_admin_user),
        parse_mode="HTML"
    )

# 2. На всякий случай добавим обработчик для CALLBACK (если такая кнопка есть в инлайне)
@dp.callback_query(F.data == "go_to_user_menu")
async def back_to_user_menu_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "🏠 Возврат в <b>главное меню</b>...",
        reply_markup=get_main_kb(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_orders")
async def show_admin_orders(callback: CallbackQuery):
    async with async_session() as session:
        # Берем только новые заказы
        result = await session.execute(select(Order).where(Order.status == 'new'))
        orders = result.scalars().all()

    if not orders:
        await callback.answer("Новых заказов пока нет")
        return

    for order in orders:
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Выкуплено", callback_data=f"status_{order.id}_paid")
        builder.button(text="❌ Отмена", callback_data=f"status_{order.id}_cancel")

        await callback.message.answer(
            f"📦 Заказ №{order.id}\nСумма: {order.total_price} грн",
            reply_markup=builder.as_markup()
        )


@dp.callback_query(F.data == "admin_new_orders")
async def show_new_orders_admin(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(
            select(Order).where(Order.status == "NEW").order_by(Order.created_at.desc())
        )
        new_orders = result.scalars().all()

    if not new_orders:
        await callback.message.edit_text("✅ <b>Все заказы обработаны!</b>", parse_mode="HTML")
        return

    text = f"📥 <b>Список необработанных заказов ({len(new_orders)} шт):</b>\n\n"
    for o in new_orders:
        text += (f"🆔 Заказ №{o.id}\n"
                 f"👤 Клиент ID: {o.user_id}\n"
                 f"🏷 {o.title}\n"
                 f"💰 {o.price_uah} грн\n"
                 f"───────────────────\n")
    # Здесь функция заказов заканчивается. Больше внутри неё ничего быть не должно!
    await callback.message.answer(text, parse_mode="HTML")

# --- А ТЕПЕРЬ ФУНКЦИИ МОДЕРАЦИИ (ОНИ СТОЯТ ОТДЕЛЬНО, С КРАЯ) ---
# 1. Вход в выбор категории (теперь и по кнопке, и по callback)
# --- БЛОК: МОДЕРАЦИЯ И УПРАВЛЕНИЕ БРЕНДАМИ ---

# 1. Вход в меню модерации (Текстовая кнопка или возврат через Callback)
@dp.message(F.text == "🎯 Модерация сайтов")
@dp.callback_query(F.data == "admin_content_cats")
async def admin_content_categories(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()

    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    if not await is_admin(event.from_user.id):
        return

    # Получаем кнопки существующих категорий
    kb = await get_admin_categories_kb()

    builder = InlineKeyboardBuilder()
    builder.attach(InlineKeyboardBuilder.from_markup(kb))

    # --- ВОТ ЭТОТ БЛОК МЫ ДОБАВЛЯЕМ ---
    builder.row(
        InlineKeyboardButton(text="➕ Добавить бренд", callback_data="add_site_start"),
        InlineKeyboardButton(text="🗑 Удалить категорию", callback_data="admin_delete_cat_start")
    )
    # ----------------------------------

    text = "🎯 <b>Панель модерации</b>\nУправляйте брендами или очистите лишние категории:"

    if isinstance(event, CallbackQuery):
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# 2. Начало процесса добавления нового сайта
@dp.callback_query(F.data == "add_site_start")
async def add_site_init(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "🔗 <b>Добавление нового бренда</b>\n\n"
        "Пришлите ссылку на главную страницу (URL).\n"
        "<i>Пример: https://www.nike.com</i>",
        parse_mode="HTML"
    )
    await state.set_state(AdminSettings.waiting_for_new_site_url)


# 3. Обработка ссылки, парсинг домена и иконки, сохранение
# 1. Приняли ссылку -> Переходим к выбору категории
@dp.message(AdminSettings.waiting_for_new_site_url)
async def process_new_site_url(message: Message, state: FSMContext):
    url = message.text.strip().lower()
    if not url.startswith("http"):
        return await message.answer("❌ Ссылка должна начинаться с http")

    # Временно сохраняем URL в память FSM
    await state.update_data(new_site_url=url)

    # Показываем выбор категорий + "Создать новую"
    async with async_session() as session:
        res = await session.execute(select(Category).order_by(Category.name))
        categories = res.scalars().all()

    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.button(text=cat.name, callback_data=f"set_cat_for_new_{cat.id}")
    builder.button(text="➕ Создать новую категорию", callback_data="create_new_cat_flow")
    builder.adjust(2)

    await message.answer("📁 <b>Выберите категорию для сайта:</b>", reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(AdminSettings.waiting_for_new_site_category)


# 2. Финальное сохранение сайта (после выбора категории)
@dp.callback_query(F.data.startswith("set_cat_for_new_"))
async def finalize_site_addition(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    url = data['new_site_url']

    try:
        domain = urlparse(url).netloc.replace('www.', '')
        site_name = domain.split('.')[0].capitalize()
        logo_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

        async with async_session() as session:
            # Получаем имя категории для сообщения
            cat_obj = await session.get(Category, cat_id)

            new_site = SiteSetting(
                name=site_name, url=url, logo_url=logo_url,
                category_id=cat_id, is_active=True,
                description=f"Магазин {site_name}"
            )
            session.add(new_site)
            await session.commit()

        await callback.message.edit_text(
            f"✅ <b>Бренд добавлен!</b>\n🏷 <b>Название:</b> {site_name}\n📂 <b>Категория:</b> {cat_obj.name}",
            parse_mode="HTML"
        )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await state.clear()

# 4. Обработчик списка сайтов в категории (старый, проверенный блок)
# --- БЛОК МОДЕРАЦИИ: СОРТИРОВКА И УПРАВЛЕНИЕ ---

# 1. Список сайтов с сортировкой А-Я
@dp.callback_query(F.data.startswith("mod_cat_"))
async def admin_mod_sites_list(callback: CallbackQuery):
    await callback.answer()
    cat_id = int(callback.data.split("_")[-1])

    async with async_session() as session:
        # ТЕХКОНТРОЛЬ: Сортировка по имени
        result = await session.execute(
            select(SiteSetting)
            .where(SiteSetting.category_id == cat_id)
            .order_by(SiteSetting.name)  # Вот здесь включается сортировка
        )
        sites = result.scalars().all()

    kb = get_admin_sites_moderation_kb(cat_id, sites)
    await callback.message.edit_text(
        "🔧 <b>Настройка брендов</b>\nНажмите на название сайта для управления им:",
        reply_markup=kb,
        parse_mode="HTML"
    )


# 2. МЕНЮ УПРАВЛЕНИЯ КОНКРЕТНЫМ САЙТОМ (Правка/Удаление)
@dp.callback_query(F.data.startswith("manage_site_"))
async def admin_manage_single_site(callback: CallbackQuery):
    await callback.answer()
    site_id = int(callback.data.split("_")[-1])

    async with async_session() as session:
        site = await session.get(SiteSetting, site_id)

    if not site:
        return await callback.message.answer("❌ Сайт не найден в базе.")

    text = (
        f"🛠 <b>Управление брендом: {site.name}</b>\n"
        f"───────────────────\n"
        f"📝 <b>Описание:</b> {site.description}\n"
        f"📊 <b>Статус:</b> {'✅ Активен' if site.is_active else '❌ Скрыт'}\n"
        f"🔗 <b>URL:</b> {site.url}"
    )

    builder = InlineKeyboardBuilder()
    # Кнопка переключения статуса (Toggle)
    status_text = "❌ Выключить" if site.is_active else "✅ Включить"
    builder.button(text=status_text, callback_data=f"toggle_site_{site.id}_{site.category_id}")

    builder.button(text="✏️ Изменить название", callback_data=f"edit_name_{site.id}")
    builder.button(text="🗑 УДАЛИТЬ САЙТ", callback_data=f"del_site_{site.id}")
    builder.button(text="⬅️ Назад к списку", callback_data=f"mod_cat_{site.category_id}")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# 3. ФУНКЦИЯ УДАЛЕНИЯ (Техконтроль: полное удаление из БД)
@dp.callback_query(F.data.startswith("del_site_"))
async def delete_site_handler(callback: CallbackQuery):
    site_id = int(callback.data.split("_")[-1])

    async with async_session() as session:
        site = await session.get(SiteSetting, site_id)
        if site:
            cat_id = site.category_id
            name = site.name
            await session.delete(site)
            await session.commit()
            await callback.answer(f"✅ Сайт {name} удален", show_alert=True)

            # ВАЖНО: Вместо подмены callback.data, просто заново получаем список
            result = await session.execute(
                select(SiteSetting)
                .where(SiteSetting.category_id == cat_id)
                .order_by(SiteSetting.name)
            )
            sites = result.scalars().all()
            kb = get_admin_sites_moderation_kb(cat_id, sites)
            await callback.message.edit_text("🔧 <b>Настройка брендов</b>:", reply_markup=kb, parse_mode="HTML")


# 1. Начало редактирования
@dp.callback_query(F.data.startswith("edit_name_"))
async def edit_site_name_init(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    site_id = int(callback.data.split("_")[-1])
    await state.update_data(edit_site_id=site_id)

    await callback.message.answer("⌨️ <b>Введите новое название для бренда:</b>", parse_mode="HTML")
    await state.set_state(AdminSettings.waiting_for_edit_site_name)


# 2. Сохранение нового названия
@dp.message(AdminSettings.waiting_for_edit_site_name)
async def process_edit_site_name(message: Message, state: FSMContext):
    new_name = message.text.strip()
    data = await state.get_data()
    site_id = data.get("edit_site_id")

    async with async_session() as session:
        site = await session.get(SiteSetting, site_id)
        if site:
            site.name = new_name
            await session.commit()
            await message.answer(f"✅ Название успешно изменено на <b>{new_name}</b>", parse_mode="HTML")
        else:
            await message.answer("❌ Ошибка: сайт не найден.")

    await state.clear()


# 1. Начало создания категории
@dp.callback_query(F.data == "create_new_cat_flow")
async def admin_create_category_init(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "📝 <b>Введите название новой категории:</b>\nНапример: <i>Аксессуары</i> или <i>Парфюмерия</i>",
        parse_mode="HTML")
    await state.set_state(AdminSettings.waiting_for_new_category_name)


# 2. Сохранение новой категории в базу
@dp.message(AdminSettings.waiting_for_new_category_name)
async def admin_create_category_save(message: Message, state: FSMContext):
    cat_name = message.text.strip()

    if len(cat_name) < 2:
        return await message.answer("❌ Название слишком короткое. Введите нормальное имя:")

    async with async_session() as session:
        # Проверяем, нет ли уже такой категории
        existing = await session.execute(select(Category).where(Category.name == cat_name))
        if existing.scalar_one_or_none():
            await message.answer("⚠️ Такая категория уже существует!")
            await state.clear()
            return

        # Добавляем новую
        new_cat = Category(name=cat_name)
        session.add(new_cat)
        await session.commit()
        await session.refresh(new_cat)
        new_id = new_cat.id

    await message.answer(f"✅ Категория <b>{cat_name}</b> создана!", parse_mode="HTML")

    # Сразу предлагаем привязать сайт к этой новой категории, если мы в процессе добавления
    data = await state.get_data()
    if 'new_site_url' in data:
        # Если мы попали сюда из процесса добавления сайта, завершаем его
        await state.update_data(selected_cat_id=new_id)
        # Имитируем нажатие кнопки выбора категории, чтобы сработал finalize_site_addition
        callback_mock = types.CallbackQuery(
            id="0", from_user=message.from_user, chat_instance="0",
            message=message, data=f"set_cat_for_new_{new_id}"
        )
        await finalize_site_addition(callback_mock, state)
    else:
        await state.clear()


# 1. Хендлер для вызова режима удаления (добавим кнопку в основное меню модерации)
@dp.callback_query(F.data == "admin_delete_cat_start")
async def admin_delete_category_list(callback: CallbackQuery):
    await callback.answer()

    async with async_session() as session:
        res = await session.execute(select(Category).order_by(Category.name))
        categories = res.scalars().all()

    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.button(text=f"🗑 {cat.name}", callback_data=f"confirm_del_cat_{cat.id}")

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_content_cats"))

    await callback.message.edit_text(
        "🗑 <b>Режим удаления категорий</b>\n\n"
        "Выберите категорию, которую нужно удалить. <b>Внимание:</b> категорию можно удалить только если она пуста.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


# 2. Логика удаления категории
@dp.callback_query(F.data.startswith("confirm_del_cat_"))
async def admin_delete_category_process(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[-1])

    async with async_session() as session:
        # Проверяем наличие сайтов в этой категории
        site_check = await session.execute(select(SiteSetting).where(SiteSetting.category_id == cat_id))
        if site_check.scalars().first():
            return await callback.answer("❌ Нельзя удалить: в категории есть сайты! Сначала удалите или перенесите их.",
                                         show_alert=True)

        category = await session.get(Category, cat_id)
        if category:
            name = category.name
            await session.delete(category)
            await session.commit()
            await callback.answer(f"✅ Категория '{name}' удалена")
            # Возвращаемся к списку категорий
            await admin_delete_category_list(callback)


@dp.callback_query(F.data.startswith("toggle_site_"))
async def admin_toggle_site(callback: CallbackQuery):
    # Разбираем callback: toggle_site_ID_CATID
    _, _, site_id, cat_id = callback.data.split("_")

    async with async_session() as session:
        site = await session.get(SiteSetting, int(site_id))
        if site:
            site.is_active = not site.is_active
            await session.commit()

            result = await session.execute(
                select(SiteSetting).where(SiteSetting.category_id == int(cat_id))
            )
            sites = result.scalars().all()

            from bot.keyboards import get_admin_sites_moderation_kb
            await callback.message.edit_reply_markup(
                reply_markup=get_admin_sites_moderation_kb(int(cat_id), sites)
            )
            await callback.answer(f"Статус изменен!")

# Вставьте это перед хендлерами админ-панели
async def get_promo_count(session):
    # ТЕХКОНТРОЛЬ: считаем только те акции, которые админ еще не удалил или не скрыл
    res = await session.execute(
        select(func.count(Promotion.id)).where(Promotion.is_active == True)
    )
    return res.scalar() or 0


# Универсальный хендлер: вход в статусы по кнопке с текстом ИЛИ по callback
@dp.message(F.text.startswith("📑 Статусы"), StateFilter("*"))
@dp.callback_query(F.data == "admin_order_statuses_kb")
@dp.message(F.text.startswith("📑 Статусы"), StateFilter("*"))
@dp.callback_query(F.data == "admin_order_statuses_kb")
async def admin_statuses_main(event: Message | CallbackQuery, state: FSMContext):
    # Очищаем состояния, чтобы кнопки меню работали всегда
    await state.clear()

    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    if not await is_admin(event.from_user.id):
        return

    async with async_session() as session:
        # Универсальная функция для точного подсчета
        async def get_count(status_names):
            if isinstance(status_names, str):
                status_names = [status_names]

            upper_names = [s.upper() for s in status_names]
            res = await session.execute(
                select(func.count(Order.id)).where(
                    func.upper(Order.status).in_(upper_names)
                )
            )
            return res.scalar() or 0

        # Считаем количество активных акций (из новой таблицы promotions)
        c_promo = await get_promo_count(session)

        # Считаем данные по заказам
        c_new = await get_count("НОВЫЙ")
        c_unpaid = await get_count(["ОЖИДАЕТ ОПЛАТЫ", "ОЖИДАЕТ ОПЛАТЫ ВЕСА"])
        c_paid_no_track = await get_count("ЖДЕТ ТРЕК")
        c_way = await get_count("В ПУТИ")
        c_stock = await get_count("НА СКЛАДЕ")
        c_ready = await get_count("ОЖИДАЕТ ОТПРАВКИ")
        c_done = await get_count("ЗАВЕРШЕН")

    builder = InlineKeyboardBuilder()

    # Сетка кнопок
    builder.button(text="🔍 Поиск по ТТН / Треку", callback_data="search_by_ttn")

    # Новая кнопка для управления акциями
    builder.button(text=f"🔥 Акции ({c_promo})", callback_data="admin_promo_list")

    builder.button(text=f"📥 Новые ({c_new})", callback_data="orders_view_НОВЫЙ")
    builder.button(text=f"💳 Неоплаченные ({c_unpaid})", callback_data="orders_view_ОЖИДАЕТ_ОПЛАТЫ")
    builder.button(text=f"📨 Ждут трек ({c_paid_no_track})", callback_data="orders_view_ЖДЕТ_ТРЕК")
    builder.button(text=f"🚚 В пути ({c_way})", callback_data="orders_view_В_ПУТИ")
    builder.button(text=f"📦 На складе ({c_stock})", callback_data="orders_view_НА_СКЛАДЕ")
    builder.button(text=f"🚀 Готовы к отправке ({c_ready})", callback_data="orders_view_ОЖИДАЕТ_ОТПРАВКИ")
    builder.button(text=f"✅ Завершены ({c_done})", callback_data="orders_view_ЗАВЕРШЕН")

    builder.button(text="🏠 В админку", callback_data="admin_panel")

    builder.adjust(1)

    text = "📑 <b>Управление статусами заказов</b>\n\nВыберите категорию для контроля:"

    try:
        if isinstance(event, CallbackQuery):
            await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# Ловим ID пользователя и проверяем его
@dp.message(MailingStates.waiting_for_user_id)
async def process_mailing_user_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Ошибка: ID должен состоять только из цифр. Попробуйте еще раз:")

    await state.update_data(target_user_id=message.text)
    await state.set_state(MailingStates.waiting_for_private_text)
    await message.answer(f"ID {message.text} принят. Теперь введите текст сообщения:")


@dp.message(F.text == "✉️ Письма (Рассылка)")
async def admin_mailing_menu(message: Message):
    # Используем вашу функцию проверки по базе данных
    if not await is_admin(message.from_user.id):
        return

    await message.answer(
        "📩 <b>Меню рассылки</b>\nВыберите тип отправки:",
        reply_markup=get_admin_mailing_kb(),
        parse_mode="HTML"
    )

# --- БЛОК РАССЫЛКИ (ТЕХКОНТРОЛЬ) ---

# 1. Вход в режим "Письмо конкретному"
@dp.message(F.text == "👤 Письмо конкретному пользователю")
async def start_private_mailing(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return

    async with async_session() as session:
        # Берем всех пользователей из базы
        result = await session.execute(select(User))
        users = result.scalars().all()

    if not users:
        return await message.answer("Пользователей пока нет в базе.")

    builder = InlineKeyboardBuilder()

    for user in users:
        # Формируем текст на кнопке: Имя или фамилия, если нет — ID
        name = user.full_name or f"ID: {user.tg_id}"
        # В callback_data кладем ID, чтобы потом его вытащить
        builder.button(text=name, callback_data=f"mail_to_{user.tg_id}")

    # Делаем сетку в 3 столбца
    builder.adjust(3)
    # Добавляем кнопку отмены внизу
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_mailing"))

    await state.set_state(MailingStates.waiting_for_user_id)
    await message.answer(
        "👤 <b>Письмо конкретному пользователю</b>\n\nВыберите получателя из списка ниже:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


# Хендлер для текстовой кнопки "⬅️ Назад в админку"
@dp.message(F.text == "⬅️ Назад в админку")
async def back_to_admin_mailing(message: Message):
    # Используем вашу функцию проверки по базе данных
    if not await is_admin(message.from_user.id):
        return

    await message.answer("🔙 Возврат в админ-панель", reply_markup=get_admin_main_kb())

# Хендлер нажатия на кнопку с именем пользователя
@dp.callback_query(F.data.startswith("mail_to_"), MailingStates.waiting_for_user_id)
async def process_user_selection(callback: CallbackQuery, state: FSMContext):
    # Извлекаем ID из callback_data (mail_to_12345 -> 12345)
    target_id = callback.data.replace("mail_to_", "")

    # Сохраняем ID в память FSM
    await state.update_data(target_user_id=target_id)

    # Переходим к следующему состоянию — ожидание текста
    await state.set_state(MailingStates.waiting_for_private_text)

    await callback.answer()  # Убираем "часики" на кнопке

    # Редактируем старое сообщение, чтобы интерфейс был плавным
    await callback.message.edit_text(
        f"✅ <b>Получатель выбран!</b> (ID: <code>{target_id}</code>)\n"
        f"───────────────────\n"
        f"Теперь <b>введите текст</b> письма, который хотите отправить:",
        parse_mode="HTML"
    )


# Дополнительно: Хендлер для кнопки "❌ Отмена"
@dp.callback_query(F.data == "cancel_mailing")
async def cancel_mailing_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Действие отменено")
    await callback.message.edit_text("❌ Рассылка отменена. Возврат в админ-панель.")


# 2. Обработка ID и переход к вводу текста
@dp.message(MailingStates.waiting_for_user_id)
async def process_mailing_user_id(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад в админку":
        await state.clear()
        return await message.answer("Отменено", reply_markup=get_admin_main_kb())

    if not message.text.isdigit():
        return await message.answer("❌ Ошибка: ID должен состоять только из цифр. Попробуйте снова:")

    await state.update_data(target_user_id=message.text)
    await state.set_state(MailingStates.waiting_for_private_text)
    await message.answer(f"✅ ID {message.text} принят. Теперь введите <b>текст письма</b>:", parse_mode="HTML")


# 3. Финальная отправка конкретному
@dp.message(MailingStates.waiting_for_private_text)
async def send_private_message(message: Message, state: FSMContext, bot: Bot):
    if message.text == "⬅️ Назад в админку":
        await state.clear()
        return await message.answer("Отменено", reply_markup=get_admin_main_kb())

    data = await state.get_data()
    target_id = data.get('target_user_id')

    try:
        await bot.send_message(target_id, f"✉️ <b>Сообщение от администрации:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer(f"✅ Отправлено пользователю <code>{target_id}</code>", reply_markup=get_admin_main_kb(),
                             parse_mode="HTML")
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\nПроверьте ID или не заблокировал ли вас пользователь.")


# 4. Вход в режим "Письмо всем"
@dp.message(F.text == "👥 Письмо всем")
async def start_global_mailing(message: Message, state: FSMContext):
    await state.set_state(MailingStates.waiting_for_global_text)
    await message.answer("📢 <b>Введите текст для ОБЩЕЙ рассылки:</b>", parse_mode="HTML",
                         reply_markup=get_admin_mailing_kb())


# 5. Финальная рассылка всем
@dp.message(MailingStates.waiting_for_global_text)
async def send_global_message(message: Message, state: FSMContext, bot: Bot):
    if message.text == "⬅️ Назад в админку":
        await state.clear()
        return await message.answer("Отменено", reply_markup=get_admin_main_kb())

    status_msg = await message.answer("🚀 Рассылка запущена...")

    async with async_session() as session:
        users = (await session.execute(select(User.tg_id))).scalars().all()

    count, errors = 0, 0
    for user_tg_id in users:
        try:
            await bot.send_message(user_tg_id, f"📢 <b>Важное уведомление:</b>\n\n{message.text}", parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05)
        except:
            errors += 1
            continue

    await status_msg.delete()
    await message.answer(f"🏁 <b>Завершено!</b>\n✅ Успешно: {count}\n❌ Ошибок: {errors}",
                         reply_markup=get_admin_main_kb(), parse_mode="HTML")
    await state.clear()

# --- ПОИСК ПО ТТН (Ввод номера) ---
# 2. Нажатие на кнопку поиска в меню
@dp.callback_query(F.data == "search_by_ttn")
async def admin_search_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.waiting_for_query)
    await callback.message.answer("🔎 Введите трек-номер или ТТН для поиска заказа:")
    await callback.answer()


# 3. Обработка введенного номера
@dp.message(SearchStates.waiting_for_query)
async def admin_search_process(message: Message, state: FSMContext):
    query = message.text.strip().upper()

    async with async_session() as session:
        # Ищем по track_number (международный) или по ТТН (Новая Почта)
        stmt = select(Order, User).join(User).where(
            or_(
                Order.track_number == query,
                Order.ttn_number == query  # Убедитесь, что такие поля есть в базе
            )
        )
        result = await session.execute(stmt)
        data = result.first()

    if not data:
        await message.answer(f"❌ Заказ с номером <code>{query}</code> не найден.", parse_mode="HTML")
    else:
        order, user = data
        text = (
            f"✅ <b>Заказ найден!</b>\n"
            f"🆔 №{order.id} | Клиент: {user.full_name}\n"
            f"📦 Товар: {order.title}\n"
            f"📊 Текущий статус: <b>{order.status}</b>\n\n"
            f"Перевести в статус 'НА СКЛАДЕ'?"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="📥 Принять на склад", callback_data=f"set_stat_{order.id}_НА_СКЛАДЕ")
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

    await state.clear()

# --- ОБРАБОТКА ПОИСКА ---
@dp.message(AdminSettings.waiting_for_ttn_search)
async def process_ttn_search(message: Message, state: FSMContext):
    query = message.text.strip()

    async with async_session() as session:
        # Ищем по ТТН, ID заказа или фамилии клиента
        stmt = (
            select(Order, User)
            .join(User, Order.user_id == User.id)
            .where(
                (Order.size_details.ilike(f"%{query}%")) |
                (User.full_name.ilike(f"%{query}%")) |
                (Order.id.cast(String).ilike(f"%{query}%"))
            )
        )
        result = await session.execute(stmt)
        found_data = result.all()

    if not found_data:
        await message.answer("❌ Ничего не найдено. Попробуйте ввести номер ТТН точнее.")
        await state.clear()
        return

    for order, user in found_data:
        builder = InlineKeyboardBuilder()
        builder.button(text="📦 Запросить реквизиты", callback_data=f"request_shipping_{order.id}")
        builder.button(text="✏️ Изменить статус", callback_data=f"manage_order_{order.id}")
        builder.adjust(1)

        await message.answer(
            f"📦 <b>Заказ №{order.id}</b>\n"
            f"👤 <b>Клиент:</b> {user.full_name}\n"
            f"📝 <b>Инфо/ТТН:</b> {order.size_details}\n"
            f"💰 <b>Сумма:</b> {order.price_uah} грн",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    await state.clear()


# Хендлер нажатия кнопки "Перевести в В ПУТИ"
@dp.callback_query(F.data.startswith("set_status_В_ПУТИ_"))
async def start_ttn_input(callback: CallbackQuery, state: FSMContext):
    # Извлекаем ID заказа
    order_id = callback.data.replace("set_status_В_ПУТИ_", "")

    # Сохраняем ID заказа в память бота
    await state.update_data(current_order_id=order_id)
    # Включаем режим ожидания ТТН
    await state.set_state(OrderProcessStates.waiting_for_ttn)

    await callback.message.answer(
        f"🚛 <b>Заказ №{order_id}</b>\nВведите номер ТТН Новой Почты для клиента:",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(OrderProcessStates.waiting_for_ttn)
async def process_ttn_save(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid = data.get("current_order_id")
    ttn_val = message.text

    async with async_session() as session:
        # Обновляем заказ (убедитесь, что поле ttn есть в модели Order)
        await session.execute(
            update(Order).where(Order.id == int(oid)).values(status="В ПУТИ", ttn=ttn_val)
        )

        # Получаем данные клиента для отправки сообщения
        res = await session.execute(select(Order).where(Order.id == int(oid)))
        order = res.scalar()
        user_res = await session.execute(select(User).where(User.id == order.user_id))
        user_tg_id = user_res.scalar().tg_id
        await session.commit()

    # Уведомляем клиента
    try:
        await bot.send_message(
            user_tg_id,
            f"🚀 <b>Ваш заказ отправлен!</b>\n📦 ТТН: <code>{ttn_val}</code>\n"
            f"Статус заказа в боте обновлен на 'В пути'.",
            parse_mode="HTML"
        )
    except:
        pass

    await message.answer(f"✅ Статус заказа №{oid} изменен. ТТН сохранена.")
    await state.clear()


# Хендлер получения текста ТТН
@dp.message(OrderProcessStates.waiting_for_ttn)
async def save_ttn_and_notify(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid = data['current_order_id']
    ttn_val = message.text

    async with async_session() as session:
        # Обновляем статус и ТТН в базе
        await session.execute(
            update(Order).where(Order.id == int(oid)).values(status="В ПУТИ", ttn=ttn_val)
        )
        # Получаем ТГ-айди пользователя
        res = await session.execute(select(Order).where(Order.id == int(oid)))
        order = res.scalar()
        user_res = await session.execute(select(User).where(User.id == order.user_id))
        user_tg_id = user_res.scalar().tg_id
        await session.commit()

    # Сразу уведомляем пользователя
    try:
        await bot.send_message(
            user_tg_id,
            f"🚀 <b>Ваш заказ в пути!</b>\n📦 Номер ТТН: <code>{ttn_val}</code>",
            parse_mode="HTML"
        )
    except:
        pass

    await message.answer(f"✅ Статус заказа №{oid} изменен на 'В ПУТИ'. ТТН отправлена клиенту.")
    await state.clear()



# 2. Рассылка всем (Заглушка)
# 1. Начало процесса: просим прислать сообщение
@dp.callback_query(F.data == "mail_all")
async def mail_all_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "📢 <b>Подготовка рассылки</b>\n\n"
        "Пришлите текст сообщения (можно с фото).\n"
        "<i>Его увидят все пользователи бота!</i>",
        parse_mode="HTML"
    )
    await state.set_state(AdminSettings.waiting_for_mail_text)


# 2. Обработка и запуск рассылки
@dp.message(AdminSettings.waiting_for_mail_text)
async def mail_all_process(message: Message, state: FSMContext, bot: Bot):
    await state.clear()

    # Получаем всех пользователей из базы
    async with async_session() as session:
        result = await session.execute(select(User.tg_id))
        users = result.scalars().all()

    sent_count = 0
    err_count = 0

    status_msg = await message.answer(f"🚀 Рассылка запущена для {len(users)} пользователей...")

    for user_id in users:
        try:
            # Если в сообщении есть фото
            if message.photo:
                await bot.send_photo(
                    user_id,
                    photo=message.photo[-1].file_id,
                    caption=message.caption or "",
                    parse_mode="HTML"
                )
            # Если только текст
            else:
                await bot.send_message(user_id, message.text, parse_mode="HTML")

            sent_count += 1
            # Небольшая пауза, чтобы Telegram не заблокировал за спам
            await asyncio.sleep(0.05)

        except Exception:
            err_count += 1

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n"
        f"───────────────────\n"
        f"📥 Доставлено: {sent_count}\n"
        f"❌ Не удалось: {err_count} (заблокировали бота)",
        parse_mode="HTML"
    )


# 3. Написать лично (Тот самый список из Матрицы судьбы)
@dp.callback_query(F.data == "mail_personal")
async def mail_personal_list(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        # Берем последних 10 пользователей
        result = await session.execute(select(User).limit(10))
        users = result.scalars().all()

    builder = InlineKeyboardBuilder()
    for user in users:
        builder.button(text=f"👤 {user.full_name}", callback_data=f"write_to_{user.tg_id}")
    builder.button(text="⬅️ Назад", callback_data="admin_panel")
    builder.adjust(1)
    await callback.message.edit_text("📝 <b>Кому напишем?</b>", reply_markup=builder.as_markup(), parse_mode="HTML")

# Показ списка заказов по статусу
@dp.callback_query(F.data.startswith("orders_view_"))
async def admin_orders_list(callback: CallbackQuery):
    status_raw = callback.data.replace("orders_view_", "")
    status_db = status_raw.replace("_", " ").upper()

    async with async_session() as session:
        stmt = (
            select(Order, User)
            .join(User, Order.user_id == User.id)
            .where(func.upper(Order.status) == status_db)
            .order_by(Order.created_at.desc())
        )
        result = await session.execute(stmt)
        orders_data = result.all()

    if not orders_data:
        return await callback.answer(f"В категории '{status_db}' пусто", show_alert=True)

    await callback.answer()
    await callback.message.answer(f"📦 <b>Категория: {status_db}</b>", parse_mode="HTML")

    for order, user in orders_data:
        text = (
            f"🆔 <b>Заказ №{order.id}</b>\n"
            f"───────────────────\n"
            f"👤 <b>Клиент:</b> {user.full_name or 'Не указан'}\n"
            f"📱 <b>TG:</b> @{user.username or 'нет'}\n"
            f"🏷 <b>Товар:</b> {order.title}\n"
            f"📝 <b>Детали:</b> {order.size_details or 'нет'}\n"
            f"💰 <b>Сумма:</b> {order.price_uah} грн\n"
            f"📅 <b>Дата:</b> {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"───────────────────\n"
            f"📊 <b>Статус:</b> <code>{order.status}</code>"
        )

        builder = InlineKeyboardBuilder()

        # 1. Кнопка ссылки
        if order.url and isinstance(order.url, str) and order.url.startswith("http"):
            builder.button(text="🔗 Ссылка на товар", url=order.url)

        # 2. ЛОГИКА КНОПОК ПО ВАШЕМУ ПЛАНУ
        if status_db == "НОВЫЙ":
            builder.button(text="💰 Выставить счет", callback_data=f"adm_invoice_{order.id}")
            builder.button(text="❌ Нет в наличии", callback_data=f"adm_cancel_{order.id}")

        elif status_db == "ОЖИДАЕТ ОПЛАТЫ":
            # ИСПРАВЛЕНО: callback_data теперь совпадает с хендлером подтверждения (adm_pay_ok)
            builder.button(text="✅ Оплата подтверждена", callback_data=f"adm_pay_ok_{order.id}")
            builder.button(text="❌ Отменить", callback_data=f"adm_cancel_{order.id}")

        # --- НОВЫЙ БЛОК: Ожидание трек-номера ---
        elif status_db == "ЖДЕТ ТРЕК":
            builder.button(text="📦 Ввести трек-номер", callback_data=f"adm_set_track_{order.id}")
            builder.button(text="❌ Отменить", callback_data=f"adm_cancel_{order.id}")

        elif status_db == "В ПУТИ":
            builder.button(text="📦 Прибыл (На склад)", callback_data=f"set_stat_{order.id}_НА_СКЛАДЕ")

        elif status_db == "НА СКЛАДЕ":
            builder.button(text="🚀 Отправить (Ввести ТТН)", callback_data=f"set_status_В_ПУТИ_{order.id}")
            builder.button(text="✅ Завершить заказ", callback_data=f"set_stat_{order.id}_ЗАВЕРШЕН")

        # Кнопка редактирования
        builder.button(text="✏️ Изменить данные", callback_data=f"manage_order_{order.id}")

        builder.adjust(1)

        try:
            await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data.startswith("set_stat_"))
async def admin_change_status_process(callback: CallbackQuery, bot: Bot, state: FSMContext):
    # 1. МГНОВЕННЫЙ ОТВЕТ (Техконтроль таймаута)
    # Это предотвращает ошибку "query is too old"
    try:
        await callback.answer()
    except Exception:
        pass

    data_parts = callback.data.split("_")

    # Защита от пустых данных
    if len(data_parts) < 4:
        return

    order_id = int(data_parts[2])
    # Склеиваем статус (например, "НА_СКЛАДЕ" -> "НА СКЛАДЕ")
    new_status_db = " ".join(data_parts[3:]).upper()

    # 2. ПЕРЕХВАТ ДЛЯ РАСЧЕТА ВЕСА (Пункт 7 вашего плана)
    if new_status_db == "НА СКЛАДЕ":
        # Очищаем состояния и запускаем процесс ввода веса
        await state.clear()
        await state.update_data(weight_order_id=order_id)
        await state.set_state(OrderProcessStates.waiting_for_weight)

        await callback.message.answer(
            f"⚖️ <b>Заказ №{order_id} прибыл!</b>\n"
            f"Шаг 1: Введите вес посылки в кг (через точку, например: 1.2):",
            parse_mode="HTML"
        )
        # ВАЖНО: выходим из функции, чтобы статус в базе не изменился
        # раньше, чем мы рассчитаем вес и выставим счет.
        return

        # 3. СТАНДАРТНАЯ СМЕНА СТАТУСОВ (В ПУТИ, ЗАВЕРШЕН и т.д.)
    async with async_session() as session:
        order = await session.get(Order, order_id)
        if not order:
            return await callback.message.answer(f"❌ Заказ №{order_id} не найден.")

        order.status = new_status_db
        await session.commit()

    # 4. ОБНОВЛЯЕМ МЕНЮ АДМИНА
    # Чтобы счетчики на вашем iPhone 13 сразу обновились
    await admin_statuses_main(callback)


# --- ШАГ 2: ПОЛУЧАЕМ ВЕС И СПРАШИВАЕМ ВАЛЮТУ ---
@dp.message(OrderProcessStates.waiting_for_weight)
async def process_weight_step(message: Message, state: FSMContext):
    weight_raw = message.text.replace(",", ".").strip()
    try:
        weight = float(weight_raw)
    except ValueError:
        return await message.answer("⚠️ Введите число веса (например: 0.8)")

    await state.update_data(weight=weight)

    # Клавиатура выбора валюты
    kb = InlineKeyboardBuilder()
    kb.button(text="💵 USD", callback_data="w_curr_USD")
    kb.button(text="💶 EUR", callback_data="w_curr_EUR")
    kb.button(text="💳 UAH", callback_data="w_curr_UAH")
    kb.adjust(3)

    await message.answer(f"✅ Вес {weight} кг записан.\nШаг 2: Выберите валюту тарифа:", reply_markup=kb.as_markup())
    await state.set_state(OrderProcessStates.waiting_for_currency)


# --- ШАГ 3: ПОЛУЧАЕМ ВАЛЮТУ И СПРАШИВАЕМ ТАРИФ ---
@dp.callback_query(OrderProcessStates.waiting_for_currency, F.data.startswith("w_curr_"))
async def process_currency_step(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("_")[2]
    await state.update_data(weight_currency=currency)

    await callback.message.edit_text(f"💰 Валюта: {currency}\nШаг 3: Введите тариф за 1 кг (например: 12.5):")
    await state.set_state(OrderProcessStates.waiting_for_rate)
    await callback.answer()


# --- ШАГ 4: РАСЧЕТ И ВЫСТАВЛЕНИЕ СЧЕТА КЛИЕНТУ ---
@dp.message(OrderProcessStates.waiting_for_rate)
async def process_final_weight_invoice(message: Message, state: FSMContext, bot: Bot):
    rate_raw = message.text.replace(",", ".").strip()
    try:
        rate = float(rate_raw)
    except:
        return await message.answer("⚠️ Введите число тарифа")

    data = await state.get_data()
    oid = data['weight_order_id']
    weight = data['weight']
    curr = data['weight_currency']

    # Расчет (курс можно вынести в настройки)
    rates = {"USD": 41.5, "EUR": 45.0, "UAH": 1.0}
    total_uah = round(weight * rate * rates.get(curr, 1.0), 2)

    async with async_session() as session:
        # ВАЖНО: JOIN с пользователем, чтобы получить его tg_id
        stmt = select(Order, User).join(User).where(Order.id == oid)
        res = (await session.execute(stmt)).first()
        if not res: return await message.answer("❌ Заказ не найден")

        order, user = res
        order.weight_invoice_amount = total_uah
        order.status = "ОЖИДАЕТ ОПЛАТЫ ВЕСА" # Строго этот статус
        await session.commit()

        customer_tg_id = user.tg_id # ID ПОЛУЧАТЕЛЯ

    # Кнопка для чека
    kb = InlineKeyboardBuilder()
    kb.button(text="📸 Отправить чек за ВЕС", callback_data=f"user_pay_weight_{oid}")

    invoice_text = (
        f"⚖️ <b>Выставлен счет за доставку (ВЕС) №{oid}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 Вес: <b>{weight} кг</b> | Тариф: <b>{rate} {curr}</b>\n"
        f"💰 Итого к оплате: <b>{total_uah} грн</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>Счет добавлен в ваш раздел 'Ожидают оплаты'.</i>"
    )

    try:
        # ОТПРАВЛЯЕМ КЛИЕНТУ В ЛИЧКУ
        await bot.send_message(customer_tg_id, invoice_text, reply_markup=kb.as_markup(), parse_mode="HTML")
        # ПОДТВЕРЖДАЕМ АДМИНУ
        await message.answer(f"✅ Счет на {total_uah} грн отправлен клиенту {user.full_name}.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: клиент не получил сообщение. Возможно, он заблокировал бота.")

    await state.clear()


@dp.callback_query(F.data.startswith("adm_pay_weight_ok_"))
async def confirm_weight_payment(callback: CallbackQuery, bot: Bot, state: FSMContext):
    # 1. Сразу гасим часы на кнопке
    try:
        await callback.answer()
    except:
        pass

    oid = int(callback.data.split("_")[4])

    async with async_session() as session:
        # Загружаем заказ
        order = await session.get(Order, oid)
        if not order:
            return await callback.message.answer(f"❌ Заказ №{oid} не найден.")

        # Находим владельца заказа
        user_res = await session.execute(select(User).where(User.id == order.user_id))
        user_data = user_res.scalar()

        # Обновляем статус в базе
        order.status = "ОЖИДАЕТ ОТПРАВКИ"
        await session.commit()

    # 2. ТЕХКОНТРОЛЬ: Переключаем состояние КЛИЕНТА
    # Создаем ключ к памяти конкретного клиента
    customer_key = StorageKey(
        bot_id=bot.id,
        chat_id=user_data.tg_id,
        user_id=user_data.tg_id
    )

    # ИСПРАВЛЕНО: Убираем bot=bot из аргументов
    await state.storage.set_state(key=customer_key, state=OrderProcessStates.waiting_for_shipping_details)
    await state.storage.set_data(key=customer_key, data={"shipping_order_id": oid})

    # 3. ОТПРАВЛЯЕМ ЗАПРОС КЛИЕНТУ
    shipping_msg = (
        f"✅ <b>Оплата доставки за вес подтверждена!</b>\n\n"
        f"📦 <b>Заказ №{oid}</b> готов к отправке по Украине.\n"
        f"Пожалуйста, пришлите данные для <b>Новой Почты</b> одним сообщением:\n"
        f"1. ФИО получателя\n"
        f"2. Номер телефона\n"
        f"3. Город\n"
        f"4. Номер отделения\n\n"
        f"<i>Просто напишите эти данные в ответ на это сообщение.</i>"
    )

    try:
        await bot.send_message(user_data.tg_id, shipping_msg, parse_mode="HTML")
        await callback.message.edit_caption(
            caption=f"✅ Оплата ВЕСА №{oid} принята. Клиенту {user_data.full_name} отправлен запрос реквизитов НП."
        )
    except Exception as e:
        await callback.message.answer(f"⚠️ Оплата подтверждена, но не удалось написать клиенту: {e}")


@dp.message(OrderProcessStates.waiting_for_shipping_details)
async def process_shipping_details(message: Message, state: FSMContext, bot: Bot):
    # Достаем ID заказа, который мы сохранили в память клиента ранее
    data = await state.get_data()
    oid = data.get("shipping_order_id")
    address_text = message.text

    async with async_session() as session:
        # Сохраняем реквизиты в базу
        order = await session.get(Order, oid)
        if order:
            order.shipping_details = address_text
            order.status = "ГОТОВ К ОТПРАВКЕ"
            await session.commit()

        # Получаем всех админов для рассылки
        admins = (await session.execute(select(User.tg_id).where(User.is_admin == True))).scalars().all()

    # --- 1. УВЕДОМЛЕНИЕ АДМИНУ ---
    # Создаем кнопку, чтобы админ сразу мог ввести ТТН
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Ввести номер ТТН", callback_data=f"adm_set_ttn_{oid}")

    admin_msg = (
        f"📩 <b>ПОЛУЧЕНЫ РЕКВИЗИТЫ НП (Заказ №{oid})</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 Клиент: <b>{message.from_user.full_name}</b>\n"
        f"📝 <b>Данные для отправки:</b>\n"
        f"<code>{address_text}</code>\n"  # Копируется одним нажатием
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>Нажмите кнопку ниже, когда отправите посылку.</i>"
    )

    for adm_id in admins:
        try:
            await bot.send_message(adm_id, admin_msg, reply_markup=kb.as_markup(), parse_mode="HTML")
        except:
            pass

    # --- 2. ПОДТВЕРЖДЕНИЕ КЛИЕНТУ (Исправляем "красоту") ---
    # Теперь теги будут работать правильно
    await message.answer(
        "✅ <b>Данные приняты!</b>\n"
        "Мы уже готовим вашу посылку. Как только отправим — пришлем номер ТТН.",
        parse_mode="HTML"
    )

    await state.clear()


# ОСНОВНОЙ МОДУЛЬ КАТАЛОГА (Европа и США)
# ОСНОВНОЙ МОДУЛЬ КАТАЛОГА (Европа и США)
# В aiogram 3.x StateFilter("*") пишется просто через запятую, БЕЗ слова "state="
@dp.message(F.text == "🌍 Товары из Европы и США", StateFilter("*"))
async def show_europe_usa_catalog(message: Message, state: FSMContext):
    # ТЕХКОНТРОЛЬ: Сбрасываем "глухоту" бота.
    # Если клиент был в режиме ввода адреса, мы его оттуда вытаскиваем.
    await state.clear()

    kb = await get_categories_kb()
    if not kb.inline_keyboard:
        await message.answer("⚠️ <b>Каталог сейчас наполняется.</b>\nЗайдите позже!", parse_mode="HTML")
        return

    await message.answer(
        "🌍 <b>Товары из Европы и США</b>\n"
        "──────────────────────────\n"
        "Выберите раздел для поиска брендовых магазинов:",
        reply_markup=kb,
        parse_mode="HTML"
    )


# 1. Хендлер нажатия на кнопку "🆘 Поддержка"
@dp.message(F.text == "🆘 Поддержка", StateFilter("*"))
async def support_start_handler(message: Message, state: FSMContext):
    # ТЕХКОНТРОЛЬ: Сначала очищаем старые состояния (адрес, вес и т.д.)
    await state.clear()

    await message.answer(
        "✍️ <b>Напишите ваш вопрос или описание проблемы:</b>\n"
        "Я сразу передам его администратору.",
        parse_mode="HTML"
    )

    # И ТОЛЬКО ТЕПЕРЬ устанавливаем новое состояние ожидания сообщения
    await state.set_state(SupportState.waiting_for_support_msg)


# 2. Хендлер, который ПРИНИМАЕТ сообщение (тут StateFilter("*") НЕ НУЖЕН!)
@dp.message(SupportState.waiting_for_support_msg)
async def process_support_message(message: Message, state: FSMContext, bot: Bot):
    # Отправляем сообщение админам (используйте ваш список админов)
    async with async_session() as session:
        admins = (await session.execute(select(User.tg_id).where(User.is_admin == True))).scalars().all()

    for adm_id in admins:
        try:
            await bot.send_message(
                adm_id,
                f"🆘 <b>НОВОЕ ОБРАЩЕНИЕ В ПОДДЕРЖКУ</b>\n"
                f"👤 От: <b>{message.from_user.full_name}</b>\n"
                f"🆔 ID: <code>{message.from_user.id}</code>\n"
                f"───────────────────\n"
                f"💬 Сообщение:\n{message.text}",
                parse_mode="HTML"
            )
        except:
            pass

    await message.answer("✅ <b>Ваше сообщение отправлено администратору.</b>\nОжидайте ответа!", parse_mode="HTML")

    # Сбрасываем состояние после отправки
    await state.clear()

# --- ШАГ 1: АДМИН НАЖИМАЕТ "ВВЕСТИ ТТН" ---
# --- ШАГ 1: Админ нажимает кнопку "Ввести номер ТТН" ---
@dp.callback_query(F.data.startswith("adm_set_ttn_"))
async def start_ttn_input(callback: CallbackQuery, state: FSMContext):
    oid = int(callback.data.split("_")[3])

    # Включаем режим ожидания текста от админа
    await state.set_state(AdminStates.waiting_for_ttn)
    # Запоминаем ID заказа, для которого пишем ТТН
    await state.update_data(ttn_order_id=oid)

    await callback.message.answer(
        f"🚚 <b>Заказ №{oid}</b>\nВведите номер ТТН Новой Почты (цифрами или текстом):",
        parse_mode="HTML"
    )
    await callback.answer()


# --- ШАГ 2: Админ присылает номер ТТН (Ваш "фывпр") ---
@dp.message(AdminStates.waiting_for_ttn)
async def process_admin_ttn_input(message: Message, state: FSMContext, bot: Bot):
    # Достаем ID заказа из памяти
    data = await state.get_data()
    oid = data.get("ttn_order_id")
    ttn_number = message.text.strip()

    async with async_session() as session:
        # 1. Обновляем заказ в базе
        order = await session.get(Order, oid)
        if not order:
            await message.answer("❌ Ошибка: заказ не найден в базе.")
            return await state.clear()

        order.status = "ЗАВЕРШЕН"
        order.track_number = ttn_number  # Сохраняем ТТН в базу
        await session.commit()

        # 2. Находим клиента, чтобы отправить ему радостную новость
        user_res = await session.execute(select(User).where(User.id == order.user_id))
        client = user_res.scalar()

    # --- 3. УВЕДОМЛЕНИЕ КЛИЕНТУ (Исправляем красоту) ---
    client_msg = (
        f"🚀 <b>Ваша посылка отправлена!</b>\n"
        f"───────────────────\n"
        f"📦 <b>Заказ №{oid}</b>\n"
        f"🧾 <b>ТТН Новой Почты:</b> <code>{ttn_number}</code>\n\n"
        f"<i>Вы можете отследить статус в приложении НП. Благодарим за покупку!</i> ✅"
    )

    try:
        # ТЕХКОНТРОЛЬ: parse_mode="HTML" убирает видимые теги <b>
        await bot.send_message(client.tg_id, client_msg, parse_mode="HTML")

        # Подтверждение админу
        await message.answer(
            f"✅ <b>Готово!</b>\nТТН <code>{ttn_number}</code> отправлен клиенту {client.full_name}.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"⚠️ Статус изменен, но не удалось уведомить клиента: {e}")

    # Сбрасываем состояние админа
    await state.clear()




@dp.message(OrderProcessStates.waiting_for_rate)
async def process_final_weight_invoice(message: Message, state: FSMContext, bot: Bot):
    rate_raw = message.text.replace(",", ".").strip()
    try:
        rate = float(rate_raw)
    except ValueError:
        return await message.answer("⚠️ Введите число тарифа")

    data = await state.get_data()
    oid = data['weight_order_id']
    weight = data['weight']
    curr = data['weight_currency']

    # Курс (можно менять)
    rates = {"USD": 41.5, "EUR": 45.0, "UAH": 1.0}
    ex_rate = rates.get(curr, 1.0)
    total_uah = round(weight * rate * ex_rate, 2)

    async with async_session() as session:
        # Получаем заказ и данные клиента через JOIN, чтобы не ошибиться с ID
        stmt = select(Order, User).join(User).where(Order.id == oid)
        result = await session.execute(stmt)
        res = result.first()

        if not res:
            return await message.answer("❌ Ошибка: заказ не найден в базе.")

        order, user = res
        order.weight_invoice_amount = total_uah
        # Устанавливаем статус, который мы добавим в фильтр "Неоплаченных"
        order.status = "ОЖИДАЕТ ОПЛАТЫ ВЕСА"
        await session.commit()

        # ТЕХКОНТРОЛЬ: Это ID клиента, которому уйдет сообщение
        customer_tg_id = user.tg_id

    # ФОРМИРУЕМ СЧЕТ
    kb = InlineKeyboardBuilder()
    kb.button(text="📸 Отправить чек за ВЕС", callback_data=f"user_pay_weight_{oid}")
    kb.adjust(1)

    msg = (
        f"⚖️ <b>Выставлен счет за доставку (ВЕС) №{oid}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 Вес: <b>{weight} кг</b>\n"
        f"💵 Тариф: <b>{rate} {curr}</b>\n"
        f"💰 Итого к оплате: <b>{total_uah} грн</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>Счет добавлен в ваш раздел 'Неоплаченные'. Пожалуйста, оплатите доставку и пришлите фото чека.</i>"
    )

    # 1. ОТПРАВЛЯЕМ КЛИЕНТУ (теперь точно ему)
    try:
        await bot.send_message(customer_tg_id, msg, reply_markup=kb.as_markup(), parse_mode="HTML")
        # 2. ПОДТВЕРЖДАЕМ АДМИНУ (вам)
        await message.answer(f"✅ Расчет завершен. Счет на {total_uah} грн отправлен клиенту {user.full_name}.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить счет клиенту (возможно, бот заблокирован): {e}")

    await state.clear()

# Важно: добавьте parse_mode="HTML" во все edit_text/answer!
# 1. Обработка входа в админку (из главного меню)
# Используем StateFilter("*"), чтобы админка открывалась даже если бот ждал ввода тарифа/веса
@dp.message(F.text.in_({"🛠 Админ-панель", "🔐 Админ-панель"}), StateFilter("*"))
async def admin_panel_entry(message: Message, state: FSMContext):
    # ТЕХКОНТРОЛЬ: Проверка прав админа
    if not await is_admin(message.from_user.id):
        return

    # ТЕХКОНТРОЛЬ: Сбрасываем старые вводы (вес, тариф и т.д.), чтобы не было глюков
    await state.clear()

    async with async_session() as session:
        # Считаем именно заказы со статусом "НОВЫЙ"
        # Используем func.upper для 100% совпадения, как в image_dbb078.png
        res = await session.execute(
            select(func.count(Order.id)).where(func.upper(Order.status) == "НОВЫЙ")
        )
        new_count = res.scalar() or 0

    # Выводим главное меню админа
    await message.answer(
        f"🛠 <b>Панель управления:</b>\n"
        f"Новых заказов для обработки: <b>{new_count}</b>",
        reply_markup=get_admin_main_kb(new_count), # Передаем число для кнопки в главном меню
        parse_mode="HTML"
    )


# 1. Если товара НЕТ (Кнопка "Нет в наличии")
@dp.callback_query(F.data.startswith("adm_cancel_"))
async def admin_cancel_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])

    async with async_session() as session:
        order = await session.get(Order, order_id)
        order.status = "ЗАВЕРШЕН"
        order.admin_comment = "ОТМЕНА: Товара нет в наличии"

        user_res = await session.execute(select(User).where(User.id == order.user_id))
        user_tg_id = user_res.scalar().tg_id
        await session.commit()

        await callback.bot.send_message(
            user_tg_id,
            f"❌ <b>Заказ №{order_id} отменен</b>\nК сожалению, товара нет в наличии в магазине. Заказ закрыт.",
            parse_mode="HTML"
        )

    await callback.message.edit_text(f"✅ Заказ №{order_id} отменен. Клиент уведомлен.")


# 2. Обработка текста отмены и перенос в ЗАВЕРШЕННЫЕ
@dp.message(OrderProcessStates.waiting_for_cancel_reason)
async def process_cancel_finish(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid = int(data['cancel_order_id'])
    reason = message.text

    async with async_session() as session:
        order = await session.get(Order, oid)
        user_res = await session.execute(select(User).where(User.id == order.user_id))
        user_tg_id = user_res.scalar().tg_id

        # Обновляем статус на ЗАВЕРШЕН (т.к. работа по нему закончена)
        order.status = "ЗАВЕРШЕН"
        order.admin_comment = f"ОТМЕНА: {reason}"
        await session.commit()

    await bot.send_message(user_tg_id, f"❌ <b>Ваш заказ №{oid} отменен.</b>\nПричина: {reason}", parse_mode="HTML")
    await message.answer(f"✅ Заказ №{oid} закрыт и перенесен в завершенные.")
    await state.clear()


# 3. Если товар ЕСТЬ (Кнопка "Выставить счет")
@dp.callback_query(F.data.startswith("adm_invoice_"))
async def admin_invoice_start(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[2]
    await state.update_data(inv_order_id=order_id)

    await callback.message.answer(f"💰 Заказ №{order_id}. Введите итоговую сумму к оплате (грн):")
    await state.set_state(OrderProcessStates.waiting_for_invoice_sum)
    await callback.answer()


# 4. Отправка счета клиенту

@dp.callback_query(F.data.startswith("ask_"))
async def admin_ask_details(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[1]
    await state.update_data(ask_order_id=order_id)

    await callback.message.answer(f"✍️ <b>Замовлення №{order_id}</b>\nВведіть текст повідомлення для клієнта:",
                                  parse_mode="HTML")
    await state.set_state(AdminSettings.waiting_for_ask_text)  # Используем ваше состояние


@dp.message(AdminSettings.waiting_for_ask_text)
async def admin_send_ask_text(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    order_id = int(data['ask_order_id'])

    async with async_session() as session:
        order = await session.get(Order, order_id)
        user = await session.execute(select(User).where(User.id == order.user_id))
        user_data = user.scalar()

    try:
        await bot.send_message(
            user_data.tg_id,
            f"⚠️ <b>Питання від менеджера по замовленню №{order_id}:</b>\n\n{message.text}",
            parse_mode="HTML"
        )
        await message.answer("✅ Повідомлення надіслано клієнту!")
    except Exception as e:
        await message.answer(f"❌ Не вдалося надіслати: {e}")

    await state.clear()


@dp.callback_query(F.data.startswith("move_"))
async def admin_change_order_status(callback: CallbackQuery, bot: Bot):
    # Разбираем callback_data: 'move_ID_СТАТУС'
    # maxsplit=2 нужен, чтобы статусы типа 'В_ПУТИ' не ломали логику
    parts = callback.data.split("_", maxsplit=2)
    if len(parts) < 3:
        await callback.answer("Ошибка в данных кнопки")
        return

    _, order_id, new_status = parts
    order_id = int(order_id)

    async with async_session() as session:
        # 1. Получаем заказ из базы
        order = await session.get(Order, order_id)
        if not order:
            await callback.answer("Заказ не найден")
            return

        # 2. Обновляем статус в базе
        order.status = new_status

        # 3. Находим пользователя для уведомления
        user_res = await session.execute(
            select(User).where(User.id == order.user_id)
        )
        user_db = user_res.scalar_one_or_none()

        await session.commit()

    # 4. Словарь уведомлений для клиента (на русском)
    status_msg = {
        "В_ПУТИ": "🚚 Ваш заказ №{id} выкуплен и едет на наш склад!",
        "НА_СКЛАДЕ": "📦 Ваш заказ №{id} прибыл на наш склад и готовится к отправке вам.",
        "ОТПРАВЛЕН": "🚀 Ваш заказ №{id} передан почтовой службе! Ожидайте ТТН.",
        "ЗАВЕРШЕН": "🏁 Заказ №{id} успешно завершен. Будем рады новым покупкам!",
        "ОТМЕНЕН": "❌ Ваш заказ №{id} был отменен менеджером."
    }

    # 5. Отправляем уведомление пользователю, если он есть в базе
    if user_db and new_status in status_msg:
        try:
            await bot.send_message(
                user_db.tg_id,
                status_msg[new_status].format(id=order_id),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление пользователю {user_db.tg_id}: {e}")

    # 6. Отвечаем админу и удаляем старую карточку заказа
    await callback.answer(f"Статус изменен на: {new_status}")
    await callback.message.delete()


async def is_admin(user_id: int) -> bool:
    # Ваш личный ID (SUPER_ADMIN)
    SUPER_ADMIN_ID = 1502399001

    # Сначала проверяем супер-админа
    if int(user_id) == SUPER_ADMIN_ID:
        return True

    async with async_session() as session:
        try:
            # Ищем в таблице Admin
            result = await session.execute(
                select(Admin).where(Admin.tg_id == int(user_id))
            )
            admin = result.scalar_one_or_none()

            # Возвращаем результат проверки
            return admin is not None
        except Exception as e:
            logging.error(f"Ошибка проверки админа: {e}")
            return False

# Состояние для FSM
class AdminSetup(StatesGroup):
    waiting_for_admin_id = State()

@dp.message(F.text == "➕ Добавить админа")
async def request_admin_id(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    await message.answer("Пришлите Telegram ID нового администратора:")
    await state.set_state(AdminSetup.waiting_for_admin_id)

@dp.message(AdminSetup.waiting_for_admin_id)
async def process_add_admin(message: Message, state: FSMContext):
    try:
        new_id = int(message.text)
        async with async_session() as session:
            session.add(Admin(tg_id=new_id, name="Добавлен через панель"))
            await session.commit()
        await message.answer(f"✅ Пользователь {new_id} теперь администратор!")
    except ValueError:
        await message.answer("❌ Ошибка: ID должен состоять только из цифр.")
    except Exception as e:
        await message.answer(f"❌ Ошибка базы данных: {e}")
    await state.clear()


# 1. Показать список всех админов
@dp.message(F.text == "👥 Список админов")
async def show_admins_list(message: Message):
    if not await is_admin(message.from_user.id): return

    async with async_session() as session:
        res = await session.execute(select(Admin))
        admins = res.scalars().all()

    if not admins:
        await message.answer("В базе нет дополнительных админов.")
        return

    await message.answer("<b>Действующие администраторы:</b>", parse_mode="HTML")

    for adm in admins:
        kb = InlineKeyboardBuilder()
        kb.button(text="🗑 Удалить доступ", callback_data=f"del_admin_{adm.id}")

        await message.answer(
            f"👤 ID: <code>{adm.tg_id}</code>\n📝 Заметка: {adm.name}",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )


# 2. Обработка удаления (Callback)
@dp.callback_query(F.data.startswith("del_admin_"))
async def process_delete_admin(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!", show_alert=True)
        return

    admin_db_id = int(callback.data.split("_")[2])

    async with async_session() as session:
        admin_to_del = await session.get(Admin, admin_db_id)
        if admin_to_del:
            await session.delete(admin_to_del)
            await session.commit()
            await callback.message.edit_text(f"✅ Админ (ID: {admin_to_del.tg_id}) успешно удален из системы.")
        else:
            await callback.answer("Ошибка: админ не найден.")


@dp.message(F.text == "🔐 Админ-панель")
async def admin_panel_entry(message: Message):
    if await is_admin(message.from_user.id):
        await message.answer("Добро пожаловать в панель управления!",
                             reply_markup=get_admin_main_kb())
    else:
        await message.answer("У вас нет прав доступа к этому разделу.")


# Функция для получения списка всех ID администраторов из базы
async def get_admin_ids():
    async with async_session() as session:
        # ИСПРАВЛЕНО: берем ID из таблицы Admin, а не User
        result = await session.execute(select(Admin.tg_id))
        return result.scalars().all()

# Универсальная функция уведомления всех админов
async def notify_admins(bot, text, reply_markup=None): # Должно быть так
    admin_ids = await get_admin_ids()
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

# Теперь любой из списка ADMIN_LIST сможет войти
# Список ID всех админов
@dp.callback_query(F.data == "admin_list")
async def show_admins_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id): return

    async with async_session() as session:
        # Получаем всех админов из базы
        result = await session.execute(select(Admin))
        admins = result.scalars().all()

    if not admins:
        return await callback.message.answer("Список администраторов пуст.")

    await callback.message.answer("<b>Действующие администраторы:</b>", parse_mode="HTML")

    for admin in admins:
        # Создаем кнопку удаления для каждого
        builder = InlineKeyboardBuilder()
        builder.button(text="🗑 Удалить доступ", callback_data=f"remove_admin_{admin.tg_id}")

        await callback.message.answer(
            f"👤 ID: <code>{admin.tg_id}</code>\n"
            f"📝 Заметка: {admin.note or 'Нет заметок'}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    await callback.answer()


@dp.message(F.text == "✉️ Письма (Рассылка)")
async def admin_mailing_menu(message: Message):
    # Используем вашу функцию проверки по базе данных
    if not await is_admin(message.from_user.id):
        return

    await message.answer(
        "📩 <b>Меню рассылки</b>\nВыберите тип отправки:",
        reply_markup=get_admin_mailing_kb(),
        parse_mode="HTML"
    )


@dp.message(F.text == "⬅️ Назад в админку")
async def back_to_admin(message: Message):
    # Техконтроль: проверяем права через базу данных
    if not await is_admin(message.from_user.id):
        return

    # Вызываем вход в админку (убедитесь, что функция admin_panel_entry существует)
    await admin_panel_entry(message)


@dp.message(F.text == "🔐 Админ-панель")
async def admin_panel_entry(message: Message):
    # Техконтроль: проверяем права через базу данных
    if not await is_admin(message.from_user.id):
        return # Если не админ, бот просто проигнорирует нажатие

    # Универсальное приветствие
    await message.answer(
        f"🤝 Добро пожаловать в панель управления, {message.from_user.first_name}!",
        reply_markup=get_admin_main_kb()
    )

# --- ЛОГИКА КАТАЛОГА С ФИЛЬТРОМ МОДЕРАЦИИ ---
@dp.callback_query(F.data.startswith("cat_"))
async def shops_grid_handler(callback: types.CallbackQuery):
    # 1. Защита от "протухших" кнопок
    try:
        await callback.answer()
    except Exception:
        # Если кнопка старая, просто игнорируем ошибку и идем дальше
        pass

    cat_id = int(callback.data.split("_")[1])

    async with async_session() as session:
        # Используем select для надежности
        result = await session.execute(select(Category).where(Category.id == cat_id))
        category = result.scalar_one_or_none()

        # Если категорию удалили, пока юзер смотрел на кнопку
        if not category:
            await callback.message.answer("❌ Эта категория больше не доступна.")
            return

        # Получаем только активные сайты (как вы и хотели)
        kb = await get_shops_grid_kb(cat_id, only_active=True)

    if not kb.inline_keyboard:
        await callback.message.answer(f"😔 В категории <b>{category.name}</b> пока нет проверенных ссылок.",
                                      parse_mode="HTML")
        return

    # Удаляем старое сообщение с категориями, чтобы не засорять чат
    try:
        await callback.message.delete()
    except Exception:
        pass  # Если сообщение уже удалено

    await callback.message.answer(
        f"🗳 <b>Раздел: {category.name}</b>\nВыберите бренд или магазин:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("shop_"))
async def show_specific_shop(callback: types.CallbackQuery):
    await callback.answer()
    shop_id = int(callback.data.split("_")[1])
    async with async_session() as session:
        shop = await session.get(SiteSetting, shop_id)

    text = (f"💎 <b>БРЕНД: {shop.name}</b>\n───────────────────\n"
            f"📝 {shop.description}\n\n📍 <i>Пришлите ссылку на товар, и я сделаю расчет!</i>")
    kb = get_shop_action_kb(shop.url, shop.category_id)

    if shop.logo_url:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(photo=shop.logo_url, caption=text, reply_markup=kb, parse_mode="HTML")
        except:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "back_to_cats")
async def back_to_cats(callback: types.CallbackQuery):
    await callback.answer()
    kb = await get_categories_kb()
    if callback.message.photo: await callback.message.delete()
    await callback.message.answer("📍 <b>Выберите категорию:</b>", reply_markup=kb, parse_mode="HTML")


# --- ПАРСИНГ И РАСЧЕТ (ИСПРАВЛЕННЫЙ БЛОК) ---
@dp.message(F.text.contains("http"), StateFilter("*"))
async def process_link(message: Message, state: FSMContext):
    await state.clear()
    urls = re.findall(r'(https?://[^\s]+)', message.text)
    if not urls: return

    wait_msg = await message.answer("🛠 <b>Минутку...</b> Проверяю цену и наличие...", parse_mode="HTML")

    product = await get_product_info(urls[0])

    try:
        clean_price = float(product.get('price', 0))
    except:
        clean_price = 0

    if "error" in product or clean_price == 0:
        await wait_msg.edit_text("⚠️ Не удалось распознать цену автоматически.\nМенеджер проверит ссылку вручную.")
        return

    # --- ФИНАНСОВАЯ КОРРЕКТИРОВКА (ТЕХКОНТРОЛЬ) ---
    currency = product.get('currency', 'USD')

    # Выбираем курс в зависимости от валюты сайта
    if currency == "UAH":
        rate = 1.0
    elif currency == "EUR":
        rate = await get_current_rate("eur_rate", 45.5)
    else:  # По умолчанию USD
        rate = await get_current_rate("usd_rate", 42.0)

    # Расчет: Цена * 1.20 (комиссия) * Курс (1.0 для гривны)
    total_uah = round((clean_price * 1.20) * rate, 2)
    fee_uah = round((clean_price * 0.20) * rate, 2)

    await state.update_data(p_title=product['title'], p_price=total_uah, p_url=urls[0], p_currency=currency)

    # Формируем текст (Курс показываем только если он не равен 1.0)
    rate_info = f"📈 Курс: {rate} грн\n" if rate > 1.0 else ""

    caption = (
        f"✅ <b>Товар найден!</b>\n\n"
        f"📦 <b>{product['title']}</b>\n"
        f"💰 Цена на сайте: {clean_price} {currency}\n"
        f"{rate_info}"
        f"───────────────────\n"
        f"💵 <b>Итого к оплате: {total_uah} грн</b>\n"
        f"<i>(Включая комиссию 20%: {fee_uah} грн)</i>\n\n"
        f"📍 Желаете добавить товар в корзину?"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 Добавить в корзину", callback_data="confirm_add")
    builder.button(text="🔎 Новый поиск", callback_data="back_to_cats")
    builder.adjust(1)

    await wait_msg.delete()
    if product.get('image'):
        await message.answer_photo(photo=product['image'], caption=caption, reply_markup=builder.as_markup(),
                                   parse_mode="HTML")
    else:
        await message.answer(caption, reply_markup=builder.as_markup(), parse_mode="HTML")


# --- ДОБАВЛЕНИЕ В КОРЗИНУ И ПАРАМЕТРЫ ---



@dp.message(OrderFlow.waiting_for_details)
async def save_to_cart_final(message: Message, state: FSMContext):
    data = await state.get_data()

    # ПРОВЕРКА: если данных нет (например, был перезапуск бота)
    if not data or 'p_title' not in data:
        await message.answer(
            "⚠️ <b>Данные заказа были утеряны (бот перезагрузился).</b>\n"
            "Пожалуйста, пришлите ссылку на товар еще раз.",
            parse_mode="HTML"
        )
        await state.clear()
        return

    details = message.text
    async with async_session() as session:
        try:
            new_item = CartItem(
                user_id=message.from_user.id,
                title=data['p_title'],
                price_uah=data['p_price'],
                size_details=details,
                url=data['p_url']
            )
            session.add(new_item)
            await session.commit()

            await message.answer(
                f"✅ <b>Добавлено в корзину!</b>\n\n"
                f"📦 {data['p_title']}\n"
                f"📝 Параметры: {details}\n\n"
                "Товар сохранен. Можете прислать новую ссылку или оформить заказ в 🛒 <b>Корзине</b>.",
                reply_markup=get_main_menu_kb(message.from_user.id == ADMIN_ID),
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Ошибка при сохранении в базу: {e}")
            await message.answer("❌ <b>Ошибка при сохранении.</b> Попробуйте позже.")
        finally:
            await state.clear()


# --- СНАЧАЛА САМА ФУНКЦИЯ МЕНЮ (Логика) ---
async def admin_stock_hub(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        # Теперь, после импорта, StockItem и StockCategory будут видны
        res_items = await session.execute(select(func.count(StockItem.id)))
        total_items = res_items.scalar() or 0

        res_cats = await session.execute(select(func.count(StockCategory.id)))
        total_cats = res_cats.scalar() or 0

    text = (
        "🏘 <b>Управление товарами в наличии</b>\n\n"
        f"📊 В магазине:\n"
        f"├ Категорий: <b>{total_cats}</b>\n"
        f"└ Товаров: <b>{total_items}</b>\n\n"
        "Выберите действие:"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📁 Создать категорию", callback_data="prod_cat_add")
    builder.button(text="➕ Добавить товар", callback_data="prod_add_start")
    builder.button(text="🏠 В админку", callback_data="admin_panel")
    builder.adjust(1)

    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# --- ЗАТЕМ ТРИГГЕР (Кнопка) ---
async def is_admin_check(tg_id: int) -> bool:
    async with async_session() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        user = res.scalar_one_or_none()
        return user.is_admin if user else False

# --- 1. АДМИН: Хаб управления (Triggered by Text) ---
@dp.message(F.text == "🏘 Товары в наличии", StateFilter("*"))
async def admin_stock_entry(message: Message, state: FSMContext):
    # Проверяем права
    if not await is_admin_check(message.from_user.id):
        # Если не админ — перекидываем функцию ниже (пользовательскую)
        return await user_stock_entry(message, state)

    await state.clear()
    async with async_session() as session:
        res_items = await session.execute(select(func.count(StockItem.id)))
        total_items = res_items.scalar() or 0
        res_cats = await session.execute(select(func.count(StockCategory.id)))
        total_cats = res_cats.scalar() or 0

    text = (
        "🏘 <b>ПАНЕЛЬ УПРАВЛЕНИЯ СКЛАДОМ</b>\n\n"
        f"📊 Всего категорий: <b>{total_cats}</b>\n"
        f"📦 Всего товаров: <b>{total_items}</b>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Список/Правка товаров", callback_data="admin_stock_list_0")
    builder.button(text="📁 Создать категорию", callback_data="prod_cat_add")
    builder.button(text="➕ Добавить товар", callback_data="prod_add_start")
    builder.button(text="🏠 В админку", callback_data="admin_panel")
    builder.adjust(1)

    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


async def user_stock_entry(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        # Запрос: Имя категории + количество активных товаров в ней
        res = await session.execute(
            select(
                StockCategory.id,
                StockCategory.name,
                func.count(StockItem.id).label('cnt')
            )
            .join(StockItem, StockItem.category_id == StockCategory.id, isouter=True)
            .where((StockItem.is_available == True) | (StockItem.id == None))
            .group_by(StockCategory.id)
        )
        categories = res.all()

    if not categories:
        return await message.answer("🏘 <b>Магазин пуст.</b> Мы скоро добавим новые товары!", parse_mode="HTML")

    text = "🏘 <b>КАТАЛОГ ТОВАРОВ</b>\n\nВыберите категорию:"
    builder = InlineKeyboardBuilder()

    for cat_id, name, count in categories:
        # Кнопка со счетчиком: "Обувь (5)"
        builder.button(text=f"{name} ({count})", callback_data=f"user_cat_{cat_id}_0")

    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")



# --- 2. АДМИН: Просмотр списка (Triggered by Callback) ---
# --- АДМИН: Просмотр и редактирование списка товаров ---
@dp.callback_query(F.data.startswith("admin_stock_list_"))
async def admin_stock_view(callback: CallbackQuery):
    # Извлекаем номер страницы из callback_data
    page = int(callback.data.split("_")[3])

    async with async_session() as session:
        # Получаем конкретный товар для этой страницы
        res = await session.execute(
            select(StockItem).order_by(StockItem.id).offset(page).limit(1)
        )
        item = res.scalar_one_or_none()

        # Считаем общее количество товаров в базе
        total_res = await session.execute(select(func.count(StockItem.id)))
        total = total_res.scalar() or 0

    if not item:
        return await callback.answer("📦 Товаров пока нет.")

    # --- ЛОГИКА ВАЛЮТЫ ---
    # Берем символ в зависимости от того, что сохранено в базе
    currency_symbol = "₴" if getattr(item, 'currency', 'USD') == "UAH" else "$"

    text = (
        f"🛠 <b>РЕДАКТИРОВАНИЕ ТОВАРА</b>\n\n"
        f"📝 Описание: {item.description}\n"
        f"📏 Размер: {item.size}\n"
        f"💰 Цена: <b>{item.price} {currency_symbol}</b>\n"  # <-- Исправлено на динамическую валюту
        f"───────────────────\n"
        f"📦 Товар {page + 1} из {total}"
    )

    builder = InlineKeyboardBuilder()
    # Кнопки редактирования конкретных полей
    builder.button(text="✏️ Изменить цену", callback_data=f"edit_price_{item.id}")
    builder.button(text="✏️ Изменить размер", callback_data=f"edit_size_{item.id}")
    builder.button(text="🗑 Удалить", callback_data=f"prod_del_{item.id}")
    builder.adjust(2, 1)  # Первые две кнопки в ряд, Удалить — под ними

    # Навигация (Стрелочки)
    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_stock_list_{page - 1}"))
    if page < total - 1:
        nav_btns.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_stock_list_{page + 1}"))

    if nav_btns:
        builder.row(*nav_btns)

    # Кнопка возврата в админ-меню магазина
    builder.row(InlineKeyboardButton(text="🏠 Назад в меню", callback_data="admin_stock_back"))

    await callback.message.delete()
    await callback.message.answer_photo(
        photo=item.photo_id,
        caption=text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# --- 3. ПОЛЬЗОВАТЕЛЬ: Список категорий (Triggered by Text) ---
@dp.message(F.text == "🛍 Товары в наличии")
async def user_shop_categories(message: Message):
    async with async_session() as session:
        # Получаем категории, где есть хотя бы один доступный товар
        res = await session.execute(
            select(StockCategory.id, StockCategory.name, func.count(StockItem.id))
            .join(StockItem, isouter=True)
            .where(StockItem.is_available == True)
            .group_by(StockCategory.id)
        )
        categories = res.all()

    if not categories:
        return await message.answer("🏘 Магазин пока пуст. Заходите позже!")

    text = "🏘 <b>КАТАЛОГ ТОВАРОВ</b>\n\nВыберите категорию, чтобы посмотреть вещи в наличии:"
    builder = InlineKeyboardBuilder()

    for cat_id, name, count in categories:
        builder.button(text=f"{name} ({count})", callback_data=f"user_cat_{cat_id}_0")

    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# --- 4. ПОЛЬЗОВАТЕЛЬ: Просмотр товара (Triggered by Callback) ---
@dp.callback_query(F.data == "back_to_shop_cats")
async def back_to_cats(callback: CallbackQuery, state: FSMContext):
    """Возврат к списку категорий"""
    await callback.message.delete()
    # Вызываем функцию категорий, которую мы определили ранее
    await user_shop_categories(callback.message, state)
    await callback.answer()

@dp.callback_query(F.data.startswith("user_cat_"))
async def user_view_items(callback: CallbackQuery):
    data = callback.data.split("_")
    cat_id, page = int(data[2]), int(data[3])

    async with async_session() as session:
        # Получаем товар
        res = await session.execute(
            select(StockItem).where(StockItem.category_id == cat_id, StockItem.is_available == True)
            .offset(page).limit(1)
        )
        item = res.scalar_one_or_none()

        # Получаем общее количество активных товаров в этой категории
        count_res = await session.execute(
            select(func.count(StockItem.id)).where(StockItem.category_id == cat_id, StockItem.is_available == True)
        )
        total = count_res.scalar()

    if not item:
        return await callback.answer("В этой категории пока пусто.")

    # --- ЛОГИКА ОПРЕДЕЛЕНИЯ ВАЛЮТЫ ---
    # Если в базе UAH — ставим ₴, иначе (USD или пусто) — ставим $
    currency_symbol = "₴" if getattr(item, 'currency', 'USD') == "UAH" else "$"

    text = (
        f"🏷 <b>{item.description}</b>\n\n"
        f"📏 Размер: <code>{item.size}</code>\n"
        f"💰 Цена: <b>{item.price} {currency_symbol}</b>\n"
        f"───────────────────\n"
        f"📦 Товар {page + 1} из {total}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="💳 КУПИТЬ", callback_data=f"shop_buy_{item.id}")

    # Формируем навигацию
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"user_cat_{cat_id}_{page - 1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"user_cat_{cat_id}_{page + 1}"))

    if nav:
        builder.row(*nav)

    # Кнопка возврата к категориям
    builder.row(InlineKeyboardButton(text="📂 К категориям", callback_data="back_to_shop_cats"))

    await callback.message.delete()
    await callback.message.answer_photo(
        photo=item.photo_id,
        caption=text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )



# --- КОРЗИНА И ОФОРМЛЕНИЕ ---

@dp.message(F.text == "🛒 Корзина", StateFilter("*"))
async def cart_handler(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        # Получаем товары текущего пользователя
        items = (await session.execute(
            select(CartItem).where(CartItem.user_id == message.from_user.id)
        )).scalars().all()

    # --- БЛОК "КРАСИВАЯ ПУСТАЯ КОРЗИНА" ---
    if not items:
        text = (
            "🛒 <b>Ваша корзина пуста</b>\n\n"
            "Похоже, вы еще ничего не выбрали. Самое время заглянуть в наши каталоги и найти что-то особенное! ✨\n\n"
            "<i>Используйте кнопку ниже, чтобы перейти к категориям.</i>"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="🛍 Перейти к покупкам", callback_data="back_to_cats")

        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        return
    # -------------------------------------

    # Логика отображения товаров (если они есть)
    text = "🛒 <b>Ваш список покупок:</b>\n\n"
    total = 0
    for i, item in enumerate(items, 1):
        text += f"{i}. <b>{item.title}</b>\n   📏 {item.size_details}\n   💰 {item.price_uah} грн\n\n"
        total += item.price_uah

    text += f"───────────────────\n<b>ИТОГО К ОПЛАТЕ: {round(total, 2)} грн</b>"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Оформить заказ", callback_data="checkout")
    builder.button(text="🗑 Очистить всё", callback_data="clear_cart")
    builder.adjust(1)

    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# Хендлер после получения ссылки
@dp.message(OrderState.waiting_for_url)
async def process_url(message: Message, state: FSMContext):
    await state.update_data(url=message.text)

    kb = InlineKeyboardBuilder()
    kb.button(text="👟 Обувь", callback_data="cat_shoes")
    kb.button(text="👕 Одежда", callback_data="cat_clothes")
    kb.adjust(2)

    await message.answer("Отлично! Что именно заказываем?", reply_markup=kb.as_markup())
    await state.set_state(OrderState.waiting_for_category)



# 2. Уточняем пол в зависимости от выбора (Муж/Жен или Мальчик/Девочка)
# Словари с размерами
# --- МУЖЧИНЫ (Обувь от US 4) ---
SHOE_MAN = [
    "US 4 / EU 36", "US 4.5 / EU 37", "US 5 / EU 37.5", "US 5.5 / EU 38",
    "US 6 / EU 38.5", "US 6.5 / EU 39", "US 7 / EU 40", "US 7.5 / EU 40.5",
    "US 8 / EU 41", "US 8.5 / EU 42", "US 9 / EU 42.5", "US 9.5 / EU 43",
    "US 10 / EU 44", "US 10.5 / EU 44.5", "US 11 / EU 45", "US 11.5 / EU 45.5",
    "US 12 / EU 46", "US 13 / EU 47.5", "US 14 / EU 48.5"
]

# --- ЖЕНЩИНЫ (Обувь от US 4) ---
SHOE_WOMAN = [
    "US 4 / EU 34.5", "US 4.5 / EU 35", "US 5 / EU 35.5", "US 5.5 / EU 36",
    "US 6 / EU 36.5", "US 6.5 / EU 37.5", "US 7 / EU 38", "US 7.5 / EU 38.5",
    "US 8 / EU 39", "US 8.5 / EU 40", "US 9 / EU 40.5", "US 9.5 / EU 41",
    "US 10 / EU 42", "US 10.5 / EU 42.5", "US 11 / EU 43"
]

# Одежду оставляем расширенную, как в прошлый раз
CLOTHES_MAN = ["S (44-46)", "M (48-50)", "L (52-54)", "XL (56-58)", "XXL (60-62)", "3XL (64-66)", "4XL (68-70)", "5XL (72+)"]
CLOTHES_WOMAN = ["XXS (32)", "XS (34)", "S (36-38)", "M (40-42)", "L (44-46)", "XL (48-50)", "XXL (52-54)", "3XL (56+)"]

# --- МАЛЬЧИКИ (с указанием роста) ---
SHOE_BOY = [
    "US 10C (27)", "US 11C (28.5)", "US 12C (30)", "US 13C (31)",
    "US 1Y (32)", "US 2Y (33.5)", "US 3Y (35)", "US 4Y (36)",
    "US 5Y (37.5)", "US 6Y (38.5)", "US 7Y (40)"
]
CLOTHES_BOY = [
    "86-92 (1-2 года)", "98-104 (3-4 года)", "110-116 (5-6 лет)",
    "122-128 (7-8 лет)", "134-140 (9-10 лет)", "146-152 (11-12 лет)", "158-164 (13-14 лет)"
]

# --- ДЕВОЧКИ (с указанием роста) ---
SHOE_GIRL = [
    "US 10C (27)", "US 11C (28.5)", "US 12C (30)", "US 13C (31)",
    "US 1Y (32)", "US 2Y (33.5)", "US 3Y (35)", "US 4Y (36)",
    "US 5Y (37.5)", "US 6Y (38.5)"
]
CLOTHES_GIRL = [
    "86-92 (1-2 года)", "98-104 (3-4 года)", "110-116 (5-6 лет)",
    "122-128 (7-8 лет)", "134-140 (9-10 лет)", "146-152 (11-12 лет)", "158-170 (13-15 лет)"
]


# Хендлер выбора пола (с учетом детей - Пункт 0)
# 1. Выбор категории (Обувь/Одежда)
@dp.callback_query(F.data == "confirm_add")
async def start_size_request(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="👟 Обувь", callback_data="ordercat_shoes")
    builder.button(text="👕 Одежда", callback_data="ordercat_clothes")
    builder.adjust(2)
    await callback.message.answer("Выберите категорию товара:", reply_markup=builder.as_markup())
    await state.set_state(OrderState.waiting_for_category)

# 2. Сохранение категории и выбор Взрослым/Детям
@dp.callback_query(OrderState.waiting_for_category)
async def process_category_selection(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(category=callback.data) # Сохраняем 'ordercat_shoes' или 'ordercat_clothes'
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Взрослым", callback_data="target_adult")
    kb.button(text="👶 Детское", callback_data="target_child")
    kb.adjust(2)
    await state.set_state(OrderState.waiting_for_gender)
    await callback.message.edit_text("Для кого этот товар?", reply_markup=kb.as_markup())

# 3. Уточнение пола (Ловим возраст)
@dp.callback_query(OrderState.waiting_for_gender, F.data.startswith("target_"))
async def process_target_selection(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    if callback.data == "target_child":
        kb.button(text="👦 Мальчик", callback_data="gender_boy")
        kb.button(text="👧 Девочка", callback_data="gender_girl")
    else:
        kb.button(text="👨 Мужское", callback_data="gender_man")
        kb.button(text="👩 Женское", callback_data="gender_woman")
    kb.adjust(2)
    await callback.message.edit_text("Уточните пол:", reply_markup=kb.as_markup())

# 4. Выбор страны (Ловим пол)
@dp.callback_query(OrderState.waiting_for_gender, F.data.startswith("gender_"))
async def process_final_gender(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(gender=callback.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇸 США", callback_data="country_us")
    kb.button(text="🇪🇺 Европа", callback_data="country_eu")
    kb.button(text="🇺🇦 Украина", callback_data="country_ua")
    kb.adjust(3)
    await state.set_state(OrderState.waiting_for_size_country)
    await callback.message.edit_text("📍 Выберите сетку размеров:", reply_markup=kb.as_markup())

# 5. Вывод размеров
@dp.callback_query(OrderState.waiting_for_size_country)
async def process_size_country(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    country = callback.data.replace("country_", "").upper()
    await state.update_data(size_country=country)

    data = await state.get_data()
    category = str(data.get("category", "")).lower()
    gender = str(data.get("gender", "")).lower()

    kb = InlineKeyboardBuilder()
    sizes = []

    # СТРОГАЯ СЕЛЕКЦИЯ СПИСКА
    if "man" in gender:
        sizes = SHOE_MAN if "shoe" in category else CLOTHES_MAN
    elif "woman" in gender:
        sizes = SHOE_WOMAN if "shoe" in category else CLOTHES_WOMAN
    elif "boy" in gender:
        sizes = SHOE_BOY if "shoe" in category else CLOTHES_BOY
    elif "girl" in gender:
        sizes = SHOE_GIRL if "shoe" in category else CLOTHES_GIRL

    # Генерация кнопок
    for s in sizes:
        kb.button(text=s, callback_data=f"sz_{s}")

    kb.button(text="⌨️ Свой вариант (нет в списке)", callback_data="sz_manual")

    # Для одежды (где текст длинный) делаем 1 в ряд, для обуви 2 в ряд
    kb.adjust(1 if "clothes" in category else 2)

    await state.set_state(OrderState.waiting_for_size)
    await callback.message.edit_text(
        f"✅ Сетка: {country}\nВыберите точный размер:",
        reply_markup=kb.as_markup()
    )

# 6. Финал размера -> Цвет
@dp.callback_query(OrderState.waiting_for_size, F.data.startswith("sz_"))
async def process_final_size_choice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    size = callback.data.replace("sz_", "")
    await state.update_data(size=size)
    await callback.message.edit_text(f"✅ Размер: {size}. Теперь напишите цвет:")
    await state.set_state(OrderState.waiting_for_color)


@dp.message(OrderState.waiting_for_color)
async def process_order_final(message: Message, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    color = message.text.strip()

    # 1. Словари-переводчики (ваша логика)
    cat_map = {"shoes": "👟 Обувь", "clothes": "👕 Одежда", "ordercat_shoes": "👟 Обувь", "ordercat_clothes": "👕 Одежда"}
    gender_map = {"gender_man": "👨 Мужской", "gender_woman": "👩 Женский", "gender_boy": "👦 Мальчик",
                  "gender_girl": "👧 Девочка"}

    category_label = cat_map.get(user_data.get("category"), "Товар")
    gender_label = gender_map.get(user_data.get("gender"), "Не указан")
    size_label = user_data.get("size", "Не указан")
    product_title = user_data.get("p_title", "Товар")
    total_price = user_data.get("p_price", 0)
    url = user_data.get("p_url", "#")
    db_details = f"{category_label} | {gender_label} | Разм: {size_label} | Цв: {color}"

    async with async_session() as session:
        try:
            # 2. ПОИСК ПОЛЬЗОВАТЕЛЯ (Учитываем ваш алиас User as User)
            # Мы ищем запись, где tg_id совпадает с ID того, кто пишет боту
            user_stmt = await session.execute(select(User).where(User.tg_id == message.from_user.id))
            db_user = user_stmt.scalar_one_or_none()

            # ТЕХКОНТРОЛЬ: Если юзер не найден, пробуем создать его "на лету" или выдать четкую ошибку
            if not db_user:
                return await message.answer(
                    "❌ <b>Ваш профиль не найден в БД!</b>\n\n"
                    "Скорее всего, база была очищена. Пожалуйста, введите команду /start и попробуйте оформить заказ снова.",
                    parse_mode="HTML"
                )

            # 3. СОЗДАНИЕ ЗАКАЗА
            new_order = Order(
                user_id=db_user.id,  # Привязываем к внутреннему ID
                url=url,
                title=product_title,
                size_details=db_details,
                price_uah=total_price,
                status="НОВЫЙ"
            )

            session.add(new_order)
            await session.commit()
            await session.refresh(new_order)  # Теперь ID заказа будет реальным (не 0)

            # 4. УВЕДОМЛЕНИЕ АДМИНАМ
            admin_report = (
                f"🔔 <b>НОВЫЙ ЗАКАЗ №{new_order.id}</b>\n"
                f"───────────────────\n"
                f"👤 <b>Клиент:</b> {message.from_user.full_name}\n"
                f"💰 <b>Сумма:</b> {total_price} грн\n"
                f"🔗 <a href='{url}'>Ссылка на товар</a>"
            )

            # Рассылка всем админам (используем ваш User для поиска админов)
            admins_res = await session.execute(select(User.tg_id).where(User.is_admin == True))
            for adm_id in admins_res.scalars().all():
                try:
                    await bot.send_message(adm_id, admin_report, parse_mode="HTML")
                except:
                    pass

            # 5. ФИНАЛЬНЫЙ ОТВЕТ КЛИЕНТУ
            await message.answer(
                f"✅ <b>ЗАКАЗ СФОРМИРОВАН</b>\n\n"
                f"📦 <b>Товар:</b> {product_title}\n"
                f"💰 <b>Сумма:</b> {total_price} грн\n\n"
                f"🚀 <i>Менеджер уже получил уведомление!</i>",
                parse_mode="HTML"
            )
            await state.clear()

        except Exception as e:
            await session.rollback()
            await message.answer(f"⚠️ Ошибка при сохранении: {e}")



@dp.callback_query(F.data == "checkout")
async def checkout_handler(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_tg = callback.from_user

    async with async_session() as session:
        # 1. Получаем товары из корзины
        result = await session.execute(
            select(CartItem).where(CartItem.user_id == user_tg.id)
        )
        cart_items = result.scalars().all()

        if not cart_items:
            await callback.message.answer("⚠️ <b>Ваша корзина пуста!</b>", parse_mode="HTML")
            return

        # 2. ПРОВЕРКА ПОЛЬЗОВАТЕЛЯ: получаем или создаем запись в User
        user_res = await session.execute(
            select(User).where(User.tg_id == user_tg.id)
        )
        db_user = user_res.scalar_one_or_none()

        # Если пользователя почему-то нет в таблице User, создаем его на лету
        if not db_user:
            db_user = User(tg_id=user_tg.id, full_name=user_tg.full_name, is_admin=False)
            session.add(db_user)
            await session.flush() # Получаем ID без коммита всей транзакции

        internal_user_id = db_user.id

        # 3. Создаем записи в таблице Order
        report_items = ""
        total_sum = 0

        for item in cart_items:
            new_order = Order(
                user_id=internal_user_id, # Привязка к внутренней базе
                title=item.title,
                price_uah=item.price_uah,
                url=item.url,
                size_details=item.size_details,
                status="NEW",
                currency="UAH"
            )
            session.add(new_order)

            report_items += (
                f"📦 <b>{item.title}</b>\n"
                f"📏 {item.size_details}\n"
                f"💰 {item.price_uah} грн\n\n"
            )
            total_sum += item.price_uah

        # 4. Очищаем корзину
        await session.execute(
            delete(CartItem).where(CartItem.user_id == user_tg.id)
        )

        await session.commit()

    # 5. Уведомление админов
    admin_report = (
        f"🚨 <b>НОВЫЙ ЗАКАЗ!</b>\n"
        f"👤 Клиент: {user_tg.full_name} (@{user_tg.username})\n"
        f"🆔 ID в базе: <code>{internal_user_id}</code>\n"
        f"───────────────────\n"
        f"{report_items}"
        f"💵 <b>ИТОГО: {round(total_sum, 2)} грн</b>"
    )

    await notify_admins(bot, admin_report)

    # 6. Ответ клиенту
    await callback.message.answer(
        "🎉 <b>Заказ оформлен!</b>\nМенеджер свяжется с вами в ближайшее время.",
        parse_mode="HTML"
    )
    await callback.message.delete()


@dp.callback_query(F.data == "clear_cart")
async def clear_cart_handler(callback: types.CallbackQuery):
    await callback.answer("Корзина очищена")
    async with async_session() as session:
        await session.execute(delete(CartItem).where(CartItem.user_id == callback.from_user.id))
        await session.commit()
    await callback.message.edit_text("🛒 <b>Корзина пуста.</b>")


# Исправленная функция меню для пользователя
@dp.message(F.text == "📋 Статус заказа")
async def show_my_orders_menu(message: Message):
    async with async_session() as session:
        u_res = await session.execute(select(User.id).where(User.tg_id == message.from_user.id))
        user_id = u_res.scalar()

        if not user_id: return

        # Считаем количество для каждой кнопки
        async def get_count(stat):
            res = await session.execute(
                select(func.count(Order.id)).where(Order.user_id == user_id, func.upper(Order.status) == stat)
            )
            return res.scalar() or 0

        c_new = await get_count("НОВЫЙ")
        c_way = await get_count("В ПУТИ")
        c_stock = await get_count("НА СКЛАДЕ")
        c_done = await get_count("ЗАВЕРШЕН")

    builder = InlineKeyboardBuilder()
    # callback_data должна строго соответствовать обработчику (с подчеркиваниями)
    builder.button(text=f"⏳ В обработке ({c_new})", callback_data="my_orders_НОВЫЙ")
    builder.button(text=f"🚚 В пути ({c_way})", callback_data="my_orders_В_ПУТИ")
    builder.button(text=f"📦 На складе ({c_stock})", callback_data="my_orders_НА_СКЛАДЕ")
    builder.button(text=f"✅ Завершенные ({c_done})", callback_data="my_orders_ЗАВЕРШЕН")
    builder.adjust(1)

    await message.answer(
        "🔎 <b>Мониторинг ваших заказов</b>\nВыберите категорию ниже:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


def get_admin_order_manage_kb(order_id: int):
    builder = InlineKeyboardBuilder()
    # Пункт 3: Выставить счет или отказать
    builder.button(text="💰 Выставить счет", callback_data=f"adm_invoice_{order_id}")
    builder.button(text="❌ Нет в наличии", callback_data=f"adm_cancel_{order_id}")
    # Пункт 5: Добавить трек выкупа (когда уже купили)
    builder.button(text="📦 Добавить трек-номер", callback_data=f"adm_track_{order_id}")

    builder.adjust(2)
    return builder.as_markup()


# Начинаем процесс выставления счета
@dp.callback_query(F.data.startswith("adm_invoice_"))
async def start_invoice_process(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[2]
    await state.update_data(current_order_id=order_id)
    await state.set_state(OrderProcessStates.waiting_for_invoice_sum)  # Используем созданный ранее стейт

    await callback.message.answer(f"Введите итоговую сумму для заказа №{order_id} (товар + ваш %):")
    await callback.answer()


# Принимаем сумму и отправляем счет клиенту
@dp.message(OrderProcessStates.waiting_for_invoice_sum)
async def process_invoice_send(message: Message, state: FSMContext, bot: Bot):
    # 1. ТЕХКОНТРОЛЬ ВВОДА: разрешаем точки, запятые и убираем лишнее
    raw_text = message.text.replace(",", ".").replace("грн", "").strip()

    try:
        amount = float(raw_text)  # Примет и 4000, и 4031.42
    except ValueError:
        return await message.answer("⚠️ Ошибка! Введите сумму числом (например: 4031.42)")

    data = await state.get_data()
    # Проверьте, какой ключ вы используете: inv_order_id или current_order_id
    oid = int(data.get('inv_order_id') or data.get('current_order_id'))

    # 2. РАБОТА С БАЗОЙ: обновляем статус и цену
    async with async_session() as session:
        order = await session.get(Order, oid)
        if not order:
            return await message.answer(f"❌ Заказ №{oid} не найден в базе.")

        order.price_uah = amount
        order.status = "ОЖИДАЕТ ОПЛАТЫ"  # Переводим в категорию "Неоплаченные"
        await session.commit()

        # Получаем данные клиента для отправки пуша
        user_res = await session.execute(select(User).where(User.id == order.user_id))
        user_tg_id = user_res.scalar().tg_id

    # 3. ФОРМИРУЕМ КНОПКИ ДЛЯ КЛИЕНТА
    kb = InlineKeyboardBuilder()
    kb.button(text="📸 Отправить чек", callback_data=f"user_pay_check_{oid}")
    kb.button(text="💳 Оплата онлайн (авто)", callback_data=f"user_pay_auto_{oid}")
    kb.adjust(1)  # Кнопки в столбик, чтобы на iPhone 13 было удобно нажимать

    # 4. ОТПРАВЛЯЕМ СЧЕТ КЛИЕНТУ В БОТ
    invoice_text = (
        f"💳 <b>Выставлен счет по заказу №{oid}</b>\n"
        f"───────────────────\n"
        f"📦 Товар: {order.title}\n"
        f"💰 К оплате: <b>{amount} грн</b>\n\n"
        f"<i>Выберите удобный способ оплаты ниже. Если платите на карту — пришлите фото чека.</i>"
    )

    try:
        await bot.send_message(
            user_tg_id,
            invoice_text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
        await message.answer(f"✅ Счет на {amount} грн отправлен клиенту. Заказ переведен в 'Неоплаченные'.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить уведомление клиенту: {e}")

    await state.clear()

@dp.callback_query(F.data.startswith("adm_track_"))
async def start_add_track(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[2]
    await state.update_data(current_order_id=order_id)
    await state.set_state(OrderProcessStates.waiting_for_track_number)
    await callback.message.answer(f"Введите трек-номер склада (США/Европа) для заказа №{order_id}:")


# 1. Вызываем ввод трека из списка заказов (кнопка в категории "ЖДЕТ ТРЕК")
@dp.callback_query(F.data.startswith("adm_set_track_"))
async def start_set_track(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[3]
    await state.update_data(track_order_id=order_id)
    await state.set_state(OrderProcessStates.waiting_for_track_number)
    await callback.message.answer(f"📝 Введите международный трек-номер для заказа №{order_id}:")
    await callback.answer()


# 2. Сохраняем трек в базу
@dp.message(OrderProcessStates.waiting_for_track_number)
async def process_track_number(message: Message, state: FSMContext):
    track_code = message.text.strip().upper()
    data = await state.get_data()
    oid = int(data['track_order_id'])

    async with async_session() as session:
        order = await session.get(Order, oid)
        order.track_number = track_code  # Убедитесь, что это поле есть в моделях SQLAlchemy
        order.status = "В ПУТИ"  # Теперь он официально едет!
        await session.commit()

        # Уведомляем клиента на его iPhone 13
        user_res = await session.execute(select(User.tg_id).where(User.id == order.user_id))
        user_tg_id = user_res.scalar()

    await message.answer(f"✅ Трек <code>{track_code}</code> присвоен заказу №{oid}. Статус изменен на 'В ПУТИ'.",
                         parse_mode="HTML")

    # Пуш клиенту
    await message.bot.send_message(
        user_tg_id,
        f"🚚 <b>Ваш заказ №{oid} отправлен магазином!</b>\nТрек-номер: <code>{track_code}</code>",
        parse_mode="HTML"
    )
    await state.clear()

@dp.callback_query(F.data.startswith("user_pay_check_"))
async def start_payment_confirmation(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[3]
    await state.update_data(active_order_id=order_id)
    await state.set_state(OrderProcessStates.waiting_for_receipt)

    await callback.message.answer(
        f"🧾 <b>Заказ №{order_id}</b>\n"
        "Пожалуйста, пришлите фото или скриншот чека об оплате.\n"
        "Я сразу передам его администратору на проверку.",
        parse_mode="HTML"
    )
    await callback.answer()


# Принимаем фото чека
@dp.message(OrderProcessStates.waiting_for_receipt, F.photo)
async def process_payment_receipt(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid = data.get('payment_order_id')
    photo_id = message.photo[-1].file_id

    # Клавиатура для всех админов
    admin_kb = InlineKeyboardBuilder()
    admin_kb.button(text="✅ Подтвердить оплату", callback_data=f"adm_pay_ok_{oid}")
    admin_kb.button(text="❌ Ошибка в чеке", callback_data=f"adm_pay_bad_{oid}")
    admin_kb.adjust(1)

    # 1. ПОЛУЧАЕМ ВСЕ ID АДМИНОВ
    async with async_session() as session:
        # Убедитесь, что в таблице User есть поле is_admin
        stmt = select(User.tg_id).where(User.is_admin == True)
        result = await session.execute(stmt)
        admin_ids = result.scalars().all()

    # 2. РАССЫЛКА ЧЕКА ВСЕЙ КОМАНДЕ
    if not admin_ids:
        # Если в базе пусто, бот отправит чек вам (вставьте свой ID для страховки)
        admin_ids = [message.from_user.id]

    for admin_id in admin_ids:
        try:
            await bot.send_photo(
                admin_id,
                photo=photo_id,
                caption=f"💰 <b>ПОЛУЧЕН ЧЕК К ЗАКАЗУ №{oid}</b>\n"
                        f"───────────────────\n"
                        f"👤 Клиент: {message.from_user.full_name}\n"
                        f"📱 TG: @{message.from_user.username or 'скрыт'}",
                reply_markup=admin_kb.as_markup(),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Не удалось отправить чек админу {admin_id}: {e}")

    await message.answer("✅ Чек отправлен на проверку админам. Ожидайте подтверждения.")
    await state.clear()
# Принимаем фото чека


@dp.callback_query(F.data.startswith("adm_pay_confirm_"))
async def confirm_payment_and_ask_track(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[3]

    # [SQLAlchemy: Статус заказа = "ВЫКУПЛЕНО"]

    await callback.message.answer(
        f"💳 Оплата заказа №{order_id} подтверждена!\n"
        "Теперь, когда вы выкупите товар на сайте, нажмите кнопку '📦 Добавить трек-номер' в управлении заказом."
    )

    # Уведомляем клиента на его iPhone 13
    # await bot.send_message(user_id, f"🎉 Ваш заказ №{order_id} успешно выкуплен! Статус: В ПУТИ.")
    await callback.answer()


# --- 1. КЛИЕНТ: Нажимает "Отправить чек за ВЕС" ---
@dp.callback_query(F.data.startswith("user_pay_weight_"))
async def user_start_weight_payment(callback: CallbackQuery, state: FSMContext):
    oid = callback.data.split("_")[3]
    await state.update_data(payment_order_id=oid)
    await state.set_state(OrderProcessStates.waiting_for_weight_receipt)

    await callback.message.answer("📸 Пожалуйста, отправьте фото чека об оплате ДОСТАВКИ (ВЕСА):")
    await callback.answer()


# --- 2. КЛИЕНТ: Отправляет фото чека за вес ---
@dp.message(OrderProcessStates.waiting_for_weight_receipt, F.photo)
async def process_weight_receipt_photo(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid = data['payment_order_id']
    photo_id = message.photo[-1].file_id

    # Кнопки для админов
    admin_kb = InlineKeyboardBuilder()
    admin_kb.button(text="✅ Подтвердить ВЕС", callback_data=f"adm_pay_weight_ok_{oid}")
    admin_kb.button(text="❌ Ошибка", callback_data=f"adm_pay_bad_{oid}")
    admin_kb.adjust(1)

    # Рассылка всем админам (используем ваш список ID)
    async with async_session() as session:
        stmt = select(User.tg_id).where(User.is_admin == True)
        admin_ids = (await session.execute(stmt)).scalars().all()

    for admin_id in admin_ids:
        try:
            await bot.send_photo(
                admin_id,
                photo=photo_id,
                caption=f"⚖️ <b>ОПЛАТА ЗА ВЕС!</b>\nЗаказ №{oid}\nКлиент: {message.from_user.full_name}",
                reply_markup=admin_kb.as_markup(),
                parse_mode="HTML"
            )
        except:
            pass

    await message.answer("✅ Чек за доставку отправлен. Ожидайте подтверждения и запроса данных на отправку.")
    await state.clear()


# --- 3. АДМИН: Подтверждает оплату веса и ЗАПРАШИВАЕТ РЕКВИЗИТЫ ---
@dp.callback_query(F.data.startswith("my_orders_"))
async def show_my_orders_by_category(callback: CallbackQuery):
    status_raw = callback.data.replace("my_orders_", "")
    status_db = status_raw.replace("_", " ").upper()

    titles = {
        "НОВЫЙ": "⏳ В обработке",
        "ОЖИДАЕТ ОПЛАТЫ": "💳 Ожидают оплаты",
        "В ПУТИ": "🚚 В пути",
        "НА СКЛАДЕ": "📦 На складе",
        "ЗАВЕРШЕН": "✅ Завершенные"
    }
    display_title = titles.get(status_db, status_db)

    async with async_session() as session:
        user_stmt = await session.execute(select(User.id).where(User.tg_id == callback.from_user.id))
        user_id = user_stmt.scalar()

        # --- ТЕХКОНТРОЛЬ: Регистронезависимый поиск ---
        if status_db == "ОЖИДАЕТ ОПЛАТЫ":
            # Ищем и обычные счета, и счета за вес, используя func.upper для надежности
            stmt = (
                select(Order)
                .where(
                    Order.user_id == user_id,
                    func.upper(Order.status).in_(["ОЖИДАЕТ ОПЛАТЫ", "ОЖИДАЕТ ОПЛАТЫ ВЕСА"])
                )
                .order_by(Order.created_at.desc())
            )
        else:
            stmt = (
                select(Order)
                .where(
                    Order.user_id == user_id,
                    func.upper(Order.status) == status_db
                )
                .order_by(Order.created_at.desc())
            )

        result = await session.execute(stmt)
        orders = result.scalars().all()

    if not orders:
        return await callback.answer(f"В категории '{display_title}' пока нет заказов", show_alert=True)

    await callback.answer()
    await callback.message.answer(f"📋 <b>{display_title}</b>", parse_mode="HTML")

    for o in orders:
        # Приводим статус к верхнему регистру для сравнения
        curr_status = o.status.upper() if o.status else ""

        # Определяем сумму и тип оплаты
        if "ВЕСА" in curr_status:
            current_sum = o.weight_invoice_amount or 0
            payment_type = "Доставка (ВЕС)"
        else:
            current_sum = o.price_uah or 0
            payment_type = "Товар"

        card_text = (
            f"🆔 <b>Заказ №{o.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛍 <b>Товар:</b> {o.title}\n"
            f"📐 <b>Детали:</b> {o.size_details or 'Не указаны'}\n"
            f"💰 <b>Сумма ({payment_type}):</b> <code>{current_sum}</code> грн\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Статус:</b> <code>{o.status}</code>"
        )

        builder = InlineKeyboardBuilder()

        # Логика кнопок оплаты
        if curr_status == "ОЖИДАЕТ ОПЛАТЫ":
            builder.button(text="📸 Отправить чек", callback_data=f"user_pay_check_{o.id}")
            builder.button(text="💳 Оплата онлайн (авто)", callback_data=f"user_pay_auto_{o.id}")
        elif curr_status == "ОЖИДАЕТ ОПЛАТЫ ВЕСА":
            builder.button(text="📸 Отправить чек за ВЕС", callback_data=f"user_pay_weight_{o.id}")

        if o.url and o.url.startswith("http"):
            builder.button(text="🔗 Ссылка на товар", url=o.url)

        builder.adjust(1)

        await callback.message.answer(
            card_text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

# 1. Добавить состояние в StatesGroup
# ИСПРАВЛЕНО: переименовали атрибут в waiting_for_support_msg
@dp.message(SupportState.waiting_for_support_msg)
async def support_send(message: Message, state: FSMContext, bot: Bot):
    user_info = f"👤 От: {message.from_user.full_name} (@{message.from_user.username})"
    admin_text = (
        f"📩 <b>Новое сообщение в поддержку!</b>\n\n"
        f"{user_info}\n\n"
        f"Текст: <i>{message.text}</i>"
    )

    # Рассылаем всем админам через вашу функцию ниже
    await notify_admins(bot, admin_text)

    await message.answer("✅ Ваше сообщение отправлено. Ожидайте ответа.")
    await state.clear()

# Хендлер, который ловит реквизиты от клиента
@dp.message(F.text, ~F.text.startswith("/")) # Любой текст, кроме команд
async def handle_customer_shipping_info(message: Message, bot: Bot):
    # Если пишет админ — просто игнорируем, чтобы не спамить
    if await is_admin(message.from_user.id):
        return

    # Берем ваш ID из настроек (чтобы уведомление пришло именно вам)
    from config import ADMIN_IDS
    admin_to_notify = ADMIN_IDS[0]

    # Формируем красивое уведомление для вас
    info_text = (
        f"📩 <b>ПОЛУЧЕНЫ РЕКВИЗИТЫ!</b>\n"
        f"👤 Клиент: {message.from_user.full_name}\n"
        f"🆔 TG ID: <code>{message.from_user.id}</code>\n"
        f"───────────────────\n"
        f"📝 <b>Данные для отправки:</b>\n"
        f"<i>{message.text}</i>"
    )

    try:
        # Шлем сообщение вам
        await bot.send_message(admin_to_notify, info_text, parse_mode="HTML")
        # Подтверждаем клиенту
        await message.answer(
            "✅ <b>Данные приняты!</b>\n"
            "Менеджер проверит информацию и подготовит ТТН. Ожидайте уведомление об отправке.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка пересылки реквизитов: {e}")

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

async def main():
    # 1. Настройка логирования (чтобы видеть всё в консоли)
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 2. Инициализация базы данных
    await init_db()

    # 3. Настройка бота с глобальным режимом HTML
    # Теперь не нужно в каждом message.answer писать parse_mode="HTML"
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # 4. РЕГИСТРАЦИЯ MIDDLEWARE (Ваш новый "пограничник")
    # Он будет проверять и регистрировать каждого пользователя автоматически
    dp.update.middleware(RegistrationMiddleware())

    # 5. Очистка очереди (drop_pending_updates=True)
    # Если бот был выключен, он проигнорирует все сообщения, присланные за это время,
    # и не начнет спамить ответами при включении
    await bot.delete_webhook(drop_pending_updates=True)

    # 6. Запуск опроса серверов
    print("🚀 Бот успешно запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("⭕️ Бот остановлен пользователем")