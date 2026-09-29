"""V6 — одна роль в заголовке НЕ есть auth. При включённом RBAC нужен shared API token.

Trusted reverse proxy может выставлять X-PlanSight-Role ПОСЛЕ аутентификации пользователя.
Внешние клиенты шлют Authorization: Bearer <PLANSIGHT_API_TOKEN>.
Без настроенного PLANSIGHT_API_TOKEN режим RBAC запрещает привилегированный доступ
(fail-closed для ops/admin; мутации для viewer по-прежнему блокируются).
"""

from __future__ import annotations

import hmac
import os
from typing import Callable

from fastapi import Header, HTTPException, Request


ROLES = ("viewer", "operator", "admin")


def rbac_enabled() -> bool:
    return os.environ.get("PLANSIGHT_RBAC", "").strip().lower() in ("1", "true", "yes")


def _expected_token() -> str | None:
    tok = (os.environ.get("PLANSIGHT_API_TOKEN") or "").strip()
    return tok or None


def _token_ok(request: Request) -> bool:
    expected = _expected_token()
    if not expected:
        return False
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        got = auth[7:].strip()
        return hmac.compare_digest(got, expected)
    # Заголовок прокси предпочтителен вместе с bearer;
    # X-PlanSight-Token — альтернатива для демо за прокси.
    alt = (request.headers.get("X-PlanSight-Token") or "").strip()
    return bool(alt) and hmac.compare_digest(alt, expected)


def require_role(min_role: str) -> Callable:
    order = {r: i for i, r in enumerate(ROLES)}

    def dep(
        request: Request,
        role: str = Header(default="viewer", alias="X-PlanSight-Role"),
    ) -> str:
        if not rbac_enabled():
            return "operator"
        if not _token_ok(request):
            raise HTTPException(401, "authentication required")
        r = (role or "viewer").lower()
        if r not in ROLES:
            raise HTTPException(403, "role denied")
        if order[r] < order[min_role]:
            raise HTTPException(403, f"requires {min_role}")
        return r

    return dep


async def rbac_middleware(request: Request, call_next):
    if not rbac_enabled():
        return await call_next(request)
    path = request.url.path
    method = request.method.upper()
    # Публичный health
    if path in ("/api/health", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)
    if not path.startswith("/api/"):
        return await call_next(request)

    authed = _token_ok(request)
    role = (request.headers.get("X-PlanSight-Role") or "viewer").lower()
    if role not in ROLES:
        role = "viewer"

    from fastapi.responses import JSONResponse

    # Поддельный admin без token → 401
    if path.startswith("/api/ops/") or path.startswith("/api/admin/"):
        if not authed:
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        if role != "admin":
            return JSONResponse({"detail": "admin required"}, status_code=403)

    if method in ("POST", "PUT", "PATCH", "DELETE"):
        if not authed:
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        if role == "viewer":
            return JSONResponse({"detail": "viewer cannot mutate"}, status_code=403)

    # Метод GET: при RBAC нужен token (изоляция медиа/проектов)
    if method == "GET" and not authed:
        # Без auth только health; остальное при RBAC требует token
        return JSONResponse({"detail": "authentication required"}, status_code=401)

    return await call_next(request)
