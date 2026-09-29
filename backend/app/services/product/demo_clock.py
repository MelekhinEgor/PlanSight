"""Демо-часы — «сегодня» для демо всегда календарная дата (Москва)."""

from __future__ import annotations

from datetime import datetime


def demo_as_of_iso() -> str:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
