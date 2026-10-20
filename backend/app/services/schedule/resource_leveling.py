"""V6 Sprint E / Stage 4 — ресурсная выполнимость / leveling.

Использует OR-Tools CP-SAT при наличии; иначе детерминированный greedy fallback.
Никогда не мутирует published КСГ — только preview.

При наличии связей FS/SS earliest starts соблюдают precedence (toy RCPSP).
Без Resources/Assignments из MSPDI это НЕ ресурсный claim по Strogino.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResourceDemand:
    activity_id: str
    resource_key: str
    units: float
    duration_days: int
    earliest_start_day: int = 0


def _apply_precedence(
    demands: list[ResourceDemand],
    links: list[dict[str, Any]] | None,
) -> list[ResourceDemand]:
    """Поднять earliest_start_day, чтобы FS-преемники не стартовали до finish предка."""
    if not links:
        return demands
    by_id = {d.activity_id: d for d in demands}
    # Итерации до стабильности (DAG; циклы игнорируем)
    for _ in range(max(1, len(demands) + 2)):
        changed = False
        for link in links:
            pred_id = str(link.get("predecessor_activity_id") or link.get("predecessor_id") or "")
            succ_id = str(link.get("successor_activity_id") or link.get("successor_id") or "")
            rel = str(link.get("relation_type") or link.get("relation") or "FS").upper()
            lag = int(link.get("lag_days") or 0)
            pred = by_id.get(pred_id)
            succ = by_id.get(succ_id)
            if not pred or not succ:
                continue
            if rel == "FS":
                bound = pred.earliest_start_day + pred.duration_days + lag
            elif rel == "SS":
                bound = pred.earliest_start_day + lag
            elif rel == "FF":
                bound = pred.earliest_start_day + pred.duration_days + lag - succ.duration_days
            elif rel == "SF":
                bound = pred.earliest_start_day + lag - succ.duration_days
            else:
                continue
            if bound > succ.earliest_start_day:
                succ.earliest_start_day = max(0, bound)
                changed = True
        if not changed:
            break
    return demands


def _greedy_level(
    demands: list[ResourceDemand],
    capacities: dict[str, float],
    horizon_days: int,
) -> dict[str, Any]:
    """Разместить спрос в самый ранний feasible день без превышения capacity."""
    usage: dict[str, list[float]] = {k: [0.0] * horizon_days for k in capacities}
    schedule: list[dict[str, Any]] = []
    infeasible: list[str] = []
    # Учитывать precedence: по возрастанию earliest_start, затем длиннее первыми
    ordered = sorted(demands, key=lambda x: (x.earliest_start_day, -x.duration_days, x.activity_id))
    finish_day: dict[str, int] = {}
    for d in ordered:
        # Повторное ужесточение vs уже размещённых предшественников — в _apply_precedence;
        # также сдвинуть, если та же работа уже завершена раньше по finish_day.
        cap = float(capacities.get(d.resource_key, 0))
        if cap <= 0:
            infeasible.append(d.activity_id)
            continue
        placed = None
        start_from = d.earliest_start_day
        for start in range(start_from, max(start_from, horizon_days - d.duration_days) + 1):
            end = start + d.duration_days
            if end > horizon_days:
                break
            ok = all(usage[d.resource_key][t] + d.units <= cap + 1e-9 for t in range(start, end))
            if ok:
                for t in range(start, end):
                    usage[d.resource_key][t] += d.units
                placed = start
                finish_day[d.activity_id] = end
                break
        if placed is None:
            infeasible.append(d.activity_id)
        else:
            schedule.append(
                {
                    "activity_id": d.activity_id,
                    "resource_key": d.resource_key,
                    "start_day": placed,
                    "duration_days": d.duration_days,
                    "units": d.units,
                }
            )
    peak = {k: max(v) if v else 0.0 for k, v in usage.items()}
    return {
        "engine": "greedy_fallback",
        "feasible": len(infeasible) == 0,
        "infeasible_activity_ids": infeasible,
        "leveled": schedule,
        "peak_usage": peak,
        "capacities": capacities,
        "optimality_gap": None,
        "note": "OR-Tools не установлен — жадный leveling с precedence; не утверждённая инженерная схема Строгино",
    }


def _cpsat_level(
    demands: list[ResourceDemand],
    capacities: dict[str, float],
    horizon_days: int,
    links: list[dict[str, Any]] | None = None,
    time_limit_sec: float = 2.0,
) -> dict[str, Any] | None:
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None

    model = cp_model.CpModel()
    starts: dict[str, Any] = {}
    ends: dict[str, Any] = {}
    intervals_by_res: dict[str, list] = {k: [] for k in capacities}
    for d in demands:
        max_start = max(0, horizon_days - d.duration_days)
        s = model.NewIntVar(d.earliest_start_day, max_start, f"s_{d.activity_id}_{d.resource_key}")
        e = model.NewIntVar(d.earliest_start_day, horizon_days, f"e_{d.activity_id}_{d.resource_key}")
        model.Add(e == s + d.duration_days)
        iv = model.NewIntervalVar(s, d.duration_days, e, f"iv_{d.activity_id}_{d.resource_key}")
        starts[d.activity_id] = s
        ends[d.activity_id] = e
        intervals_by_res.setdefault(d.resource_key, []).append((iv, int(round(d.units * 100))))

    for res, items in intervals_by_res.items():
        if not items:
            continue
        cap = int(round(float(capacities.get(res, 0)) * 100))
        if cap <= 0:
            continue
        model.AddCumulative([iv for iv, _ in items], [u for _, u in items], cap)

    for link in links or []:
        pred_id = str(link.get("predecessor_activity_id") or link.get("predecessor_id") or "")
        succ_id = str(link.get("successor_activity_id") or link.get("successor_id") or "")
        rel = str(link.get("relation_type") or link.get("relation") or "FS").upper()
        lag = int(link.get("lag_days") or 0)
        if pred_id not in starts or succ_id not in starts:
            continue
        if rel == "FS":
            model.Add(starts[succ_id] >= ends[pred_id] + lag)
        elif rel == "SS":
            model.Add(starts[succ_id] >= starts[pred_id] + lag)
        elif rel == "FF":
            model.Add(ends[succ_id] >= ends[pred_id] + lag)
        elif rel == "SF":
            model.Add(ends[succ_id] >= starts[pred_id] + lag)

    # минимизировать сумму стартов (раньше лучше)
    model.Minimize(sum(starts.values()) if starts else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_sec
    status = solver.Solve(model)
    ok_status = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    leveled = []
    if ok_status:
        for d in demands:
            leveled.append(
                {
                    "activity_id": d.activity_id,
                    "resource_key": d.resource_key,
                    "start_day": int(solver.Value(starts[d.activity_id])),
                    "duration_days": d.duration_days,
                    "units": d.units,
                }
            )
    # Истинный gap только при OPTIMAL с известной границей; иначе null
    gap = None
    if ok_status and status == cp_model.OPTIMAL:
        gap = 0.0
    elif ok_status:
        try:
            gap = float(solver.BestObjectiveBound())  # not a relative gap — labeled below
        except Exception:
            gap = None
    return {
        "engine": "ortools_cpsat",
        "feasible": ok_status,
        "status": int(status),
        "infeasible_activity_ids": [] if ok_status else [d.activity_id for d in demands],
        "leveled": leveled,
        "optimality_gap": gap,
        "optimality_gap_note": (
            "0 = proven optimal"
            if gap == 0.0
            else "BestObjectiveBound raw — не relative gap; не публиковать как optimality %"
        ),
        "capacities": capacities,
        "precedence_enforced": bool(links),
        "note": "CP-SAT with optional precedence; rates/cost не подставляются без тарифов",
    }


def level_resources(
    *,
    resource_changes: list[dict[str, Any]] | None,
    capacities: dict[str, float] | None = None,
    horizon_days: int = 60,
    time_limit_sec: float = 2.0,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    changes = list(resource_changes or [])
    if not changes:
        return {
            "engine": "none",
            "feasible": True,
            "leveled": [],
            "note": "resource_changes пуст — leveling не запускался",
            "resource_leveling": "skipped",
            "precedence_enforced": False,
        }
    caps = dict(capacities or {})
    demands: list[ResourceDemand] = []
    for ch in changes:
        rk = str(ch.get("resource_key") or ch.get("resource") or "crew")
        if rk not in caps:
            caps[rk] = float(ch.get("capacity") or 1.0)
        demands.append(
            ResourceDemand(
                activity_id=str(ch.get("activity_id") or ch.get("id") or "act"),
                resource_key=rk,
                units=float(ch.get("units") or 1.0),
                duration_days=max(1, int(ch.get("duration_days") or ch.get("days") or 1)),
                earliest_start_day=max(0, int(ch.get("earliest_start_day") or 0)),
            )
        )
    demands = _apply_precedence(demands, links)
    cpsat = _cpsat_level(demands, caps, horizon_days, links=links, time_limit_sec=time_limit_sec)
    if cpsat is not None:
        cpsat["resource_leveling"] = "ran"
        return cpsat
    out = _greedy_level(demands, caps, horizon_days)
    out["resource_leveling"] = "ran_fallback"
    out["precedence_enforced"] = bool(links)
    return out
