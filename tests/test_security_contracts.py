import importlib
import os
import unittest
from unittest.mock import AsyncMock, patch

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import Response
from sqlalchemy import create_engine, inspect, text
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.integrations import validate_whatsend_url
from app.main import enforce_cookie_csrf
from app.routers.auth import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, set_web_session
from app.routers.management import validate_whatsend_setting_url


def request_for(path: str, method: str = "POST", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 443),
    })


async def ok_response(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


class CookieSessionTests(unittest.IsolatedAsyncioTestCase):
    def test_web_session_uses_httponly_and_csrf_cookie(self):
        response = Response()
        with patch.dict(os.environ, {"FLY_APP_NAME": "zamzam-api"}):
            set_web_session(response, "signed-token")

        cookies = response.headers.getlist("set-cookie")
        access_cookie = next(cookie for cookie in cookies if cookie.startswith(f"{ACCESS_COOKIE_NAME}="))
        csrf_cookie = next(cookie for cookie in cookies if cookie.startswith(f"{CSRF_COOKIE_NAME}="))
        self.assertIn("HttpOnly", access_cookie)
        self.assertIn("Secure", access_cookie)
        self.assertIn("SameSite=lax", access_cookie)
        self.assertNotIn("HttpOnly", csrf_cookie)
        self.assertIn("Secure", csrf_cookie)

    async def test_cookie_authenticated_mutation_requires_matching_csrf_header(self):
        request = request_for(
            "/tahfiz/settings",
            headers=[(b"cookie", f"{ACCESS_COOKIE_NAME}=token; {CSRF_COOKIE_NAME}=csrf".encode())],
        )

        response = await enforce_cookie_csrf(request, ok_response)

        self.assertEqual(response.status_code, 403)

    async def test_public_invitation_registration_is_csrf_exempt(self):
        request = request_for(
            "/invitations/register/public-token",
            headers=[(b"cookie", f"{ACCESS_COOKIE_NAME}=old-session".encode())],
        )

        response = await enforce_cookie_csrf(request, ok_response)

        self.assertEqual(response.status_code, 200)


class WhatSendUrlValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_integration_does_not_validate_inactive_url(self):
        validator = AsyncMock()
        with patch("app.routers.management.validate_whatsend_url", validator):
            await validate_whatsend_setting_url(False, "http://legacy.example/send")

        validator.assert_not_awaited()

    async def test_enabled_integration_validates_configured_url(self):
        validator = AsyncMock()
        with patch("app.routers.management.validate_whatsend_url", validator):
            await validate_whatsend_setting_url(True, "https://api.example.com/send")

        validator.assert_awaited_once_with("https://api.example.com/send")

    async def test_production_rejects_plain_http(self):
        with (
            patch.dict(os.environ, {"FLY_APP_NAME": "zamzam-api"}),
            patch.object(settings, "WHATSEND_ALLOWED_HOSTS", "api.example.com"),
        ):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                await validate_whatsend_url("http://api.example.com/send")

    async def test_rejects_hosts_outside_the_allowlist(self):
        with patch.object(settings, "WHATSEND_ALLOWED_HOSTS", "api.example.com"):
            with self.assertRaisesRegex(ValueError, "غير مسموح"):
                await validate_whatsend_url("https://attacker.example/send")

    async def test_rejects_private_dns_results(self):
        with (
            patch.object(settings, "WHATSEND_ALLOWED_HOSTS", "api.example.com"),
            patch("app.integrations.socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("10.0.0.8", 443)),
            ]),
        ):
            with self.assertRaisesRegex(ValueError, "شبكة داخلية"):
                await validate_whatsend_url("https://api.example.com/send")


class AuthHardeningMigrationTests(unittest.TestCase):
    def run_upgrade(self, connection) -> None:
        migration = importlib.import_module("migrations.versions.20260729_08_auth_hardening")
        original_op = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
        finally:
            migration.op = original_op

    def test_upgrades_an_existing_users_table(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            self.run_upgrade(connection)
            self.assertIn(
                "auth_version",
                {column["name"] for column in inspect(connection).get_columns("users")},
            )
            self.assertIn("auth_rate_limits", inspect(connection).get_table_names())
        engine.dispose()

    def test_is_idempotent_with_current_baseline_metadata(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, auth_version INTEGER NOT NULL DEFAULT 0)"
            ))
            connection.execute(text(
                "CREATE TABLE auth_rate_limits ("
                "key_hash VARCHAR(64) PRIMARY KEY, attempts INTEGER NOT NULL, "
                "window_started_at DATETIME NOT NULL, expires_at DATETIME NOT NULL)"
            ))
            self.run_upgrade(connection)
            self.assertIn("auth_rate_limits", inspect(connection).get_table_names())
        engine.dispose()
