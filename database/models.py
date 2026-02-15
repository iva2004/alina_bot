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
    tg_id = Column(BigInteger, unique=True, index=True) # Добавлен индекс для скорости
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)

    orders = relationship("Order", back_populates="user")

class Admin(Base):
    """Додаткова таблиця адмінів (Оставлена для совместимости)"""
    __tablename__ = 'admins'
    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=True)

# --- 2. ГЛОБАЛЬНЫЕ НАСТРОЙКИ ---

class GlobalSetting(Base):
    """Налаштування: курси валют, проксі, комісії"""
    __tablename__ = "global_settings"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Float, nullable=True)
    value_str = Column(String, nullable=True)

# --- 3. СКАНЕР АКЦИЙ И ПАРСИНГ САЙТОВ ---

class Category(Base):
    """Категорії для парсингу сайтів"""
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    shops = relationship("SiteSetting", back_populates="category", cascade="all, delete-orphan")

class SiteSetting(Base):
    """Налаштування парсингу для магазинів"""
    __tablename__ = "site_settings"
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"))
    name = Column(String, nullable=False)
    domain = Column(String, unique=True, nullable=True)
    url = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    description = Column(Text, nullable=True) # Изменено на Text для длинных описаний
    name_selector = Column(String, nullable=True)
    price_selector = Column(String, nullable=True)
    image_selector = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    category = relationship("Category", back_populates="shops")

class Promotion(Base):
    """Знайдені акції через сканер"""
    __tablename__ = 'promotions'
    id = Column(Integer, primary_key=True)
    site_name = Column(String, nullable=True)
    title = Column(String, nullable=True)
    url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

# --- 4. ЗАКАЗЫ И КОРЗИНА ---

class Order(Base):
    """Замовлення користувачів"""
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    url = Column(String, nullable=True)
    title = Column(String, nullable=True)
    target_group = Column(String, nullable=True)
    size_details = Column(String, nullable=True)
    size_eu = Column(String, nullable=True)
    size_us = Column(String, nullable=True)
    size_ua = Column(String, nullable=True)
    price_valuta = Column(Float, nullable=True)
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
    """Тимчасовий кошик"""
    __tablename__ = 'cart_items'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    title = Column(String, nullable=True)
    price_uah = Column(Float, nullable=True)
    size_details = Column(String, nullable=True)
    url = Column(String, nullable=True)

# --- 5. МАГАЗИН (ТОВАРЫ В НАЛИЧИИ) ---

class StockCategory(Base):
    """Категорії товарів у наявності"""
    __tablename__ = 'stock_categories'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

    items = relationship("StockItem", back_populates="category", cascade="all, delete-orphan")

class StockItem(Base):
    """Товари у наявності"""
    __tablename__ = 'stock_items'
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey('stock_categories.id'))
    photo_id = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    size = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    currency = Column(String, default="UAH") # Перенесено вверх для порядка
    is_available = Column(Boolean, default=True) # Исправлен дубликат
    created_at = Column(DateTime, default=func.now())

    category = relationship("StockCategory", back_populates="items")

# --- 6. ТЕХНИЧЕСКИЕ И ПРОЧИЕ МОДЕЛИ ---

class SupportTicket(Base):
    __tablename__ = 'support_tickets'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    full_name = Column(String, nullable=True)
    message_text = Column(Text)
    is_answered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

# Для совместимости со старым кодом
class Site(Base):
    __tablename__ = 'sites'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)
    url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

class Item(Base):
    __tablename__ = 'items'
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey('categories.id'))
    title = Column(String, nullable=True)
    url = Column(String, nullable=True)
    icon = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)