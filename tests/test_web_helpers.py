from __future__ import annotations

import os
import time
import unittest

import jwt

from meme_collector_app.core.config import get_settings
from meme_collector_app.web import auth
from meme_collector_app.web.schedule import (
    build_cron_from_form,
    cron_to_schedule_view,
    validate_cron,
)
from tests.helpers import TempDatabaseMixin


class WebHelperTests(TempDatabaseMixin, unittest.TestCase):
    def test_jwt_round_trip_and_bad_token(self) -> None:
        settings = get_settings()
        token = auth.create_access_token("admin", settings)
        self.assertEqual(auth.decode_access_token(token, settings), "admin")
        self.assertIsNone(auth.decode_access_token(token + "bad", settings))

        wrong_subject = jwt.encode(
            {"sub": "other", "exp": int(time.time()) + 60},
            auth.jwt_secret(settings),
            algorithm="HS256",
        )
        self.assertIsNone(auth.decode_access_token(wrong_subject, settings))

        expired = jwt.encode(
            {"sub": "admin", "exp": int(time.time()) - 60},
            auth.jwt_secret(settings),
            algorithm="HS256",
        )
        self.assertIsNone(auth.decode_access_token(expired, settings))

    def test_auth_cookie_flags(self) -> None:
        from starlette.responses import Response

        settings = get_settings()
        response = Response()
        auth.set_auth_cookie(response, "admin", settings)
        cookie_header = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=lax", cookie_header)
        self.assertIn(settings.jwt_cookie_name, cookie_header)

    def test_csrf_token_validation(self) -> None:
        token = auth.make_csrf_token()
        self.assertTrue(auth.is_valid_csrf_token(token))
        self.assertFalse(auth.is_valid_csrf_token(token + "x"))
        self.assertFalse(auth.is_valid_csrf_token("missing-separator"))

    def test_production_auth_requires_secret_values(self) -> None:
        os.environ["APP_ENV"] = "production"
        os.environ.pop("ADMIN_PASSWORD", None)
        os.environ.pop("JWT_SECRET", None)
        get_settings.cache_clear()
        with self.assertRaises(RuntimeError):
            auth.admin_password()
        with self.assertRaises(RuntimeError):
            auth.jwt_secret()

    def test_schedule_helpers(self) -> None:
        self.assertEqual(
            build_cron_from_form({"schedule_kind": "every_hours", "interval_hours": "6"}),
            "0 */6 * * *",
        )
        self.assertEqual(
            build_cron_from_form({"schedule_kind": "daily", "daily_time": "08:15"}),
            "15 8 * * *",
        )
        self.assertEqual(
            build_cron_from_form(
                {"schedule_kind": "weekly", "weekly_day": "fri", "weekly_time": "18:45"}
            ),
            "45 18 * * fri",
        )
        view = cron_to_schedule_view("15 10 1 * *")
        self.assertTrue(view.custom)
        self.assertIn("15 10 1 * *", view.label)
        with self.assertRaises(ValueError):
            validate_cron("bad cron")


if __name__ == "__main__":
    unittest.main()
