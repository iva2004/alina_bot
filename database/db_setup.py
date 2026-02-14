from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from database.models import Base

DB_URL = "sqlite+aiosqlite:///./bot_database.db"

engine = create_async_engine(DB_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        # Автоматически создаст таблицу admins и остальные
        await conn.run_sync(Base.metadata.create_all)
    print("✅ База данных готова к работе.")