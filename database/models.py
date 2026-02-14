from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, BigInteger, Boolean, Text, func
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime

# --- ОСНОВА ---
class Base(DeclarativeBase):
    pass

# --- 1. ПОЛЬЗОВАТЕЛИ И АДМИНИСТРАЦИЯ ---

class User(Base):
    """Таблиця клієнтів та адміністраторів"""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True)
    username = Column(String, nullable=True)
    full_name = Column(String)
    is_admin = Column(Boolean, default=False)

    orders = relationship("Order", back_populates="user")

class Admin(Base):
    """Додаткова таблиця адмінів для внутрішнього управління"""
    __tablename__ = 'admins'
    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String)

# --- 2. ГЛОБАЛЬНЫЕ НАСТРОЙКИ ---

class GlobalSetting(Base):
    """Налаштування: курси валют, проксі, комісії"""
    __tablename__ = "global_settings"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Float, nullable=True)     # Для чисел (курс)
    value_str = Column(String, nullable=True) # Для тексту (проксі)

# --- 3. СКАНЕР АКЦИЙ И ПАРСИНГ САЙТОВ ---

class Category(Base):
    """Категорії для парсингу сайтів (Одяг, Косметика тощо)"""
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    shops = relationship("SiteSetting", back_populates="category", cascade="all, delete-orphan")

class SiteSetting(Base):
    """Налаштування парсингу для конкретних магазинів"""
    __tablename__ = "site_settings"
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"))
    name = Column(String, nullable=False)
    domain = Column(String, unique=True)
    url = Column(String)
    logo_url = Column(String, nullable=True)
    description = Column(String, nullable=True)
    name_selector = Column(String, nullable=True)
    price_selector = Column(String, nullable=True)
    image_selector = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    category = relationship("Category", back_populates="shops")

class Promotion(Base):
    """Знайдені акції через сканер"""
    __tablename__ = 'promotions'
    id = Column(Integer, primary_key=True)
    site_name = Column(String)
    title = Column(String)
    url = Column(String)
    image_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

# --- 4. ЗАКАЗЫ И КОРЗИНА ---

class Order(Base):
    """Замовлення користувачів на викуп"""
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    url = Column(String)
    title = Column(String, nullable=True)
    target_group = Column(String)
    size_details = Column(String, nullable=True)
    size_eu = Column(String, nullable=True)
    size_us = Column(String, nullable=True)
    size_ua = Column(String, nullable=True)
    price_valuta = Column(Float)
    currency = Column(String, default="USD")
    price_uah = Column(Float, nullable=True)
    weight_invoice_amount = Column(Float, nullable=True)
    status = Column(String, default="НОВЫЙ")
    track_number = Column(String, nullable=True)
    ttn = Column(String, nullable=True)
    shipping_details = Column(Text, nullable=True)
    admin_comment = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="orders")

class CartItem(Base):
    """Тимчасовий кошик для розрахунків"""
    __tablename__ = 'cart_items'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    title = Column(String)
    price_uah = Column(Float)
    size_details = Column(String)
    url = Column(String)

# --- 5. МАГАЗИН (ТОВАРЫ В НАЛИЧИИ) ---

class StockCategory(Base):
    """Категорії для товарів у наявності (Магазин)"""
    __tablename__ = 'stock_categories'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

    items = relationship("StockItem", back_populates="category", cascade="all, delete-orphan")

class StockItem(Base):
    """Товари, які фізично є в наявності"""
    __tablename__ = 'stock_items'
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey('stock_categories.id')) # ПРАВИЛЬНО: на stock_categories
    photo_id = Column(String)
    description = Column(Text)
    size = Column(String)
    price = Column(Float)
    is_available = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    category = relationship("StockCategory", back_populates="items") # ПРАВИЛЬНО: на StockCategory
     # НОВАЯ КОЛОНКА:
    currency = Column(String, default="UAH")
    is_available = Column(Boolean, default=1)


# --- 6. ТЕХНИЧЕСКИЕ И ПРОЧИЕ МОДЕЛИ ---

class SupportTicket(Base):
    """Звернення до підтримки"""
    __tablename__ = 'support_tickets'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    full_name = Column(String)
    message_text = Column(Text)
    is_answered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

# Модели Site и Item оставлены для совместимости, если они используются в коде
class Site(Base):
    __tablename__ = 'sites'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    url = Column(String)
    is_active = Column(Boolean, default=True)

class Item(Base):
    __tablename__ = 'items'
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey('categories.id'))
    title = Column(String)
    url = Column(String)
    icon = Column(String)
    is_active = Column(Boolean, default=True)