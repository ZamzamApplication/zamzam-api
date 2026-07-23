from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def migrate_legacy_circle_names():
    """Promote the legacy Circle tenant boundary to Tahfiz before ORM startup."""
    async with engine.begin() as conn:
        tables = {
            row[0]
            for row in (await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ))).fetchall()
        }
        if "circles" in tables and "tahfiz" not in tables:
            await conn.execute(text("ALTER TABLE circles RENAME TO tahfiz"))

        for table_name in ("sheikhs", "sessions"):
            if table_name not in tables:
                continue
            columns = {
                row[1]
                for row in (await conn.execute(text(f"PRAGMA table_info({table_name})"))).fetchall()
            }
            if "circle_id" in columns and "tahfiz_id" not in columns:
                await conn.execute(text(
                    f"ALTER TABLE {table_name} RENAME COLUMN circle_id TO tahfiz_id"
                ))


async def migrate():
    async with engine.begin() as conn:
        # — Session migration (already exists) —
        result = await conn.execute(text("PRAGMA table_info(sessions)"))
        columns = {row[1] for row in result.fetchall()}
        if "circle_id" not in columns and "tahfiz_id" not in columns:
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            await conn.execute(text("""
                CREATE TABLE sessions_new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    tahfiz_id INTEGER NOT NULL DEFAULT 1 REFERENCES tahfiz(id),
                    is_confirmed BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text(
                "INSERT INTO sessions_new (id, date, tahfiz_id, is_confirmed, created_at) "
                "SELECT id, date, 1, is_confirmed, created_at FROM sessions"
            ))
            await conn.execute(text("DROP TABLE sessions"))
            await conn.execute(text("ALTER TABLE sessions_new RENAME TO sessions"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        if "version" not in columns:
            await conn.execute(text("ALTER TABLE sessions ADD COLUMN version INTEGER NOT NULL DEFAULT 0"))
        if "reopened_at" not in columns:
            await conn.execute(text("ALTER TABLE sessions ADD COLUMN reopened_at DATETIME"))
        if "reopened_reason" not in columns:
            await conn.execute(text("ALTER TABLE sessions ADD COLUMN reopened_reason VARCHAR(500)"))
        if "reopened_by_id" not in columns:
            await conn.execute(text("ALTER TABLE sessions ADD COLUMN reopened_by_id INTEGER REFERENCES users(id)"))

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
        if "registration_date" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN registration_date DATE"))
        if "tahfiz_id" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN tahfiz_id INTEGER REFERENCES tahfiz(id)"))
            if "sheikh_id" in student_columns:
                await conn.execute(text("""
                    UPDATE students
                    SET tahfiz_id = (
                        SELECT sheikhs.tahfiz_id FROM sheikhs WHERE sheikhs.id = students.sheikh_id
                    )
                    WHERE sheikh_id IS NOT NULL
                """))
            await conn.execute(text("""
                UPDATE students
                SET tahfiz_id = (
                    SELECT sessions.tahfiz_id
                    FROM attendance
                    JOIN sessions ON sessions.id = attendance.session_id
                    WHERE attendance.student_id = students.id
                    ORDER BY sessions.date DESC
                    LIMIT 1
                )
                WHERE tahfiz_id IS NULL
            """))

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

        # — Add notes to attendance table —
        result = await conn.execute(text("PRAGMA table_info(attendance)"))
        att_columns = {row[1] for row in result.fetchall()}
        if "notes" not in att_columns:
            await conn.execute(text("ALTER TABLE attendance ADD COLUMN notes TEXT"))
        if "tahfiz_id" not in att_columns:
            await conn.execute(text("ALTER TABLE attendance ADD COLUMN tahfiz_id INTEGER REFERENCES tahfiz(id)"))
            await conn.execute(text("""
                UPDATE attendance
                SET tahfiz_id = (
                    SELECT sessions.tahfiz_id FROM sessions WHERE sessions.id = attendance.session_id
                )
            """))
        if "sheikh_id" not in att_columns:
            await conn.execute(text("ALTER TABLE attendance ADD COLUMN sheikh_id INTEGER REFERENCES sheikhs(id)"))

        # SQLAlchemy's former Enum mapping stored enum member names in SQLite.
        # Attendance statuses are now tenant-configurable strings, so promote
        # those legacy keys to the Arabic labels users have always seen.
        await conn.execute(text("""
            UPDATE attendance
            SET status = CASE status
                WHEN 'present' THEN 'حاضر'
                WHEN 'absent' THEN 'غياب'
                WHEN 'excused' THEN 'غياب بعذر'
                WHEN 'not_applicable' THEN 'لا ينطبق'
                ELSE status
            END
            WHERE status IN ('present', 'absent', 'excused', 'not_applicable')
        """))

        # — Add notes to excused weekdays —
        result = await conn.execute(text("PRAGMA table_info(excused_weekdays)"))
        excused_weekday_columns = {row[1] for row in result.fetchall()}
        if excused_weekday_columns and "note" not in excused_weekday_columns:
            await conn.execute(text("ALTER TABLE excused_weekdays ADD COLUMN note TEXT"))

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
                    sheikh_id INTEGER REFERENCES sheikhs(id),
                    tahfiz_id INTEGER REFERENCES tahfiz(id),
                    status VARCHAR(20) NOT NULL DEFAULT 'غياب',
                    notes TEXT
                )
            """))
            await conn.execute(text(
                "INSERT INTO attendance_new (id, session_id, student_id, sheikh_id, tahfiz_id, status, notes) "
                "SELECT id, session_id, student_id, sheikh_id, tahfiz_id, status, notes FROM attendance"
            ))
            await conn.execute(text("DROP TABLE attendance"))
            await conn.execute(text("ALTER TABLE attendance_new RENAME TO attendance"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))

        # — Add name column to parent_phones table —
        result = await conn.execute(text("PRAGMA table_info(parent_phones)"))
        parent_phone_columns = {row[1] for row in result.fetchall()}
        if "name" not in parent_phone_columns:
            await conn.execute(text("ALTER TABLE parent_phones ADD COLUMN name VARCHAR(100)"))

        # — Add sheikh_id to attendance table —
        result = await conn.execute(text("PRAGMA table_info(attendance)"))
        att_columns = {row[1]: row for row in result.fetchall()}
        if "sheikh_id" not in att_columns:
            await conn.execute(text("ALTER TABLE attendance ADD COLUMN sheikh_id INTEGER REFERENCES sheikhs(id)"))

        # — Ensure users table has password_hash column (rename from hashed_password if needed) —
        result = await conn.execute(text("PRAGMA table_info(users)"))
        user_columns = {row[1] for row in result.fetchall()}
        if "hashed_password" in user_columns and "password_hash" not in user_columns:
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            await conn.execute(text("""
                CREATE TABLE users_new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL DEFAULT '',
                    role VARCHAR(10) NOT NULL DEFAULT 'admin',
                    sheikh_id INTEGER REFERENCES sheikhs(id)
                )
            """))
            await conn.execute(text(
                "INSERT INTO users_new (id, username, password_hash, role, sheikh_id) "
                "SELECT id, username, hashed_password, role, sheikh_id FROM users"
            ))
            await conn.execute(text("DROP TABLE users"))
            await conn.execute(text("ALTER TABLE users_new RENAME TO users"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        elif "password_hash" not in user_columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NOT NULL DEFAULT ''"))
        if "is_active" not in user_columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
        if "tahfiz_id" not in user_columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN tahfiz_id INTEGER REFERENCES tahfiz(id)"))
            await conn.execute(text("""
                UPDATE users
                SET tahfiz_id = (
                    SELECT sheikhs.tahfiz_id FROM sheikhs WHERE sheikhs.id = users.sheikh_id
                )
                WHERE sheikh_id IS NOT NULL
            """))
        if "default_tahfiz_id" not in user_columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN default_tahfiz_id INTEGER REFERENCES tahfiz(id)"))
        # Legacy tenant administrators were not necessarily linked to a
        # sheikh, so derive their workspace from the original single tenant.
        await conn.execute(text("""
            UPDATE users
            SET tahfiz_id = (SELECT id FROM tahfiz ORDER BY id LIMIT 1)
            WHERE tahfiz_id IS NULL AND role = 'admin' AND username != 'admin'
        """))
        await conn.execute(text(
            "UPDATE users SET role = 'super_admin' WHERE username = 'admin' AND tahfiz_id IS NULL"
        ))
        await conn.execute(text("""
            UPDATE users
            SET default_tahfiz_id = tahfiz_id
            WHERE default_tahfiz_id IS NULL AND tahfiz_id IS NOT NULL
        """))

        # — Promote one-user/one-Tahfiz access to explicit memberships —
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_tahfiz_memberships (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                tahfiz_id INTEGER NOT NULL REFERENCES tahfiz(id),
                role VARCHAR(20) NOT NULL,
                sheikh_id INTEGER REFERENCES sheikhs(id),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_by_id INTEGER REFERENCES users(id),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_user_tahfiz_membership UNIQUE (user_id, tahfiz_id)
            )
        """))
        await conn.execute(text("""
            INSERT OR IGNORE INTO user_tahfiz_memberships
                (user_id, tahfiz_id, role, sheikh_id, is_active, created_at)
            SELECT id, tahfiz_id, role, sheikh_id, is_active, CURRENT_TIMESTAMP
            FROM users
            WHERE tahfiz_id IS NOT NULL AND role IN ('admin', 'sheikh')
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_tahfiz_memberships_user_id "
            "ON user_tahfiz_memberships(user_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_tahfiz_memberships_tahfiz_id "
            "ON user_tahfiz_memberships(tahfiz_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_tahfiz_memberships_tahfiz_role "
            "ON user_tahfiz_memberships(tahfiz_id, role, is_active)"
        ))

        # — Single-use, expiring Tahfiz invitations —
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tahfiz_invitations (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                tahfiz_id INTEGER NOT NULL REFERENCES tahfiz(id),
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                role VARCHAR(20) NOT NULL,
                sheikh_id INTEGER REFERENCES sheikhs(id),
                created_by_id INTEGER NOT NULL REFERENCES users(id),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                used_at DATETIME,
                used_by_id INTEGER REFERENCES users(id),
                revoked_at DATETIME
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tahfiz_invitations_token_hash "
            "ON tahfiz_invitations(token_hash)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tahfiz_invitations_tahfiz_status "
            "ON tahfiz_invitations(tahfiz_id, used_at, revoked_at, expires_at)"
        ))

        # — Migrate sheikh_id + sort_order from student_sheikhs to students —
        result = await conn.execute(text("PRAGMA table_info(students)"))
        student_columns = {row[1] for row in result.fetchall()}
        if "sheikh_id" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN sheikh_id INTEGER REFERENCES sheikhs(id)"))
        if "sort_order" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"))

        # Check if student_sheikhs table exists and migrate data
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='student_sheikhs'"
        ))
        if result.scalar_one_or_none():
            await conn.execute(text("""
                UPDATE students SET
                    sheikh_id = (
                        SELECT ss.sheikh_id FROM student_sheikhs ss
                        WHERE ss.student_id = students.id AND ss.end_date IS NULL
                    ),
                    sort_order = (
                        SELECT ss.sort_order FROM student_sheikhs ss
                        WHERE ss.student_id = students.id AND ss.end_date IS NULL
                    )
                WHERE EXISTS (
                    SELECT 1 FROM student_sheikhs ss
                    WHERE ss.student_id = students.id AND ss.end_date IS NULL
                )
            """))
            await conn.execute(text("DROP TABLE student_sheikhs"))
        await conn.execute(text("""
            UPDATE students
            SET tahfiz_id = (
                SELECT sheikhs.tahfiz_id FROM sheikhs WHERE sheikhs.id = students.sheikh_id
            )
            WHERE tahfiz_id IS NULL AND sheikh_id IS NOT NULL
        """))

        # — Migrate is_enrolled → status on students —
        result = await conn.execute(text("PRAGMA table_info(students)"))
        student_columns = {row[1] for row in result.fetchall()}
        if "is_enrolled" in student_columns and "status" not in student_columns:
            await conn.execute(text("ALTER TABLE students ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'مقيد'"))
            await conn.execute(text("""
                UPDATE students SET status = 'مقيد' WHERE is_enrolled = 1
            """))
            await conn.execute(text("""
                UPDATE students SET status = 'غير مقيد' WHERE is_enrolled = 0
            """))
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            # Recreate table without is_enrolled
            await conn.execute(text("""
                CREATE TABLE students_new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    phone VARCHAR(20),
                    student_id VARCHAR(50),
                    birthday DATE,
                    profile_pic TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'مقيد',
                    registration_date DATE,
                    sheikh_id INTEGER REFERENCES sheikhs(id),
                    tahfiz_id INTEGER REFERENCES tahfiz(id),
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
            """))
            await conn.execute(text("""
                INSERT INTO students_new (id, name, phone, student_id, birthday, profile_pic, status, registration_date, sheikh_id, tahfiz_id, sort_order)
                SELECT id, name, phone, student_id, birthday, profile_pic, status, registration_date, sheikh_id, tahfiz_id, sort_order FROM students
            """))
            await conn.execute(text("DROP TABLE students"))
            await conn.execute(text("ALTER TABLE students_new RENAME TO students"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))

        # — Add whatsapp_group_id to sheikhs —
        result = await conn.execute(text("PRAGMA table_info(sheikhs)"))
        sheikh_columns = {row[1] for row in result.fetchall()}
        if "whatsapp_group_id" not in sheikh_columns:
            await conn.execute(text("ALTER TABLE sheikhs ADD COLUMN whatsapp_group_id VARCHAR(255)"))

        # — Promote legacy organization settings to Tahfiz tenancy —
        result = await conn.execute(text("PRAGMA table_info(tahfiz)"))
        tahfiz_columns = {row[1] for row in result.fetchall()}
        if "max_warnings" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN max_warnings INTEGER NOT NULL DEFAULT 3"))
        if "week_start_day" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN week_start_day INTEGER NOT NULL DEFAULT 6"))
        if "month_start_day" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN month_start_day INTEGER NOT NULL DEFAULT 1"))
        if "attendance_statuses" not in tahfiz_columns:
            default_statuses = '["حاضر", "غياب", "غياب بعذر", "لا ينطبق"]'
            await conn.execute(text(
                f"ALTER TABLE tahfiz ADD COLUMN attendance_statuses TEXT NOT NULL DEFAULT '{default_statuses}'"
            ))
        if "contact_phone" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN contact_phone VARCHAR(20)"))
        if "status" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"))
        if "owner_user_id" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN owner_user_id INTEGER"))
        if "approved_by_id" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN approved_by_id INTEGER"))
        if "approved_at" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN approved_at DATETIME"))
        if "status_reason" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN status_reason VARCHAR(255)"))
        if "whatsend_api_url" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN whatsend_api_url VARCHAR(500)"))
        if "whatsend_groups_url" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN whatsend_groups_url VARCHAR(500)"))
        if "whatsend_api_key_encrypted" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN whatsend_api_key_encrypted TEXT"))
        if "created_at" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"))
        if "progress_tracking_enabled" not in tahfiz_columns:
            await conn.execute(text("ALTER TABLE tahfiz ADD COLUMN progress_tracking_enabled BOOLEAN NOT NULL DEFAULT 0"))
        await conn.execute(text("UPDATE tahfiz SET name = 'زمزم' WHERE name = 'دار زمزم'"))
        await conn.execute(text("""
            UPDATE tahfiz
            SET owner_user_id = (
                SELECT users.id
                FROM users
                WHERE users.tahfiz_id = tahfiz.id AND users.role = 'admin'
                ORDER BY users.id
                LIMIT 1
            )
            WHERE owner_user_id IS NULL
        """))

        # — Add tenant ownership to saved filters —
        result = await conn.execute(text("PRAGMA table_info(saved_filters)"))
        saved_filter_columns = {row[1] for row in result.fetchall()}
        if saved_filter_columns and "tahfiz_id" not in saved_filter_columns:
            await conn.execute(text("ALTER TABLE saved_filters ADD COLUMN tahfiz_id INTEGER REFERENCES tahfiz(id)"))
            await conn.execute(text("""
                UPDATE saved_filters
                SET tahfiz_id = (
                    SELECT users.tahfiz_id FROM users WHERE users.id = saved_filters.user_id
                )
            """))

        # — Add warning_number, sent, sent_at to student_warnings —
        result = await conn.execute(text("PRAGMA table_info(student_warnings)"))
        warning_columns = {row[1] for row in result.fetchall()}
        if "warning_number" not in warning_columns:
            await conn.execute(text("ALTER TABLE student_warnings ADD COLUMN warning_number INTEGER NOT NULL DEFAULT 1"))
        if "sent" not in warning_columns:
            await conn.execute(text("ALTER TABLE student_warnings ADD COLUMN sent BOOLEAN NOT NULL DEFAULT 0"))
        if "sent_at" not in warning_columns:
            await conn.execute(text("ALTER TABLE student_warnings ADD COLUMN sent_at DATETIME"))

        # — Drop circle_schedules table if it exists —
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='circle_schedules'"
        ))
        if result.scalar_one_or_none():
            await conn.execute(text("DROP TABLE circle_schedules"))

        # Repair legacy duplicates before enforcing write-time invariants.
        await conn.execute(text("""
            DELETE FROM attendance
            WHERE student_id IS NOT NULL
              AND id NOT IN (
                SELECT MAX(id)
                FROM attendance
                WHERE student_id IS NOT NULL
                GROUP BY session_id, student_id
              )
        """))
        await conn.execute(text("""
            DELETE FROM excused_weekdays
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM excused_weekdays
                GROUP BY student_id, weekday
            )
        """))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_session_student "
            "ON attendance(session_id, student_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_attendance_tahfiz_session "
            "ON attendance(tahfiz_id, session_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_sessions_tahfiz_confirmed_date "
            "ON sessions(tahfiz_id, is_confirmed, date)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_students_tahfiz_sheikh_status_order "
            "ON students(tahfiz_id, sheikh_id, status, sort_order)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_student_warnings_student_created "
            "ON student_warnings(student_id, created_at)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_excused_weekday_student_day "
            "ON excused_weekdays(student_id, weekday)"
        ))


async def init_db():
    await migrate_legacy_circle_names()
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
    await migrate()
