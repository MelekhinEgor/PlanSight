from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.services.knowledge_base.service import KnowledgeBase, load_kb


UNKNOWN_EQUIPMENT = frozenset(
    {"truck_unknown", "vehicle_unknown", "equipment_unknown", "crane_unknown"}
)


def calendar_prior(planned_start: datetime, planned_finish: datetime, at: datetime) -> float:
    """Календарный prior — настраиваемый, некалиброванный."""
    import math

    cfg = get_settings().section("engine").get("calendar") or {}
    if not cfg.get("use_sigmoid", True):
        from datetime import timedelta

        grace = timedelta(hours=float(cfg.get("grace_hours", 12)))
        if planned_start - grace <= at <= planned_finish + grace:
            if planned_start <= at <= planned_finish:
                return float(cfg.get("prior_inside", 0.80))
            if at < planned_start:
                return float(cfg.get("prior_before", 0.25))
            return float(cfg.get("prior_after", 0.35))
        return float(cfg.get("epsilon", 0.05))

    def _sigmoid(x: float) -> float:
        if x >= 0:
            z = math.exp(-x)
            return 1.0 / (1.0 + z)
        z = math.exp(x)
        return z / (1.0 + z)

    eps = float(cfg.get("epsilon", 0.05))
    p_max = float(cfg.get("p_max", 0.85))
    tau_s = float(cfg.get("tau_start_hours", 24.0)) * 3600.0
    tau_f = float(cfg.get("tau_finish_hours", 24.0)) * 3600.0
    t = at.timestamp()
    s = planned_start.timestamp()
    f = planned_finish.timestamp()
    return eps + (p_max - eps) * _sigmoid((t - s) / tau_s) * _sigmoid((f - t) / tau_f)


def equipment_feature_score(
    equipment_vector: dict[str, float],
    work_type: str,
    *,
    kb: KnowledgeBase | None = None,
    observability: float = 1.0,
) -> dict[str, Any]:
    """Ограниченный feature-score heuristic_v2 — НЕ likelihood ratio."""
    kb = kb or load_kb()
    cfg = get_settings().section("engine").get("activity") or {}
    unknown_factor = float(cfg.get("unknown_equipment_factor", 0.35))

    if observability <= 0:
        return {
            "equipment_score": 0.0,
            "contributions": [],
            "note": "нет наблюдаемости — оборудование не влияет на оценку",
        }

    contributions: list[dict[str, Any]] = []
    score = 0.0
    weight_sum = 0.0
    for rule in kb.rules_for_work(work_type):
        conf = float(equipment_vector.get(rule.equipment_type, 0.0))
        if conf <= 0:
            continue
        factor = unknown_factor if rule.equipment_type in UNKNOWN_EQUIPMENT else 1.0
        nec = {"typical": 1.0, "possible": 0.7, "atypical": 0.2}.get(rule.necessity, 0.5)
        w = float(rule.theta) * nec * factor
        part = w * conf
        score += part
        weight_sum += w
        contributions.append(
            {
                "equipment": rule.equipment_type,
                "cv_confidence": conf,
                "theta": rule.theta,
                "necessity": rule.necessity,
                "unknown_factor": factor,
                "contribution": round(part, 4),
            }
        )

    # Нормализация по массе весов typical-правил (0..1)
    typical_mass = sum(
        float(r.theta) * (1.0 if r.necessity == "typical" else 0.7) for r in kb.rules_for_work(work_type)
    ) or 1.0
    equipment_score = max(0.0, min(1.0, score / typical_mass))
    return {
        "equipment_score": equipment_score,
        "contributions": contributions,
        "raw_score": score,
        "typical_mass": typical_mass,
    }


def joint_pattern_boost(
    equipment_vector: dict[str, float],
    work_type: str,
    kb: KnowledgeBase | None = None,
) -> float:
    kb = kb or load_kb()
    present = {e for e, c in equipment_vector.items() if c > 0}
    boost = 0.0
    for pat in kb.joint_patterns:
        needed = set(pat.get("equipment") or [])
        if needed and needed.issubset(present) and work_type in (pat.get("boost_work_types") or []):
            boost += float(pat.get("boost", 0))
    return max(0.0, min(0.3, boost))


def work_observability_factor(work_type: str, kb: KnowledgeBase | None = None) -> str:
    """Наблюдаемость вида работ по KB: DIRECT | INDIRECT | NOT_OBSERVABLE."""
    kb = kb or load_kb()
    meta = kb.work_types.get(work_type) or {}
    mode = str(meta.get("observability") or "DIRECT").upper()
    if mode not in ("DIRECT", "INDIRECT", "NOT_OBSERVABLE"):
        return "DIRECT"
    return mode


def select_work_types(
    equipment_vector: dict[str, float],
    schedule_work_types: list[str],
    kb: KnowledgeBase | None = None,
) -> list[str]:
    """Кандидаты observed activity: только визуально поддержанные типы.

    Календарь не invent'ит гипотезу сам: schedule_work_types лишь слегка
    повышает уже имеющий equipment evidence score. NOT_OBSERVABLE исключается.
    """
    kb = kb or load_kb()
    min_keep = float(get_settings().section("engine").get("activity", {}).get("min_score_keep", 0.12))
    scores: dict[str, float] = {}
    present = {k for k, v in equipment_vector.items() if float(v or 0) > 0}

    for work_type in kb.work_types:
        mode = work_observability_factor(work_type, kb)
        if mode == "NOT_OBSERVABLE":
            continue
        eq = equipment_feature_score(equipment_vector, work_type, kb=kb)
        score = float(eq["equipment_score"])
        # Совместный паттерн при реальной технике
        if joint_pattern_boost(equipment_vector, work_type, kb) > 0 and present:
            score = max(score, float(eq["equipment_score"]) + 0.05)
        if work_type in schedule_work_types and score > 0:
            score += 0.05
        # Режим INDIRECT: нужна совместимая техника
        if mode == "INDIRECT" and score < min_keep:
            continue
        # Режим DIRECT: только при технике или joint pattern
        if score >= min_keep:
            scores[work_type] = score
    # НЕ setdefault типы КСГ без техники — календарь не должен изобретать observed hyp.
    return [code for code, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def infer_multi_label(
    *,
    work_type: str,
    equipment_vector: dict[str, float],
    observability: float,
    calendar_prior_value: float,
    episode_repeat_weight: float = 1.0,
    temporal_support: float = 0.0,
    kb: KnowledgeBase | None = None,
) -> dict[str, Any]:
    """Оценка heuristic_v2: ограниченный blend признаков. НЕ odds / НЕ калиброванная вероятность.

    Multi-label: callers НЕ должны нормализовать между видами работ.
    Отсутствие детекций при observability=0 НЕ снижает score.
    """
    kb = kb or load_kb()
    cfg = get_settings().section("engine").get("activity") or {}
    mode = str(get_settings().section("engine").get("activity_mode") or "heuristic_v2")
    work_obs = work_observability_factor(work_type, kb)
    if work_obs == "NOT_OBSERVABLE":
        return {
            "work_type": work_type,
            "activity_score": 0.0,
            "score_kind": "uncalibrated_score",
            "engine_mode": mode,
            "band": "weak",
            "feature_breakdown": {
                "calendar": 0.0,
                "equipment": 0.0,
                "joint_pattern": 0.0,
                "camera_observability": round(max(0.0, min(1.0, observability)), 4),
                "work_observability": work_obs,
                "temporal_history": 0.0,
            },
            "calendar_prior": max(0.0, min(1.0, calendar_prior_value)),
            "note": "NOT_OBSERVABLE — CV hypothesis запрещена",
            "hypothesis_allowed": False,
        }

    cal = max(0.0, min(1.0, calendar_prior_value))
    eq = equipment_feature_score(
        equipment_vector, work_type, kb=kb, observability=max(0.0, observability)
    )
    joint = joint_pattern_boost(equipment_vector, work_type, kb)
    camera_obs = max(0.0, min(1.0, observability))
    # Вес episode_repeat_weight < 1 снижает вклад техники при статичных повторах
    eq_eff = float(eq["equipment_score"]) * max(0.2, min(1.0, episode_repeat_weight))
    temp = max(0.0, min(1.0, temporal_support))

    w_cal = float(cfg.get("w_calendar", 0.25))
    w_eq = float(cfg.get("w_equipment", 0.45))
    w_joint = float(cfg.get("w_joint", 0.15))
    w_obs = float(cfg.get("w_observability", 0.10))
    w_temp = float(cfg.get("w_temporal", 0.05))
    w_sum = w_cal + w_eq + w_joint + w_obs + w_temp or 1.0

    score = (
        w_cal * cal
        + w_eq * eq_eff
        + w_joint * joint
        + w_obs * camera_obs
        + w_temp * temp
    ) / w_sum
    score = max(0.0, min(1.0, score))

    # Если у работы нет детектируемой техники и ничего не видно — не выдумывать сильный denial
    typical = [r for r in kb.rules_for_work(work_type) if r.necessity == "typical"]
    saw_any = any(equipment_vector.get(r.equipment_type, 0) > 0 for r in kb.rules_for_work(work_type))
    if typical and not saw_any and camera_obs < 0.2:
        note = "недостаточно наблюдаемости — балл ближе к календарному prior"
        score = 0.7 * cal + 0.3 * score
    else:
        note = "heuristic_v2: сумма вкладов признаков, не вероятность"

    strong = float(cfg.get("strong_threshold", 0.65))
    active = float(cfg.get("active_threshold", 0.45))
    band = "strong" if score >= strong else "active" if score >= active else "weak"
    has_visual = saw_any or joint > 0

    return {
        "work_type": work_type,
        "activity_score": score,
        "score_kind": "uncalibrated_score",
        "engine_mode": mode,
        "band": band,
        "hypothesis_allowed": has_visual and work_obs != "NOT_OBSERVABLE",
        "feature_breakdown": {
            "calendar": round(cal, 4),
            "equipment": round(eq_eff, 4),
            "joint_pattern": round(joint, 4),
            "camera_observability": round(camera_obs, 4),
            "work_observability": work_obs,
            "temporal_history": round(temp, 4),
            "weights": {
                "calendar": w_cal,
                "equipment": w_eq,
                "joint": w_joint,
                "observability": w_obs,
                "temporal": w_temp,
            },
            "equipment_detail": eq,
            "episode_repeat_weight": episode_repeat_weight,
        },
        "calendar_prior": cal,
        "note": note,
    }
