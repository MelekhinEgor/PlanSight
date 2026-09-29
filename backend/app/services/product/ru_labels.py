"""Русские подписи для техники и кодов — без англ. идентификаторов в UI."""

from __future__ import annotations

from typing import Any, Iterable

EQUIPMENT_RU: dict[str, str] = {
    "excavator": "экскаватор",
    "mini_excavator": "мини-экскаватор",
    "dump_truck": "самосвал",
    "truck_unknown": "грузовик",
    "vehicle_unknown": "транспорт",
    "equipment_unknown": "техника",
    "crane_unknown": "кран",
    "concrete_mixer": "автобетоносмеситель",
    "concrete_pump": "бетононасос",
    "bulldozer": "бульдозер",
    "grader": "грейдер",
    "roller": "каток",
    "loader": "погрузчик",
    "forklift": "вилочный погрузчик",
    "telehandler": "телескопический погрузчик",
    "mobile_crane": "автокран",
    "tower_crane": "башенный кран",
    "loader_crane": "кран-манипулятор",
    "person": "человек",
    "worker": "рабочий",
}

DEVIATION_CODE_RU: dict[str, str] = {
    "LOW_ACTIVITY": "низкая активность на камере",
    "SCHEDULE_LAG": "отставание от графика",
    "REQUIRED_EQUIPMENT_GAP": "нет ожидаемой техники",
    "UNEXPECTED_EQUIPMENT_IN_ZONE": "неожиданная техника в зоне",
    "AMBIGUOUS_ASSIGNMENT": "неоднозначная привязка",
    "CAMERA_COVERAGE_GAP": "мало кадров для вывода",
    "POSSIBLE_LATE_START": "возможный поздний старт",
    "UNCONFIRMED_ACTIVITY": "активность не подтверждена",
    "POSSIBLE_PAUSE": "возможный простой",
    "WORK_AFTER_PLAN": "работы после планового срока",
    "NEEDS_CAMERA_SETUP": "нужна настройка камеры",
    "EARLY_START": "ранний старт",
}


def equipment_ru(code: str | None) -> str:
    if not code:
        return "—"
    key = str(code).strip()
    return EQUIPMENT_RU.get(key, EQUIPMENT_RU.get(key.lower(), key.replace("_", " ")))


def equipment_list_ru(items: Iterable[Any] | None) -> str:
    vals = [equipment_ru(str(x)) for x in (items or []) if x is not None and str(x).strip()]
    return ", ".join(vals) if vals else "—"


def zone_ru(zone_key: str | None) -> str:
    if not zone_key:
        return "зона наблюдения"
    z = str(zone_key).strip()
    if z.upper() in ("WHOLE_FRAME", "FULL", "ALL"):
        return "весь кадр"
    if z.upper().startswith("Z") and z[1:].isdigit():
        return f"зона {z[1:]}"
    # уже человекочитаемое имя
    if any(ord(ch) > 127 for ch in z):
        return z
    return f"зона «{z}»"


def deviation_code_ru(code: str | None) -> str:
    if not code:
        return "предупреждение по наблюдениям"
    return DEVIATION_CODE_RU.get(str(code), "предупреждение по наблюдениям")


# Часто встречающийся служебный/смешанный текст → чистый русский для UI
_LIMITATION_EXACT: dict[str, str] = {
    "без binding камера↔корпус назначение запрещено": (
        "Без подтверждённой привязки камеры к корпусу назначение работы запрещено"
    ),
    "отсутствие кадров ≠ отсутствие техники на площадке": (
        "Отсутствие кадров не означает отсутствие техники на площадке"
    ),
    "Отсутствие на кадре ≠ отсутствие на площадке": (
        "Отсутствие на кадре не означает отсутствие на площадке"
    ),
    "отсутствие на кадре не доказывает отсутствие на всей площадке": (
        "Отсутствие на кадре не доказывает отсутствие техники на всей площадке"
    ),
    "это возможный дефицит требуемой техники, не P(срыва сроков)": (
        "Это возможный дефицит техники, а не оценка вероятности срыва сроков"
    ),
    "Не включать в production CV KPI": "Не учитывать в рабочих показателях по камерам",
    "Нет утверждения процента готовности по фото": "Процент готовности по фото не выводится",
    "оценка по подтверждённой зоне корпуса, окно — последние часы до as_of": (
        "Оценка по подтверждённой зоне корпуса; окно — последние часы до контрольной даты"
    ),
    "Оценка по подтверждённой зоне корпуса; окно — последние часы до as_of": (
        "Оценка по подтверждённой зоне корпуса; окно — последние часы до контрольной даты"
    ),
}


_LIMITATION_FRAGMENTS: list[tuple[str, str]] = [
    (r"\bas[_\s-]?of\b", "контрольной даты"),
    (r"\bbinding\b", "привязка"),
    (r"\bproduction\s+CV\s+KPI\b", "рабочие показатели по камерам"),
    (r"\bP\s*\(\s*срыва[^)]*\)", "оценка вероятности срыва сроков"),
    (r"\bP\s*\(\s*O\s*\|\s*A\s*\)", "вероятность наблюдения"),
    (r"\buncalibrated[_\s-]?score\b", "некалиброванная оценка модели"),
    (r"\bsource[_\s-]?of[_\s-]?truth\b", "источник истины"),
    (r"\blegacy[_\s-]?code\b", "устаревший код"),
    (r"\bincompleteness\b", "неполнота данных"),
    (r"\bnot\s+a\s+legal\s+fact\b", "не юридический факт"),
    (r"\bevidence\b", "доказательства"),
    (r"\bfinding\b", "предупреждение"),
    (r"\bschedule\b", "график"),
    (r"≠", " не означает "),
]


def limitation_ru(text: str | None) -> str:
    """Очистить ограничение от англ. служебных фрагментов для карточки."""
    import re

    raw = (text or "").strip()
    if not raw:
        return ""
    if raw in _LIMITATION_EXACT:
        return _LIMITATION_EXACT[raw]
    low = raw.lower()
    for k, v in _LIMITATION_EXACT.items():
        if k.lower() == low:
            return v
    out = raw
    for pattern, repl in _LIMITATION_FRAGMENTS:
        out = re.sub(pattern, repl, out, flags=re.I)
    # убрать «голые» CODE_STYLE токены в скобках/хвосте
    out = re.sub(r"\b[A-Z]{2,}(?:_[A-Z0-9]+){1,}\b", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" .;")
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out or "Ограничение требует проверки на площадке"


def limitations_ru(items: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items or []:
        t = limitation_ru(str(x) if x is not None else "")
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def binding_status_ru(status: str | None) -> str:
    s = (status or "").strip().upper()
    return {
        "VERIFIED": "привязка зоны подтверждена",
        "PROPOSED": "привязка предложена, не подтверждена",
        "UNASSIGNED": "привязка не назначена",
        "HINT": "корпус указан как подсказка",
        "UNBOUND": "камера без привязки к корпусу",
    }.get(s, status or "статус привязки неизвестен")
