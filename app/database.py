from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def migrate():
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(sessions)"))
        columns = {row[1] for row in result.fetchall()}
        if "circle_id" not in columns:
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            await conn.execute(text("""
                CREATE TABLE sessions_new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    circle_id INTEGER NOT NULL DEFAULT 1 REFERENCES circles(id),
                    is_confirmed BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text(
                "INSERT INTO sessions_new (id, date, circle_id, is_confirmed, created_at) "
                "SELECT id, date, 1, is_confirmed, created_at FROM sessions"
            ))
            await conn.execute(text("DROP TABLE sessions"))
            await conn.execute(text("ALTER TABLE sessions_new RENAME TO sessions"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate()
