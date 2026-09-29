"""Каноническое извлечение корпуса из текста КСГ (P0-01).

Нельзя считать букву «к» внутри произвольного слова обозначением корпуса.
Допускаются только явные формы: «корпус 1», «корп. 1», «К-1», «К1», «building 1».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

BuildingSource = Literal[
    "schedule_explicit",
    "wbs_parent",
    "human_verified",
    "unknown",
]


@dataclass(frozen=True)
class BuildingParse:
    raw: str | None
    normalized: str | None
    source: BuildingSource
    confident: bool


# «корпус 1» / «корп.2» / «корп 3А»
_RE_CORPUS = re.compile(
    r"(?:^|[^\wА-Яа-яЁё])"
    r"(?:корпус|корп\.?)\s*"
    r"([0-9]+[A-Za-zА-Яа-я]?)"
    r"(?=$|[^\wА-Яа-яЁё])",
    re.IGNORECASE,
)

# корпус 1 / Building-2
_RE_BUILDING_EN = re.compile(
    r"(?:^|[^\w])"
    r"building[\s\-]*"
    r"([0-9]+[A-Za-z]?)"
    r"(?=$|[^\w])",
    re.IGNORECASE,
)

# Отдельный токен К1 / К-1 / K2 (не середина «Ключевые», «Кровля», «КСГ»)
_RE_K_TOKEN = re.compile(
    r"(?:^|[^\wА-Яа-яЁё])"
    r"([КкKk])-?([0-9]+[A-Za-zА-Яа-я]?)"
    r"(?=$|[^\wА-Яа-яЁё])",
)

# Уже нормализованный код
_RE_ALREADY = re.compile(r"^К[0-9]+[A-Za-zА-Яа-я]?$", re.IGNORECASE)


def canonicalize_building_token(token: str) -> str:
    t = (token or "").strip().upper().replace(" ", "")
    if not t:
        return ""
    if t.startswith("К") or t.startswith("K"):
        rest = t[1:].lstrip("-")
        return f"К{rest}" if rest else ""
    return f"К{t}"


def parse_building_from_text(name: str | None) -> BuildingParse:
    """Извлекает корпус только при явной форме. Иначе unknown."""
    text = (name or "").strip()
    if not text:
        return BuildingParse(None, None, "unknown", False)

    if _RE_ALREADY.fullmatch(text.replace(" ", "")):
        norm = canonicalize_building_token(text)
        return BuildingParse(text, norm, "schedule_explicit", True)

    m = _RE_CORPUS.search(text)
    if m:
        norm = canonicalize_building_token(m.group(1))
        return BuildingParse(m.group(0).strip(), norm, "schedule_explicit", True)

    m = _RE_BUILDING_EN.search(text)
    if m:
        norm = canonicalize_building_token(m.group(1))
        return BuildingParse(m.group(0).strip(), norm, "schedule_explicit", True)

    m = _RE_K_TOKEN.search(text)
    if m:
        norm = canonicalize_building_token(m.group(1) + m.group(2))
        return BuildingParse(m.group(0).strip(), norm, "schedule_explicit", True)

    return BuildingParse(None, None, "unknown", False)


def guess_building(name: str | None) -> str | None:
    """Совместимость со старым API: только confident normalized id или None."""
    p = parse_building_from_text(name)
    return p.normalized if p.confident else None
