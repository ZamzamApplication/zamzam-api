import unittest
from datetime import datetime, timezone

from fastapi import HTTPException
from jose import jwt

from app.config import settings
from app.models import Tahfiz, TahfizStatus, User, UserRole, UserTahfizMembership
from app.routers.auth import (
    TenantContext,
    create_access_token,
    issue_refresh_token,
    refresh_token_hash,
    get_tenant_context,
    require_admin,
    require_tenant_admin,
)


def make_tahfiz(tahfiz_id: int = 1, status: TahfizStatus = TahfizStatus.active) -> Tahfiz:
    return Tahfiz(id=tahfiz_id, name=f"Tahfiz {tahfiz_id}", status=status)


def make_user(
    role: UserRole,
    *,
    user_id: int = 1,
    tahfiz_id: int | None = 1,
) -> User:
    return User(
        id=user_id,
        username=f"user-{user_id}",
        password_hash="not-used-in-contract-tests",
        role=role,
        tahfiz_id=tahfiz_id,
    )


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _TenantSession:
    def __init__(
        self,
        tahfiz_by_id: dict[int, Tahfiz],
        memberships: dict[tuple[int, int], UserTahfizMembership] | None = None,
    ):
        self.tahfiz_by_id = tahfiz_by_id
        self.memberships = memberships or {}
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        params = list(statement.compile().params.values())
        user_id = next((value for value in params if isinstance(value, int) and value == 1), None)
        tahfiz_ids = [value for value in params if isinstance(value, int) and value in self.tahfiz_by_id]
        tahfiz_id = tahfiz_ids[-1] if tahfiz_ids else None
        return self.memberships.get((user_id, tahfiz_id))

    async def execute(self, statement):
        self.statements.append(statement)
        tahfiz_id = next(
            (
                value
                for value in statement.compile().params.values()
                if isinstance(value, int) and value in self.tahfiz_by_id
            ),
            None,
        )
        return _ScalarResult(self.tahfiz_by_id.get(tahfiz_id))


class AccessTokenTests(unittest.TestCase):
    def test_access_token_contains_identity_role_and_future_expiry(self):
        token = create_access_token({
            "sub": "teacher",
            "role": UserRole.sheikh.value,
            "tahfiz_id": 7,
        })

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        self.assertEqual(payload["sub"], "teacher")
        self.assertEqual(payload["role"], "sheikh")
        self.assertEqual(payload["tahfiz_id"], 7)
        self.assertGreater(
            datetime.fromtimestamp(payload["exp"], timezone.utc),
            datetime.now(timezone.utc),
        )

    def test_refresh_tokens_are_random_and_only_hash_is_persisted(self):
        raw, session = issue_refresh_token(3, "device-install-0001", "Test phone")

        self.assertGreaterEqual(len(raw), 32)
        self.assertNotEqual(raw, session.token_hash)
        self.assertEqual(session.token_hash, refresh_token_hash(raw))
        self.assertEqual(session.user_id, 3)
        self.assertEqual(session.device_id, "device-install-0001")


class RoleContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_guard_accepts_tenant_and_platform_admins(self):
        tenant_admin = make_user(UserRole.admin)
        platform_admin = make_user(UserRole.super_admin, tahfiz_id=None)

        self.assertIs(await require_admin(tenant_admin), tenant_admin)
        self.assertIs(await require_admin(platform_admin), platform_admin)

    async def test_admin_guard_rejects_sheikh(self):
        with self.assertRaises(HTTPException) as raised:
            await require_admin(make_user(UserRole.sheikh))

        self.assertEqual(raised.exception.status_code, 403)

    async def test_tenant_admin_guard_rejects_sheikh_context(self):
        context = TenantContext(make_user(UserRole.sheikh), make_tahfiz())

        with self.assertRaises(HTTPException) as raised:
            await require_tenant_admin(context)

        self.assertEqual(raised.exception.status_code, 403)


class TenantContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_regular_user_cannot_select_tenant_without_membership(self):
        tenant_one = make_tahfiz(1)
        tenant_two = make_tahfiz(2)
        db = _TenantSession({1: tenant_one, 2: tenant_two})
        user = make_user(UserRole.admin, tahfiz_id=1)

        with self.assertRaises(HTTPException) as raised:
            await get_tenant_context(
                current_user=user,
                db=db,
                support_tahfiz_id=2,
            )

        self.assertEqual(raised.exception.status_code, 403)

    async def test_regular_user_can_select_explicit_membership(self):
        tenant_one = make_tahfiz(1)
        tenant_two = make_tahfiz(2)
        membership = UserTahfizMembership(
            id=8,
            user_id=1,
            tahfiz_id=2,
            role=UserRole.admin,
            is_active=True,
        )
        db = _TenantSession({1: tenant_one, 2: tenant_two}, {(1, 2): membership})

        context = await get_tenant_context(
            current_user=make_user(UserRole.admin, tahfiz_id=1),
            db=db,
            support_tahfiz_id=2,
        )

        self.assertEqual(context.tahfiz_id, 2)
        self.assertEqual(context.effective_role, UserRole.admin)

    async def test_revoked_membership_is_rejected_immediately(self):
        membership = UserTahfizMembership(
            id=8,
            user_id=1,
            tahfiz_id=2,
            role=UserRole.admin,
            is_active=False,
        )
        db = _TenantSession({2: make_tahfiz(2)}, {(1, 2): membership})

        with self.assertRaises(HTTPException) as raised:
            await get_tenant_context(
                current_user=make_user(UserRole.admin, tahfiz_id=1),
                db=db,
                support_tahfiz_id=2,
            )

        self.assertEqual(raised.exception.status_code, 403)

    async def test_super_admin_must_select_support_workspace(self):
        user = make_user(UserRole.super_admin, tahfiz_id=None)

        with self.assertRaises(HTTPException) as raised:
            await get_tenant_context(
                current_user=user,
                db=_TenantSession({1: make_tahfiz()}),
                support_tahfiz_id=None,
            )

        self.assertEqual(raised.exception.status_code, 400)

    async def test_inactive_tenant_is_rejected(self):
        suspended = make_tahfiz(1, TahfizStatus.suspended)

        with self.assertRaises(HTTPException) as raised:
            await get_tenant_context(
                current_user=make_user(UserRole.admin),
                db=_TenantSession({1: suspended}),
                support_tahfiz_id=None,
            )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "tahfiz_inactive")


if __name__ == "__main__":
    unittest.main()
