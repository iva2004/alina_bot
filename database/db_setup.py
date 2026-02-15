from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from database.models import Base

# Путь к базе данных
DB_URL = "sqlite+aiosqlite:///./bot_database.db"

# 1. Настраиваем движок с оптимизацией под SQLite
engine = create_async_engine(
    DB_URL,
    echo=False,  # Поставьте True, если нужно видеть все SQL-запросы в консоли
    connect_args={"check_same_thread": False}  # Нужно для работы asyncio с SQLite
)

# 2. Создаем фабрику сессий
async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# 3. Функция инициализации базы
async def init_db():
    try:
        async with engine.begin() as conn:
            # Включаем режим WAL для предотвращения блокировок (database is locked)
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")

            # Создаем все таблицы, описанные в models.py (включая Admin, User и т.д.)
            await conn.run_sync(Base.metadata.create_all)

        print("✅ База данных успешно инициализирована и готова к работе.")
    except Exception as e:
        print(f"❌ Ошибка при инициализации базы данных: {e}")


# Полезная функция для закрытия всех соединений при выключении бота
async def close_db():
    await engine.dispose()
    print("🔌 Соединение с базой данных закрыто.")