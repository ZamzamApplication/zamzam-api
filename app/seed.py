import logging

from passlib.context import CryptContext
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)


async def seed_data():
    username = settings.BOOTSTRAP_SUPERADMIN_USERNAME.strip()
    password = settings.BOOTSTRAP_SUPERADMIN_PASSWORD
    if not username and not password:
        return
    if not username or not password:
        raise RuntimeError(
            "Both BOOTSTRAP_SUPERADMIN_USERNAME and BOOTSTRAP_SUPERADMIN_PASSWORD are required"
        )
    if len(username) < 3 or len(password) < 12:
        raise RuntimeError(
            "Bootstrap super-admin username must be 3+ characters and password must be 12+ characters"
        )

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        if result.scalar_one_or_none():
            logger.info("Bootstrap super-admin already exists; no changes were made")
            return

        admin_user = User(
            username=username,
            password_hash=pwd_context.hash(password),
            role=UserRole.super_admin,
        )
        db.add(admin_user)
        await db.commit()
        logger.warning("Created the explicitly configured bootstrap super-admin account")
