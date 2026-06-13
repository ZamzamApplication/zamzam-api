from passlib.context import CryptContext
from sqlalchemy import select

from app.database import async_session
from app.models import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def seed_data():
    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            return

        admin_user = User(
            username="admin",
            hashed_password=pwd_context.hash("admin123"),
            role=UserRole.admin,
        )
        db.add(admin_user)
        await db.commit()
