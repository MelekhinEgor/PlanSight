"""Демо-вход по логину/паролю: выдаёт session token для UI и (опционально) RBAC."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()


@dataclass(frozen=True)
class AuthUser:
    login: str
    name: str
    role_label: str
    initials: str
    rbac_role: str  # viewer | operator | admin
    app_role: str  # analyst | technician | admin
    password_salt: str
    password_hash: str


def _user(
    login: str,
    password: str,
    name: str,
    role_label: str,
    initials: str,
    rbac_role: str,
    app_role: str,
) -> AuthUser:
    salt = f"plansight.{login}.v1"
    return AuthUser(
        login=login,
        name=name,
        role_label=role_label,
        initials=initials,
        rbac_role=rbac_role,
        app_role=app_role,
        password_salt=salt,
        password_hash=_hash_password(password, salt),
    )


# Демо-учётки: аналитик (сигналы/КСГ) и техспециалист (источники данных).
_USERS: tuple[AuthUser, ...] = (
    _user("user", "plansight", "Анна Соколова", "Аналитик", "АС", "operator", "analyst"),
    _user("admin", "plansight", "Роман Белов", "Технический специалист", "РБ", "admin", "technician"),
)

_sessions: dict[str, AuthUser] = {}


def public_user(u: AuthUser) -> dict[str, Any]:
    return {
        "login": u.login,
        "name": u.name,
        "role": u.role_label,
        "initials": u.initials,
        "rbac_role": u.rbac_role,
        "app_role": u.app_role,
    }


def find_user(login: str) -> AuthUser | None:
    key = (login or "").strip().lower()
    for u in _USERS:
        if u.login == key:
            return u
    return None


def verify_password(user: AuthUser, password: str) -> bool:
    got = _hash_password(password or "", user.password_salt)
    return hmac.compare_digest(got, user.password_hash)


def issue_token(user: AuthUser) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = user
    return token


def revoke_token(token: str | None) -> None:
    if not token:
        return
    _sessions.pop(token, None)


def user_from_token(token: str | None) -> AuthUser | None:
    if not token:
        return None
    return _sessions.get(token)


def extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def login(login: str, password: str) -> dict[str, Any] | None:
    user = find_user(login)
    if not user or not verify_password(user, password):
        return None
    token = issue_token(user)
    return {"token": token, "user": public_user(user)}


def demo_hint() -> list[dict[str, str]]:
    """Подсказка на экране входа (только демо)."""
    return [
        {
            "login": "user",
            "password": "plansight",
            "name": "Анна Соколова",
            "role": "Аналитик",
        },
        {
            "login": "admin",
            "password": "plansight",
            "name": "Роман Белов",
            "role": "Технический специалист",
        },
    ]
