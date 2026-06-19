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
        # — Session migration (already exists) —
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

        # — Add new columns to students table —
        result = await conn.execute(text("PRAGMA table_info(students)"))
        student_columns = {row[1] for row in result.fetchall()}
        if "birthday" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN birthday DATE"))
        if "profile_pic" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN profile_pic TEXT"))
        if "is_enrolled" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN is_enrolled BOOLEAN NOT NULL DEFAULT 1"))
        if "student_id" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN student_id VARCHAR(50)"))
        # — Create student_warnings table —
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='student_warnings'"
        ))
        if not result.scalar_one_or_none():
            await conn.execute(text("""
                CREATE TABLE student_warnings (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES students(id),
                    reason TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

        # — Create parent_phones table —
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='parent_phones'"
        ))
        if not result.scalar_one_or_none():
            await conn.execute(text("""
                CREATE TABLE parent_phones (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES students(id),
                    phone_number VARCHAR(20) NOT NULL,
                    parent_type VARCHAR(10) NOT NULL
                )
            """))

        # — Add registration_date to students table —
        result = await conn.execute(text("PRAGMA table_info(students)"))
        student_columns = {row[1] for row in result.fetchall()}
        if "registration_date" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN registration_date DATE"))

        # — Add notes to attendance table —
        result = await conn.execute(text("PRAGMA table_info(attendance)"))
        att_columns = {row[1] for row in result.fetchall()}
        if "notes" not in att_columns:
            await conn.execute(text("ALTER TABLE attendance ADD COLUMN notes TEXT"))

        # — Make attendance.student_id nullable —
        result = await conn.execute(text("PRAGMA table_info(attendance)"))
        att_columns = {row[1]: row for row in result.fetchall()}
        if "student_id" in att_columns and att_columns["student_id"][3] == 1:  # notnull == 1
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            await conn.execute(text("""
                CREATE TABLE attendance_new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    student_id INTEGER REFERENCES students(id),
                    status VARCHAR(20) NOT NULL DEFAULT 'غياب'
                )
            """))
            await conn.execute(text(
                "INSERT INTO attendance_new (id, session_id, student_id, status) "
                "SELECT id, session_id, student_id, status FROM attendance"
            ))
            await conn.execute(text("DROP TABLE attendance"))
            await conn.execute(text("ALTER TABLE attendance_new RENAME TO attendance"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))

        # — Add name column to parent_phones table —
        result = await conn.execute(text("PRAGMA table_info(parent_phones)"))
        parent_phone_columns = {row[1] for row in result.fetchall()}
        if "name" not in parent_phone_columns:
            await conn.execute(text("ALTER TABLE parent_phones ADD COLUMN name VARCHAR(100)"))

        # — Add sort_order to student_sheikhs table —
        result = await conn.execute(text("PRAGMA table_info(student_sheikhs)"))
        ss_columns = {row[1] for row in result.fetchall()}
        if "sort_order" not in ss_columns:
            await conn.execute(text("ALTER TABLE student_sheikhs ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"))

        # — Add sheikh_id to attendance table —
        result = await conn.execute(text("PRAGMA table_info(attendance)"))
        att_columns = {row[1]: row for row in result.fetchall()}
        if "sheikh_id" not in att_columns:
            await conn.execute(text("ALTER TABLE attendance ADD COLUMN sheikh_id INTEGER REFERENCES sheikhs(id)"))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate()
