"""Классификация наблюдаемости работ для CV (L0)."""

from __future__ import annotations

# Режим DIRECT — техника на кадре типична и различима
# Режим INDIRECT — возможны косвенные признаки
# Режим NOT_OBSERVABLE — документы, согласования, скрытые/внутренние процессы
# Режим UNKNOWN — не определено

_NOT_OBSERVABLE_PATTERNS = [
    "разрешен",
    "согласован",
    "договор",
    "конкурс",
    "экспертиз",
    "проектн",
    "документац",
    "дизайн-проект",
    "изыскан",
    "мобилизац",
    "поставк",
    "заключение о соответств",
    "ордер",
    "гидроиспытан",  # обычно не с уличной камеры
    "ии лифта",
    "ии овкв",
    "ии скс",
    "ии скуд",
    "ии сот",
    "ии узла",
    "ии электро",
    "мебелировк",
]

_DIRECT_PATTERNS = [
    ("засыпка транш", "backfill"),
    ("засыпка котлован", "backfill"),
    ("засыпка траншей и котлованов", "backfill"),
    ("обратная засыпка", "backfill"),
    ("разработка грунта", "excavation"),
    ("разработка котлован", "excavation"),
    ("земляные", "excavation"),
    ("котлован", "excavation"),
    ("вывоз", "soil_haulage"),
    ("бетонир", "concrete_pouring"),
    ("бетонн", "concrete_pouring"),
    ("планировк", "grading"),
]

_INDIRECT_PATTERNS = [
    ("демонтаж", "demolition"),
    ("монтаж", "installation"),
    ("установка гпм", "installation"),
    ("установка зонтов", "installation"),
    ("установка решеток", "installation"),
    ("прокладк", "utilities"),
    ("фасад", "facade"),
    ("кровл", "roofing"),
    ("опалуб", "formwork"),
    ("арматур", "rebar"),
    ("усиление стен", "structural"),
    ("устройство стен", "structural"),
    ("устройство потолков", "structural"),
    ("обследован", "structural"),
    ("озеленен", "landscaping"),
    ("дорог и тротуар", "landscaping"),
    ("установка маф", "landscaping"),
]

_INTERIOR_FINISH = [
    "облицовк",
    "окрашиван",
    "оштукатур",
    "шпатлев",
    "стяжек",
    "полов",
    "гкл",
    "плитк",
    "интерьер",
]


def classify_observability(raw_name: str, *, is_milestone: bool = False, is_summary: bool = False) -> tuple[str, str, str | None]:
    """Вернуть (mode, reason, suggested_work_type_code|None)."""
    if is_summary:
        return "NOT_OBSERVABLE", "сводная работа (summary) — не объект CV", None
    if is_milestone:
        return "NOT_OBSERVABLE", "веха — не объект CV", None

    text = " ".join((raw_name or "").lower().split())
    if not text:
        return "UNKNOWN", "пустое название", None

    for pat in _NOT_OBSERVABLE_PATTERNS:
        if pat in text:
            return "NOT_OBSERVABLE", f"по признаку «{pat}» (документы/процессы вне зоны камеры)", None

    for pat in _INTERIOR_FINISH:
        if pat in text:
            return "NOT_OBSERVABLE", "внутренние отделочные работы — уличная камера не покрывает", "interior_finish"

    for pat, code in _DIRECT_PATTERNS:
        if pat in text:
            return "DIRECT", f"типично наблюдается техникой ({pat})", code

    for pat, code in _INDIRECT_PATTERNS:
        if pat in text:
            return "INDIRECT", f"возможны косвенные признаки ({pat})", code

    return "UNKNOWN", "нет уверенного правила наблюдаемости", None
