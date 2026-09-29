"""V6 Sprint B — сеть КСГ: календари, валидация связей, CPM (ES/EF/LS/LF, float).

CPM по календарным дням с опциональными рабочими календарями. Без заявления паритета с MS Project —
детерминированно и покрыто тестом на двухветвевом fixture V6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable


RELATIONS = frozenset({"FS", "SS", "FF", "SF"})


@dataclass
class WorkingCalendar:
    """Простой календарь проекта: будни + праздники. Единицы = календарные или рабочие дни."""

    name: str = "default_5d"
    working_weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})  # Mon=0 … Sun=6
    holidays: frozenset[date] = frozenset()
    use_working_days: bool = False

    def is_working(self, d: date) -> bool:
        if not self.use_working_days:
            return True
        return d.weekday() in self.working_weekdays and d not in self.holidays

    def add_duration(self, start: date, duration_days: int) -> date:
        """Длительность inclusive: duration=1 → finish=start; duration=0 → веха на start."""
        if duration_days <= 0:
            return start
        if not self.use_working_days:
            return start + timedelta(days=duration_days - 1)
        d = start
        left = duration_days
        while left > 0:
            if self.is_working(d):
                left -= 1
                if left == 0:
                    return d
            d += timedelta(days=1)
        return d

    def next_start(self, after_finish: date, lag_days: int = 0) -> date:
        """День после finish (+ lag), сдвиг на рабочий день если календарь включён."""
        d = after_finish + timedelta(days=1 + lag_days)
        if not self.use_working_days:
            return d
        while not self.is_working(d):
            d += timedelta(days=1)
        return d

    def add_lag(self, d: date, lag_days: int) -> date:
        if lag_days == 0:
            return d
        if not self.use_working_days:
            return d + timedelta(days=lag_days)
        step = 1 if lag_days > 0 else -1
        left = abs(lag_days)
        cur = d
        while left > 0:
            cur += timedelta(days=step)
            if self.is_working(cur):
                left -= 1
        return cur


@dataclass
class NetActivity:
    id: str
    name: str = ""
    duration: int = 1
    early_start: date | None = None
    early_finish: date | None = None
    late_start: date | None = None
    late_finish: date | None = None
    total_float: int | None = None
    free_float: int | None = None
    is_critical: bool = False
    is_milestone: bool = False
    planned_start: date | None = None
    planned_finish: date | None = None
    remaining_duration: int | None = None


@dataclass
class NetLink:
    predecessor_id: str
    successor_id: str
    relation: str = "FS"
    lag_days: int = 0
    source: str = "UNKNOWN"


@dataclass
class NetworkResult:
    activities: dict[str, NetActivity]
    links: list[NetLink]
    critical_ids: list[str]
    near_critical_ids: list[str]
    project_start: date | None
    project_finish: date | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)


def _as_date(v: date | datetime | str | None) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def duration_inclusive(start: date | None, finish: date | None, fallback: int = 1) -> int:
    if start and finish:
        if finish < start:
            return 0
        return max(0, (finish - start).days + 1)
    return max(0, fallback)


def _duration_offset(duration: int) -> int:
    """Дни от start до finish для inclusive duration (0 → тот же день)."""
    return max(duration - 1, 0)


def validate_network(
    activities: Iterable[NetActivity | dict[str, Any]],
    links: Iterable[NetLink | dict[str, Any]],
) -> list[str]:
    acts = [_coerce_activity(a) for a in activities]
    deps = [_coerce_link(d) for d in links]
    ids = {a.id for a in acts}
    errors: list[str] = []
    for d in deps:
        rel = (d.relation or "FS").upper()
        if rel not in RELATIONS:
            errors.append(f"unsupported_link_type:{rel}:{d.predecessor_id}->{d.successor_id}")
        if d.predecessor_id not in ids:
            errors.append(f"dangling_predecessor:{d.predecessor_id}")
        if d.successor_id not in ids:
            errors.append(f"dangling_successor:{d.successor_id}")
        if d.predecessor_id == d.successor_id:
            errors.append(f"self_link:{d.predecessor_id}")
    if _has_cycle(ids, deps):
        errors.append("cycle_detected")
    return errors


def _has_cycle(ids: set[str], deps: list[NetLink]) -> bool:
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for d in deps:
        if d.predecessor_id in adj and d.successor_id in ids:
            adj[d.predecessor_id].append(d.successor_id)
    state = {i: 0 for i in ids}  # 0=unseen 1=stack 2=done

    def dfs(n: str) -> bool:
        state[n] = 1
        for m in adj.get(n, []):
            if state[m] == 1:
                return True
            if state[m] == 0 and dfs(m):
                return True
        state[n] = 2
        return False

    return any(state[i] == 0 and dfs(i) for i in ids)


def _coerce_activity(a: NetActivity | dict[str, Any]) -> NetActivity:
    if isinstance(a, NetActivity):
        return a
    start = _as_date(a.get("planned_start") or a.get("early_start"))
    finish = _as_date(a.get("planned_end") or a.get("planned_finish") or a.get("early_finish"))
    is_ms = bool(a.get("is_milestone") or a.get("activity_type") == "MILESTONE")
    if "remaining_duration" in a and a.get("remaining_duration") is not None and a.get("duration") is None:
        dur = int(a["remaining_duration"])
    elif a.get("planned_duration") is not None:
        dur = int(a["planned_duration"])
    elif a.get("duration") is not None:
        dur = int(a["duration"])
    elif is_ms:
        dur = 0
    else:
        dur = duration_inclusive(start, finish, fallback=1)
        if dur < 1:
            dur = 1
    if is_ms:
        dur = 0
    else:
        dur = max(0, dur)
    rem = a.get("remaining_duration")
    return NetActivity(
        id=str(a["id"]),
        name=str(a.get("name") or a.get("raw_name") or ""),
        duration=dur,
        is_milestone=is_ms,
        planned_start=start,
        planned_finish=finish,
        remaining_duration=int(rem) if rem is not None else None,
    )


def apply_status_date(
    activities: list[NetActivity],
    status_date: date,
) -> list[NetActivity]:
    """Пересчёт remaining vs status_date; baseline planned_* на работе сохраняются."""
    out: list[NetActivity] = []
    for a in activities:
        na = NetActivity(
            id=a.id,
            name=a.name,
            duration=a.duration,
            is_milestone=a.is_milestone,
            planned_start=a.planned_start,
            planned_finish=a.planned_finish,
            remaining_duration=a.remaining_duration,
        )
        if a.remaining_duration is not None:
            na.duration = max(0, int(a.remaining_duration))
            if na.duration == 0:
                na.is_milestone = True
            out.append(na)
            continue
        ps, pf = a.planned_start, a.planned_finish
        if pf and pf < status_date:
            # Завершено к status — remaining=0; веха на status для сети
            na.duration = 0
            na.is_milestone = True
            na.planned_start = status_date
            na.planned_finish = status_date
        elif ps and ps <= status_date and (pf is None or pf >= status_date):
            if pf:
                na.duration = max(0, (pf - status_date).days + 1)
            else:
                na.duration = max(0, a.duration)
            na.planned_start = status_date
            if na.duration == 0:
                na.is_milestone = True
        elif ps and ps > status_date:
            # Не начато — полный remaining; SNET не раньше status — в forward pass
            na.duration = a.duration if a.duration > 0 or a.is_milestone else max(1, a.duration)
        out.append(na)
    return out


def _coerce_link(d: NetLink | dict[str, Any]) -> NetLink:
    if isinstance(d, NetLink):
        return d
    return NetLink(
        predecessor_id=str(d.get("predecessor_activity_id") or d.get("predecessor_id")),
        successor_id=str(d.get("successor_activity_id") or d.get("successor_id")),
        relation=str(d.get("relation_type") or d.get("relation") or "FS").upper(),
        lag_days=int(d.get("lag_days") or 0),
        source=str(d.get("link_source") or d.get("source") or "UNKNOWN"),
    )


def _constraint_start(
    pred: NetActivity,
    succ: NetActivity,
    link: NetLink,
    cal: WorkingCalendar,
) -> date | None:
    """Самый ранний start преемника по одной связи (forward pass)."""
    if pred.early_start is None or pred.early_finish is None:
        return None
    rel = link.relation.upper()
    lag = link.lag_days
    if rel == "FS":
        return cal.next_start(pred.early_finish, lag)
    if rel == "SS":
        return cal.add_lag(pred.early_start, lag)
    if rel == "FF":
        # FF: finish_j >= finish_i + lag → start_j >= finish_i + lag - (dur-1)
        fin = cal.add_lag(pred.early_finish, lag)
        return fin - timedelta(days=_duration_offset(succ.duration))
    if rel == "SF":
        fin = cal.add_lag(pred.early_start, lag)
        return fin - timedelta(days=_duration_offset(succ.duration))
    return None


def calculate_cpm(
    activities: Iterable[NetActivity | dict[str, Any]],
    links: Iterable[NetLink | dict[str, Any]],
    *,
    calendar: WorkingCalendar | None = None,
    near_critical_days: int = 2,
    target_finish: date | None = None,
    status_date: date | datetime | str | None = None,
) -> NetworkResult:
    cal = calendar or WorkingCalendar()
    acts_list = [_coerce_activity(a) for a in activities]
    sd = _as_date(status_date)
    if sd is not None:
        acts_list = apply_status_date(acts_list, sd)
    deps = [_coerce_link(d) for d in links]
    by_id = {a.id: a for a in acts_list}
    errors = validate_network(acts_list, deps)
    warnings: list[str] = []
    if sd is not None:
        warnings.append(f"status_date={sd.isoformat()} — remaining durations relative to data date")

    # Висячие связи исключить из расчёта, ошибки сохранить
    valid_deps = [
        d
        for d in deps
        if d.predecessor_id in by_id
        and d.successor_id in by_id
        and d.relation.upper() in RELATIONS
        and d.predecessor_id != d.successor_id
    ]

    incoming: dict[str, list[NetLink]] = {i: [] for i in by_id}
    outgoing: dict[str, list[NetLink]] = {i: [] for i in by_id}
    indeg = {i: 0 for i in by_id}
    for d in valid_deps:
        incoming[d.successor_id].append(d)
        outgoing[d.predecessor_id].append(d)
        indeg[d.successor_id] += 1

    # Вперёд: ES/EF
    q = [i for i, deg in indeg.items() if deg == 0]
    # Корни: planned_start или min всех planned
    seeds = [by_id[i].planned_start for i in q if by_id[i].planned_start]
    default_start = min(seeds) if seeds else (sd or date.today())
    if sd is not None and default_start < sd:
        default_start = sd
    order: list[str] = []
    seen = 0
    while q:
        aid = q.pop(0)
        order.append(aid)
        a = by_id[aid]
        reqs: list[date] = []
        for d in incoming[aid]:
            pred = by_id[d.predecessor_id]
            r = _constraint_start(pred, a, d, cal)
            if r:
                reqs.append(r)
        # Ограничения от предшественников + опциональный SNET (planned_start = не раньше)
        if reqs:
            es = max(reqs)
        elif a.planned_start:
            es = a.planned_start
        else:
            es = default_start
        if a.planned_start and es < a.planned_start:
            es = a.planned_start
        if sd is not None and es < sd:
            es = sd
        a.early_start = es
        a.early_finish = cal.add_duration(es, a.duration)
        for d in outgoing[aid]:
            indeg[d.successor_id] -= 1
            if indeg[d.successor_id] == 0:
                q.append(d.successor_id)
        seen += 1

    if seen < len(by_id) and "cycle_detected" not in errors:
        errors.append("incomplete_topo_forward")
        warnings.append("Some activities not scheduled (cycle or disconnected)")

    finishes = [a.early_finish for a in by_id.values() if a.early_finish]
    project_finish = target_finish or (max(finishes) if finishes else None)
    project_start = min((a.early_start for a in by_id.values() if a.early_start), default=None)

    # Назад: LF/LS
    outdeg = {i: len(outgoing[i]) for i in by_id}
    bq = [i for i, deg in outdeg.items() if deg == 0]
    for aid in bq:
        a = by_id[aid]
        a.late_finish = project_finish or a.early_finish
        if a.late_finish is not None:
            a.late_start = a.late_finish - timedelta(days=_duration_offset(a.duration))

    # Обратный топопорядок
    for aid in reversed(order):
        a = by_id[aid]
        succ_constraints: list[date] = []
        for d in outgoing[aid]:
            succ = by_id[d.successor_id]
            if succ.late_start is None or succ.late_finish is None:
                continue
            rel = d.relation.upper()
            lag = d.lag_days
            if rel == "FS":
                # FS назад: finish_i + 1 + lag <= start_j → finish_i <= start_j - 1 - lag
                succ_constraints.append(succ.late_start - timedelta(days=1 + lag))
            elif rel == "SS":
                # SS назад: start_j >= start_i + lag → LS_i <= LS_j - lag
                # как граница LF: LF_i <= LS_j - lag + (dur_i - 1)
                ls_bound = cal.add_lag(succ.late_start, -lag)
                succ_constraints.append(ls_bound + timedelta(days=_duration_offset(a.duration)))
            elif rel == "FF":
                succ_constraints.append(cal.add_lag(succ.late_finish, -lag))
            elif rel == "SF":
                # SF назад: finish_j >= start_i + lag → LS_i <= LF_j - lag
                ls_bound = cal.add_lag(succ.late_finish, -lag)
                succ_constraints.append(ls_bound + timedelta(days=_duration_offset(a.duration)))
        if succ_constraints:
            a.late_finish = min(succ_constraints)
        elif a.late_finish is None:
            a.late_finish = project_finish or a.early_finish
        if a.late_finish is not None:
            a.late_start = a.late_finish - timedelta(days=_duration_offset(a.duration))

    # Резерв (float)
    critical: list[str] = []
    near: list[str] = []
    for a in by_id.values():
        if a.early_start and a.late_start:
            a.total_float = (a.late_start - a.early_start).days
        else:
            a.total_float = None
        # свободный резерв: min ES преемника - (EF+1) для FS, упрощённо
        ff_candidates: list[int] = []
        if a.early_finish:
            for d in outgoing[a.id]:
                if d.relation.upper() != "FS":
                    continue
                succ = by_id[d.successor_id]
                if succ.early_start:
                    ff_candidates.append((succ.early_start - a.early_finish).days - 1 - d.lag_days)
        a.free_float = min(ff_candidates) if ff_candidates else a.total_float
        tf = a.total_float if a.total_float is not None else 999
        a.is_critical = tf <= 0
        if a.is_critical:
            critical.append(a.id)
        elif tf <= near_critical_days:
            near.append(a.id)

    quality = _network_quality(by_id, valid_deps, errors, cal, critical)
    if sd is not None:
        quality["status_date"] = sd.isoformat()
    return NetworkResult(
        activities=by_id,
        links=valid_deps,
        critical_ids=critical if quality.get("can_claim_schedule_impact") else [],
        near_critical_ids=near if quality.get("can_claim_schedule_impact") else [],
        project_start=project_start,
        project_finish=project_finish,
        errors=errors,
        warnings=warnings + list(quality.get("quality_warnings") or []),
        quality=quality,
    )


def _network_quality(
    by_id: dict[str, NetActivity],
    valid_deps: list[NetLink],
    errors: list[str],
    cal: WorkingCalendar,
    critical: list[str],
) -> dict[str, Any]:
    """Честная готовность сети — ноль связей ≠ forecast_available."""
    n_act = len(by_id)
    n_link = len(valid_deps)
    parent = {i: i for i in by_id}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for d in valid_deps:
        if d.predecessor_id in by_id and d.successor_id in by_id:
            union(d.predecessor_id, d.successor_id)
    components = len({find(i) for i in by_id}) if by_id else 0
    linked_ids = set()
    for d in valid_deps:
        linked_ids.add(d.predecessor_id)
        linked_ids.add(d.successor_id)
    open_ends = sum(1 for i in by_id if i not in linked_ids)

    if errors:
        status = "INVALID_NETWORK"
    elif n_act == 0 or n_link == 0:
        status = "NO_NETWORK"
    elif components > 1:
        status = "INCOMPLETE_NETWORK"
    else:
        status = "VALIDATED_NETWORK"

    can_edit = n_act > 0
    can_calculate_dates = n_act > 0 and not errors
    can_claim = status == "VALIDATED_NETWORK" and n_link > 0 and not errors
    # Предпросмотр фрагмента: связи есть, сеть неполная → CPM на связном
    # подмножестве без заявления полного finish проекта.
    fragment_ok = n_act > 0 and n_link > 0 and not errors
    partial_network = fragment_ok and not can_claim
    coverage = (n_link / max(n_act - 1, 1)) if n_act > 1 else (1.0 if n_link == 0 and n_act <= 1 else 0.0)

    qwarn: list[str] = []
    if status == "NO_NETWORK":
        qwarn.append("Нет подтверждённой сети работ — прогноз влияния на срок недоступен")
    elif status == "INCOMPLETE_NETWORK" or partial_network:
        qwarn.append(
            "Прогноз рассчитан по доступному связанному фрагменту сети. "
            "Полное влияние на срок проекта не определяется: график содержит неполную сеть зависимостей."
        )
        qwarn.append(f"Сеть неполная: компонентов={components}, связей={n_link}, работ={n_act}")

    return {
        "activity_count": n_act,
        "link_count": n_link,
        "error_count": len(errors),
        "critical_count": len(critical) if can_claim else 0,
        "calendar": cal.name,
        "use_working_days": cal.use_working_days,
        "dependency_coverage": round(coverage, 4),
        "disconnected_components": components,
        "open_ends": open_ends,
        "quality_status": status,
        "can_edit": can_edit,
        "can_calculate_dates": can_calculate_dates,
        "can_claim_schedule_impact": can_claim,
        "forecast_available": fragment_ok,
        "partial_network": partial_network,
        "quality_warnings": qwarn,
    }


def impact_delay_days(
    result: NetworkResult,
    activity_id: str,
    extra_days: int,
) -> dict[str, Any]:
    """Облегчённый what-if: удлинить duration и пересчитать; delta finish проекта."""
    acts = []
    for a in result.activities.values():
        d = a.duration + (extra_days if a.id == activity_id else 0)
        if a.is_milestone and a.id != activity_id:
            d = 0
        acts.append(
            NetActivity(
                id=a.id,
                name=a.name,
                duration=d,
                is_milestone=a.is_milestone and a.id != activity_id,
                planned_start=a.planned_start or a.early_start,
                planned_finish=None,
            )
        )
    nxt = calculate_cpm(acts, result.links)
    before = result.project_finish
    after = nxt.project_finish
    delta = (after - before).days if before and after else None
    return {
        "activity_id": activity_id,
        "extra_days": extra_days,
        "project_finish_before": before.isoformat() if before else None,
        "project_finish_after": after.isoformat() if after else None,
        "project_finish_delta_days": delta,
        "absorbed_by_float": delta == 0,
        "critical_after": nxt.critical_ids,
        "errors": nxt.errors,
    }


def quality_report_from_db_items(
    items: list[Any],
    deps: list[Any],
) -> dict[str, Any]:
    """Сводка quality gate графика для API."""
    acts = []
    for it in items:
        acts.append(
            {
                "id": str(it.id),
                "name": getattr(it, "raw_name", ""),
                "planned_start": it.planned_start,
                "planned_finish": it.planned_finish,
                "is_milestone": bool(getattr(it, "is_milestone", False)),
            }
        )
    links = []
    for d in deps:
        links.append(
            {
                "predecessor_activity_id": str(d.predecessor_item_id),
                "successor_activity_id": str(d.successor_item_id),
                "relation_type": d.link_type or "FS",
                "lag_days": int((d.lag_minutes or 0) // (24 * 60)),
                "link_source": getattr(d, "link_source", None) or "UNKNOWN",
            }
        )
    res = calculate_cpm(acts, links)
    fs_viol = 0
    for d in deps:
        if (d.link_type or "FS") != "FS":
            continue
        pred = next((i for i in items if i.id == d.predecessor_item_id), None)
        succ = next((i for i in items if i.id == d.successor_item_id), None)
        if not pred or not succ or not pred.planned_finish or not succ.planned_start:
            continue
        if succ.planned_start.date() <= pred.planned_finish.date():
            src = getattr(d, "link_source", None) or "UNKNOWN"
            if src in ("EXPERT_APPROVED", "IMPORTED"):
                fs_viol += 1
    q = dict(res.quality or {})
    can_claim = bool(q.get("can_claim_schedule_impact")) and fs_viol == 0
    return {
        "forecast_available": can_claim,
        "quality_status": q.get("quality_status") or ("NO_NETWORK" if not deps else "INVALID_NETWORK"),
        "can_edit": q.get("can_edit", True),
        "can_calculate_dates": q.get("can_calculate_dates", False),
        "can_claim_schedule_impact": can_claim,
        "errors": res.errors,
        "warnings": res.warnings
        + ([f"approved_fs_date_violations:{fs_viol}"] if fs_viol else []),
        "critical_path": res.critical_ids if can_claim else [],
        "near_critical": res.near_critical_ids if can_claim else [],
        "project_start": res.project_start.isoformat() if res.project_start else None,
        "project_finish": res.project_finish.isoformat() if res.project_finish else None,
        "stats": q,
        "approved_fs_date_violations": fs_viol,
        "link_sources": _count_sources(deps),
        "message_ru": (
            None
            if can_claim
            else "Нет подтверждённой сети работ — импортируйте зависимости или подтвердите экспертно"
        ),
    }


def _count_sources(deps: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in deps:
        k = getattr(d, "link_source", None) or "UNKNOWN"
        out[k] = out.get(k, 0) + 1
    return out


def result_to_json(res: NetworkResult) -> dict[str, Any]:
    return {
        "project_start": res.project_start.isoformat() if res.project_start else None,
        "project_finish": res.project_finish.isoformat() if res.project_finish else None,
        "critical_ids": res.critical_ids,
        "near_critical_ids": res.near_critical_ids,
        "errors": res.errors,
        "warnings": res.warnings,
        "quality": res.quality,
        "activities": {
            aid: {
                "id": a.id,
                "name": a.name,
                "duration": a.duration,
                "early_start": a.early_start.isoformat() if a.early_start else None,
                "early_finish": a.early_finish.isoformat() if a.early_finish else None,
                "late_start": a.late_start.isoformat() if a.late_start else None,
                "late_finish": a.late_finish.isoformat() if a.late_finish else None,
                "total_float": a.total_float,
                "free_float": a.free_float,
                "is_critical": a.is_critical,
            }
            for aid, a in res.activities.items()
        },
    }
