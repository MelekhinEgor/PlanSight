"""Движок grounded-объяснений — русские шаблоны без LLM."""

from __future__ import annotations

import json
from typing import Any

from app.db.models import Deviation
from app.services.product.ru_labels import (
    deviation_code_ru,
    equipment_list_ru,
    limitations_ru,
    zone_ru,
)


def finding_from_deviation(d: Deviation) -> dict[str, Any]:
    details = json.loads(d.details_json or "{}")
    finding = details.get("finding") or d.code
    return {
        "finding": finding,
        "schedule_item_id": d.schedule_item_id,
        "camera_visual_zone_id": details.get("camera_visual_zone_id") or details.get("zone_key"),
        "observed_interval": details.get("covered_interval") or details.get("observed_interval"),
        "expected_equipment": details.get("expected_equipment"),
        "observed_equipment": details.get("observed_equipment"),
        "not_confirmed_equipment": details.get("not_confirmed_equipment"),
        "unexpected_equipment": details.get("unexpected_equipment"),
        "coverage": details.get("coverage") or details.get("frames_in_window"),
        "evidence_ids": details.get("evidence_frame_ids")
        or json.loads(d.evidence_ids_json or "[]"),
        "message": details.get("message"),
        "hypothesis": details.get("hypothesis") or details.get("note"),
        "limitations": details.get("limitations")
        or ["Отсутствие на кадре не доказывает отсутствие техники на всей площадке"],
        "suggested_check": details.get("suggested_check"),
        "heuristic_score": d.heuristic_score if d.heuristic_score is not None else d.risk_score,
        "lifecycle": d.lifecycle,
        "building": details.get("building"),
        "demo_primary": details.get("demo_primary"),
    }


def _join_sentences(*parts: str | None) -> str:
    out = [p.strip() for p in parts if p and str(p).strip()]
    return " ".join(out)


def render_ru(finding: dict[str, Any]) -> str:
    """Связный ответ для аналитика — без англ. кодов и без «служебного жаргона»."""
    code = str(finding.get("finding") or "")
    zone = zone_ru(finding.get("camera_visual_zone_id"))
    building = finding.get("building")
    place = f"корпус «{building}», {zone}" if building else zone
    evid_n = len(finding.get("evidence_ids") or [])
    frames_note = f"В разбор вошло кадров: {evid_n}." if evid_n else ""

    hyp = (finding.get("hypothesis") or "").strip()
    msg = (finding.get("message") or "").strip()
    check = (finding.get("suggested_check") or "").strip()
    limits = limitations_ru(finding.get("limitations") or [])
    # Ограничения finding очищены для downstream
    finding = {**finding, "limitations": limits}

    if code == "REQUIRED_EQUIPMENT_GAP":
        exp = equipment_list_ru(finding.get("expected_equipment"))
        obs = equipment_list_ru(finding.get("observed_equipment"))
        if obs == "—":
            obs = "техника на кадрах не подтверждена"
        miss = equipment_list_ru(finding.get("not_confirmed_equipment"))
        lead = (
            f"По наблюдениям в зоне ({place}) не хватает техники, "
            f"которая нужна для текущей работы по графику."
        )
        body = f"Для работы ожидалось: {exp}. На кадрах видно: {obs}. Не подтверждено: {miss}."
        why = hyp or (
            "Это не приговор площадке: техника могла быть вне обзора камеры или вне выбранного окна времени."
        )
        action = check or "Сверьте организацию работ и наличие техники на площадке и в соседних зонах."
        text = _join_sentences(lead, body, why, frames_note, f"Что проверить: {action}")
    elif code == "UNEXPECTED_EQUIPMENT_IN_ZONE":
        un = equipment_list_ru(finding.get("unexpected_equipment"))
        lead = f"В зоне ({place}) зафиксирована техника, которая плохо согласуется с текущим этапом работ."
        body = f"На кадрах отмечено: {un}."
        why = "Возможны параллельные работы, ошибочная зона или смена состава машин."
        action = check or "Уточните назначение техники и параллельные работы в этой зоне."
        text = _join_sentences(lead, body, why, frames_note, f"Что проверить: {action}")
    elif code == "UNCONFIRMED_ACTIVITY":
        lead = f"Плановая работа в зоне ({place}) по кадрам пока не подтверждена."
        body = hyp or msg or "Наблюдаемая активность слабее ожидаемой для этого окна."
        why = "Камера могла не видеть участок работ, либо работы шли в другое время."
        action = check or "Сверьте фактическое место работ с зоной камеры и окном съёмки."
        text = _join_sentences(lead, body, why, frames_note, f"Что проверить: {action}")
    elif code == "CAMERA_COVERAGE_GAP":
        lead = f"Для зоны ({place}) не хватает пригодных кадров, чтобы уверенно говорить о ходе работ."
        why = "Без покрытия нельзя уверенно утверждать ни простой, ни срыв — данных недостаточно."
        action = check or "Проверьте работу камеры, интервал съёмки и привязку зоны."
        text = _join_sentences(lead, why, frames_note, f"Что проверить: {action}")
    elif code == "AMBIGUOUS_ASSIGNMENT":
        lead = "Система видит активность, но не может однозначно связать её с одной строкой графика."
        why = "Чаще всего это пересечение корпусов/зон или неподтверждённая привязка камеры."
        action = check or "Подтвердите привязку зоны к корпусу на экране «Камеры»."
        text = _join_sentences(lead, why, frames_note, f"Что проверить: {action}")
    elif code == "POSSIBLE_LATE_START":
        lead = f"По покрытию камеры в зоне ({place}) возможен поздний старт относительно плана."
        why = "Это сигнал к проверке, а не доказательство, что работы не велись."
        action = check or "Сверьте фактический старт с планом и журналом работ."
        text = _join_sentences(lead, why, frames_note, f"Что проверить: {action}")
    elif code == "POSSIBLE_PAUSE":
        lead = f"В зоне ({place}) возможный простой: активность на кадрах ослабла."
        action = check or "Уточните, была ли пауза по технологии, погоде или логистике."
        text = _join_sentences(lead, frames_note, f"Что проверить: {action}")
    elif code == "LOW_ACTIVITY":
        lead = hyp or msg or f"На камере в зоне ({place}) активность ниже ожидаемой."
        why = "Низкая активность на кадре не всегда означает простой всей площадки."
        action = check or "Сверьте участок работ с зоной обзора."
        text = _join_sentences(lead, why, frames_note, f"Что проверить: {action}")
    elif code == "SCHEDULE_LAG":
        lead = hyp or msg or "По срокам календарного графика работа отстаёт от плана."
        action = check or "Обновите факт выполнения и прогноз завершения."
        text = _join_sentences(lead, f"Что проверить: {action}")
    elif code == "WORK_AFTER_PLAN":
        lead = hyp or msg or "Наблюдается активность после планового срока завершения."
        action = check or "Уточните, это догонные работы или ошибка дат в графике."
        text = _join_sentences(lead, frames_note, f"Что проверить: {action}")
    elif code == "EARLY_START":
        lead = hyp or msg or "Возможен старт раньше плановой даты."
        action = check or "Сверьте даты в графике и фактический выход бригады."
        text = _join_sentences(lead, frames_note, f"Что проверить: {action}")
    elif code == "NEEDS_CAMERA_SETUP":
        lead = "Чтобы делать выводы по этой зоне, нужно настроить камеру и подтвердить привязку."
        action = check or "Задайте зону обзора и подтвердите корпус."
        text = _join_sentences(lead, f"Что проверить: {action}")
    else:
        lead = hyp or msg or f"Есть предупреждение: {deviation_code_ru(code)}."
        action = check or "Откройте карточку и сверьте кадры с графиком."
        text = _join_sentences(lead, frames_note, f"Что проверить: {action}")

    if limits:
        # Одна мягкая строка ограничения, не простыня системных заметок
        text = _join_sentences(text, f"Важно: {limits[0]}.")
    return text


def explain_deviation(d: Deviation) -> dict[str, Any]:
    finding = finding_from_deviation(d)
    return {
        "finding": finding,
        "text_ru": render_ru(finding),
        "engine": "rules_template_v2",
        "ai_used": False,
    }


def explain_payload_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Для /api/ai/explain без LLM — тот же тон, что у карточек finding."""
    from app.services.llm.claim_validator import verify_claims
    from app.services.llm.qwen_explain import sanitize_user_text

    name = sanitize_user_text(str(payload.get("activity_name") or "работа").strip() or "работа")
    code = str(payload.get("finding_code") or "").strip()
    label = deviation_code_ru(code) if code else "сигнал по наблюдениям"
    facts = dict(payload.get("facts") or {})
    facts.setdefault("activity_name", name)
    facts.setdefault("finding_code", code)
    lim = limitations_ru(
        payload.get("limitations")
        or ["Отсутствие на кадре не доказывает отсутствие техники на площадке"]
    )
    finding = {
        "finding": code,
        "camera_visual_zone_id": facts.get("camera_visual_zone_id") or facts.get("zone_id"),
        "building": facts.get("building"),
        "expected_equipment": facts.get("expected_equipment"),
        "observed_equipment": facts.get("observed_equipment") or facts.get("equipment"),
        "not_confirmed_equipment": facts.get("not_confirmed_equipment") or facts.get("missing_equipment"),
        "unexpected_equipment": facts.get("unexpected_equipment"),
        "evidence_ids": facts.get("evidence_ids") or payload.get("frame_ids") or [],
        "message": facts.get("message") or f"Работа «{name}»",
        "hypothesis": facts.get("hypothesis"),
        "limitations": lim,
        "suggested_check": facts.get("suggested_check"),
    }
    if code:
        text = render_ru(finding)
        text = _join_sentences(
            text,
            "Это рекомендация для проверки специалистом, а не юридический факт.",
        )
    else:
        text = (
            f"По работе «{name}» сформировано предупреждение «{label}». "
            "Вывод опирается на сохранённые факты и кадры. "
            "Это рекомендация для проверки специалистом, а не юридический факт."
        )
        if lim:
            text = _join_sentences(text, f"Важно: {lim[0]}.")
    verification = verify_claims(text, facts=facts, claims=payload.get("claims"))
    return {
        "engine": "rules_template_v2",
        "template_id": "rules_template_v2",
        "text_ru": text,
        "claims": payload.get("claims") or [],
        "unsupported_claims_blocked": bool(verification.get("unsupported_claims_blocked")),
        "verification": verification,
        "ai_used": False,
        "sanitized_inputs": {
            "activity_name": name,
            "finding_label": label,
        },
    }
