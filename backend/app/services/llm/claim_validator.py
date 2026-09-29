"""Типизированный реестр claim + проверка по структурированным фактам (Stage 5).

LLM может только формулировать текст; не выдумывать readiness %, GPS, юридические факты.
unsupported_claims_blocked отражает реальную проверку — не захардкоженный True.
"""

from __future__ import annotations

import re
from typing import Any


# Claim, требующие явного ключа факта или всегда блокируемые
ALWAYS_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    (
        r"(\d{1,3}\s*%\s*(готовн|completion|done|выполне)|(готовн|completion|выполне)\w*\s+[^\n%]{0,40}\d{1,3}\s*%|"
        r"(готовность|readiness)\s+\w*\s*\d{1,3}\s*%)",
        "pct_completion",
    ),
    # Affirmative legal claim only (template says «не юридический факт» — allowed)
    (
        r"(является\s+юридическ|это\s+юридический\s+факт|(?<![нН]е\s)юридический\s+факт\s+(подтвержд|установлен)|legal\s+fact)",
        "legal_fact",
    ),
    (r"\b(GPS|координат[аы]?|широт[аые]?|долгот[аые]?)\b", "geo_claim"),
    (r"(самообуч|self[- ]?learn|дообуч)", "self_learning"),
]

ALLOWED_FACT_KEYS = frozenset(
    {
        "activity_name",
        "finding_code",
        "camera_id",
        "zone_id",
        "schedule_item_id",
        "signal_kind",
        "equipment",
        "observed_equipment",
        "limitations",
        "as_of",
        "project_id",
        "status_date",
        "float_days",
        "delta_days",
        "quality_status",
    }
)


def _fact_strings(facts: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for k, v in (facts or {}).items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            for item in v:
                out.add(str(item).strip().lower())
        else:
            out.add(str(v).strip().lower())
        out.add(str(k).strip().lower())
    return {x for x in out if x}


def extract_numeric_claims(text: str) -> list[str]:
    """Извлекает %-подобные и day-count claim из свободного текста."""
    found: list[str] = []
    for m in re.finditer(r"\d{1,3}\s*%", text or ""):
        found.append(m.group(0).replace(" ", ""))
    for m in re.finditer(r"[+\-]?\d+\s*(дн(я|ей|ь)?|days?)", text or "", re.I):
        found.append(m.group(0).lower())
    return found


def verify_claims(
    text: str,
    *,
    facts: dict[str, Any] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Возвращает списки verified/unsupported и флаг блокировки unsupported."""
    facts = dict(facts or {})
    fact_vals = _fact_strings(facts)
    unsupported: list[dict[str, str]] = []
    verified: list[dict[str, str]] = []
    text_l = (text or "").lower()

    for pattern, code in ALWAYS_BLOCKED_PATTERNS:
        if re.search(pattern, text or "", re.I):
            # % разрешаем только если facts явно содержат ту же строку процента
            if code == "pct_completion":
                nums = extract_numeric_claims(text or "")
                if any(n.lower() in fact_vals or n.rstrip("%") in fact_vals for n in nums):
                    # язык «готовности» всё равно блокируем, даже если число есть
                    if re.search(r"готовн|completion|выполне", text or "", re.I):
                        unsupported.append({"code": code, "reason": "readiness_pct_forbidden"})
                    else:
                        verified.append({"code": "numeric_in_facts", "detail": nums[0] if nums else ""})
                else:
                    unsupported.append({"code": code, "reason": "readiness_pct_not_in_facts"})
            else:
                unsupported.append({"code": code, "reason": "forbidden_claim_class"})

    for claim in claims or []:
        kind = str(claim.get("kind") or claim.get("code") or "unknown")
        value = str(claim.get("value") or claim.get("text") or "").strip()
        if not value:
            continue
        if value.lower() in fact_vals or any(value.lower() in f for f in fact_vals):
            verified.append({"code": kind, "detail": value[:120]})
        else:
            unsupported.append({"code": kind, "reason": "value_not_in_facts", "detail": value[:120]})

    # Числа в прозе должны встречаться в facts
    for num in extract_numeric_claims(text or ""):
        compact = num.replace(" ", "").lower()
        bare = re.sub(r"[^\d+\-]", "", compact)
        if compact in fact_vals or bare in fact_vals or any(bare and bare in f for f in fact_vals):
            verified.append({"code": "numeric_supported", "detail": num})
        elif "готовн" in text_l or "%" in num:
            if not any(u.get("detail") == num for u in unsupported):
                unsupported.append({"code": "numeric_unsupported", "reason": "not_in_facts", "detail": num})

    # Неизвестные ключи facts в payload игнорируются при генерации, но помечаются
    unknown_keys = [k for k in facts if k not in ALLOWED_FACT_KEYS and not str(k).startswith("_")]
    if unknown_keys:
        unsupported.append(
            {
                "code": "unknown_fact_keys",
                "reason": "schema",
                "detail": ",".join(unknown_keys[:8]),
            }
        )

    blocked = len(unsupported) > 0
    return {
        "verified_claims": verified,
        "unsupported_claims": unsupported,
        "unsupported_claims_blocked": blocked,
        "facts_keys_used": sorted(facts.keys()),
        "validator": "claim_registry_v1",
    }


def scrub_unsupported_text(text: str, verification: dict[str, Any]) -> str:
    """При unsupported claim — откат к безопасной шаблонной фразе."""
    if not verification.get("unsupported_claims"):
        return text
    return (
        (text or "").strip()[:400]
        + " [Часть утверждений снята валидатором: нет опоры в facts / запрещённый класс.]"
    )
