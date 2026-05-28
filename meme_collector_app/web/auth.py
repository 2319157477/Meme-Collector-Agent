"""Single-admin JWT cookie auth and CSRF helpers for the WebUI."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import jwt
from fastapi import HTTPException, Request, status
from starlette.responses import Response

from meme_collector_app.core.config import Settings, get_settings

CSRF_SEPARATOR = "."


def _is_development(settings: Settings) -> bool:
    return settings.app_env.strip().lower() in {"", "dev", "development", "local", "test"}


def admin_password(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if settings.admin_password:
        return settings.admin_password
    if _is_development(settings):
        return "admin"
    raise RuntimeError("ADMIN_PASSWORD must be set when APP_ENV is not development")


def jwt_secret(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if settings.jwt_secret:
        return settings.jwt_secret
    if _is_development(settings):
        return "dev-only-change-me-meme-collector"
    raise RuntimeError("JWT_SECRET must be set when APP_ENV is not development")


def cookie_secure(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return not _is_development(settings)


def create_access_token(username: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, jwt_secret(settings), algorithm="HS256")


def decode_access_token(token: str | None, settings: Settings | None = None) -> str | None:
    if not token:
        return None
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, jwt_secret(settings), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    if not isinstance(subject, str) or subject != settings.admin_username:
        return None
    return subject


def authenticate(username: str, password: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    expected_user = settings.admin_username
    expected_password = admin_password(settings)
    return hmac.compare_digest(username, expected_user) and hmac.compare_digest(
        password, expected_password
    )


def current_username(request: Request) -> str | None:
    settings = get_settings()
    return decode_access_token(request.cookies.get(settings.jwt_cookie_name), settings)


def require_admin(request: Request) -> str:
    username = current_username(request)
    if username:
        return username
    next_url = quote(str(request.url.path), safe="/")
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": f"/login?next={next_url}"},
    )


def _sign(value: str, settings: Settings) -> str:
    digest = hmac.new(jwt_secret(settings).encode(), value.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_csrf_token(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    raw = secrets.token_urlsafe(32)
    return f"{raw}{CSRF_SEPARATOR}{_sign(raw, settings)}"


def is_valid_csrf_token(token: str | None, settings: Settings | None = None) -> bool:
    if not token or CSRF_SEPARATOR not in token:
        return False
    settings = settings or get_settings()
    raw, signature = token.rsplit(CSRF_SEPARATOR, 1)
    if not raw or not signature:
        return False
    return hmac.compare_digest(signature, _sign(raw, settings))


def csrf_token_for_request(request: Request, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    existing = request.cookies.get(settings.csrf_cookie_name)
    if is_valid_csrf_token(existing, settings):
        return existing or ""
    return make_csrf_token(settings)


def verify_csrf(request: Request, form_token: str | None, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    if (
        not form_token
        or not cookie_token
        or not hmac.compare_digest(form_token, cookie_token)
        or not is_valid_csrf_token(form_token, settings)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def set_auth_cookie(response: Response, username: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    response.set_cookie(
        settings.jwt_cookie_name,
        create_access_token(username, settings),
        max_age=settings.jwt_ttl_minutes * 60,
        httponly=True,
        secure=cookie_secure(settings),
        samesite="lax",
    )


def clear_auth_cookie(response: Response, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    response.delete_cookie(settings.jwt_cookie_name)
    response.delete_cookie(settings.csrf_cookie_name)


def set_csrf_cookie(response: Response, token: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=settings.jwt_ttl_minutes * 60,
        httponly=False,
        secure=cookie_secure(settings),
        samesite="lax",
    )


def validate_auth_config(settings: Settings | None = None) -> None:
    """Fail closed for deployed environments that omit auth secrets."""

    settings = settings or get_settings()
    admin_password(settings)
    jwt_secret(settings)
