"""Сид демо-портфеля PlanSight(3) в backend DB (HTTP product path).

Те же 7 проектов, что frontend DEMO seedState(): имена, карточки, деревья объектов,
КСГ (Strogino из JSON; остальные — компактный demo schedule), cameras для Строгино,
примеры CV-отклонений для маркеров Gantt AI.

Запуск (API может быть остановлен или запущен — пишет в БД напрямую)::

  cd backend
  .venv/Scripts/python.exe scripts/seed_plansight3_portfolio.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import SessionLocal, init_db
from app.db.migrate import ensure_schema_patches
from app.db.models import (
    ActivityHypothesis,
    Camera,
    CameraVisualZone,
    CameraZoneBinding,
    DailySummary,
    Detection,
    Deviation,
    Episode,
    Evidence,
    EvidenceComment,
    Frame,
    InferenceRun,
    Observation,
    Project,
    ProjectObject,
    ProjectionSnapshot,
    ScheduleDependency,
    ScheduleItem,
    ScheduleItemState,
    ScheduleMatch,
    ScheduleVersion,
    StateEvent,
    TemporalState,
)
from app.db.models import WorkType
from app.services.product.demo_integrity import (
    COMMON_BUILDING,
    building_from_ancestors,
    build_alias_index,
    fs_date_ok,
    map_work_name,
)
from app.services.product.portfolio import resolve_schedule_item_objects

STROGINO_JSON = ROOT / "frontend" / "src" / "data" / "strogino360Schedule.json"
LEGACY_DEPS_FIXTURE = ROOT / "docs" / "audit" / "fixtures" / "strogino_legacy_inferred_deps.json"

PROJECT_GROUP = {
    "parkline": "pik",
    "strogino": "pik",
    "amursky": "pik",
    "teatralny": "krost",
    "nevsky": "krost",
    "pravda": "dars-development",
    "plekhanova": "pik",
    "cvlab": "pik",
}

GROUP_NAMES = {
    "pik": "ПИК",
    "krost": "Концерн КРОСТ",
    "dars-development": "DARS Development",
}

COORDS = {
    "parkline": (55.9915, 37.1905),
    "strogino": (55.8034, 37.4021),
    "amursky": (55.8247, 37.8119),
    "teatralny": (55.7934, 37.4936),
    "nevsky": (55.8398, 37.4869),
    "pravda": (55.7930, 37.5880),
    "plekhanova": (55.7450, 37.7650),
    "cvlab": (55.76, 37.64),
}

ANALYSIS = {
    "parkline": "14.09.2026 16:20",
    "strogino": "17.09.2026 12:15",
    "amursky": "17.09.2026 17:10",
    "teatralny": "17.09.2026 14:45",
    "nevsky": "16.09.2026 19:20",
    "pravda": "17.09.2026 11:30",
    "plekhanova": "17.09.2026 16:05",
    "cvlab": "17.09.2026 18:00",
}

CHANGE = {"strogino": 2, "amursky": 2, "teatralny": 1, "nevsky": 1, "pravda": 2, "plekhanova": 3, "cvlab": 0}

# slug, name, developer, region, address, status, image, commissioning, metro, metroWalk
PROJECT_DEFS = [
    ("parkline", "ЖК «Зелёный парк»", "АО СЗ ЗЕЛЕНОГРАДСКИЙ", "Москва", "Зеленоград", "NO_DATA", "/projects/zeleniy-park.png", "II кв. 2027", None, None),
    ("strogino", "ЖК «Строгино 360»", "ООО СЗ ЛУЧ", "Москва", "Строгино", "DELAYED", "/projects/strogino-360.png", "IV кв. 2028", None, None),
    ("amursky", "ЖК «Амурский парк»", "АО СЗ ГЛОРИ", "Москва", "Район Гольяново", "ON_TRACK", "/projects/amursky-park.png", "I кв. 2029", "Черкизовская", "14 мин пешком"),
    ("teatralny", "ЖК «Театральный квартал»", "ООО СЗ ФРИЗ-ИНВЕСТ", "Москва", "ул. Ротмистрова", "AT_RISK", "/projects/teatralny-kvartal.png", "IV кв. 2026", "Октябрьское поле", "13 мин пешком"),
    ("nevsky", "NEVSKY PLAZA", "ООО СЗ ПОДОЛИНО", "Москва", "Войковский район", "ON_TRACK", "/projects/nevsky-plaza.png", "II кв. 2027", "Водный стадион", "12 мин пешком"),
    ("pravda", "Апартаменты «Правда»", "ООО СЗ ВЕГА", "Москва", "Район Беговой", "AT_RISK", "/projects/pravda.png", "II кв. 2027", "Савёловская", "10 мин пешком"),
    ("plekhanova", "ЖК «Плеханова 11»", "ООО СЗ ЯСЕНЕВЫЙ ПАРК", "Москва", "Район Перово", "DELAYED", "/projects/plekhanova-11.png", "III кв. 2026", "Шоссе Энтузиастов", "25 мин пешком"),
    (
        "cvlab",
        "CV Lab · К1/К2 (синтетический контур)",
        "PlanSight Demo",
        "Москва",
        "Испытательный полигон (не Строгино)",
        "AT_RISK",
        None,
        "—",
        None,
        None,
    ),
]

OBJECT_TREES = {
    "parkline": [
        ("Этап строительства 1", "stage", [("Корпус 1", "building"), ("Корпус 2", "building")]),
        ("Этап строительства 2", "stage", [("Детский сад", "building"), ("Паркинг", "parking")]),
    ],
    "strogino": [
        (
            "Этап строительства 1",
            "stage",
            [
                ("Корпус 1.1.1", "building"),
                ("Корпус 1.1.2", "building"),
                ("Корпус 1.1.3", "building"),
                ("Корпус 1.1.4", "building"),
                ("Корпус 1.1.5", "building"),
            ],
        ),
        (
            "Этап строительства 2",
            "stage",
            [
                ("Корпус 1.2", "building"),
                ("Корпус 1.3", "building"),
                ("Наружные сети / благоустройство", "site"),
                (COMMON_BUILDING, "site"),
            ],
        ),
    ],
    "cvlab": [
        (
            "Испытательный контур",
            "stage",
            [
                ("Зона К1", "building"),
                ("Зона К2", "building"),
            ],
        ),
    ],
    "amursky": [
        ("Этап строительства 1", "stage", [("Корпус 1", "building"), ("Корпус 2", "building"), ("Корпус 3", "building"), ("Паркинг", "parking")]),
    ],
    "teatralny": [
        ("Этап строительства 1", "stage", [("Корпус 1", "building"), ("Корпус 2", "building"), ("Корпус 3", "building"), ("Корпус 4", "building")]),
    ],
    "nevsky": [
        ("Этап строительства 1", "stage", [("Башня A", "building"), ("Башня B", "building"), ("Стилобат", "building")]),
    ],
    "pravda": [
        ("Этап строительства 1", "stage", [("Башня", "building"), ("Коммерция", "building"), ("Паркинг", "parking")]),
    ],
    "plekhanova": [
        ("Этап строительства 1", "stage", [("Корпус 1", "building"), ("Корпус 2", "building"), ("Корпус 3", "building"), ("Корпус 4", "building")]),
    ],
}

DEMO_SCHEDULE = [
    ("A01", "Подготовка", "Получение РД", "компл.", 1, 100, 100, "2026-07-01", "2026-07-18", "2026-07-01", "2026-07-18", ""),
    ("A02", "Подготовка", "Разработка ППР", "компл.", 1, 100, 100, "2026-07-12", "2026-07-28", "2026-07-12", "2026-07-28", "A01SS+5"),
    ("A03", "Подготовка", "Мобилизация техники", "компл.", 1, 100, 100, "2026-07-22", "2026-08-05", "2026-07-22", "2026-08-05", "A02FS"),
    ("A04", "Подготовка", "Организация стройплощадки", "компл.", 1, 100, 100, "2026-08-01", "2026-08-14", "2026-08-01", "2026-08-14", "A03FS"),
    ("A05", "Нулевой цикл", "Разработка котлована", "м3", 18420, 100, 100, "2026-08-10", "2026-08-28", "2026-08-10", "2026-08-28", "A04FS"),
    ("A06", "Нулевой цикл", "Вывоз грунта", "м3", 15200, 100, 100, "2026-08-12", "2026-08-30", "2026-08-12", "2026-08-30", "A05SS+2"),
    ("A07", "Нулевой цикл", "Устройство свайного основания", "шт.", 640, 100, 92, "2026-08-29", "2026-09-14", "2026-08-29", "2026-09-25", "A05FS"),
    ("A08", "Нулевой цикл", "Ростверк", "м3", 2100, 88, 70, "2026-09-10", "2026-10-02", "2026-09-12", "2026-10-06", "A07SS+8"),
    ("A09", "Нулевой цикл", "Фундаментная плита", "м3", 4250, 65, 48, "2026-09-08", "2026-10-07", "2026-09-10", "2026-10-12", "A07FS"),
    ("A10", "Каркас", "Монолитный каркас секция 1", "м3", 5200, 42, 28, "2026-09-01", "2026-11-20", "2026-09-05", "2026-11-28", "A09FS"),
    ("A11", "Каркас", "Монолитный каркас секция 2", "м3", 4650, 30, 12, "2026-10-25", "2026-12-16", None, "2026-12-24", "A10SS+12"),
    ("A12", "Каркас", "Лестничные клетки", "м3", 980, 18, 5, "2026-11-10", "2026-12-20", None, "2026-12-28", "A10SS+20"),
    ("A13", "Контур", "Кладка наружных стен", "м2", 12400, 10, 4, "2026-10-20", "2026-11-24", None, "2026-12-02", "A10SS+8"),
    ("A14", "Контур", "Монтаж окон", "м2", 5200, 0, 0, "2026-11-15", "2026-12-14", None, "2026-12-20", "A13SS+10"),
    ("A15", "Контур", "Устройство фасада", "м2", 16800, 0, 0, "2026-12-01", "2027-01-17", None, "2027-01-28", "A14SS+10"),
    ("A16", "Контур", "Кровля", "м2", 3200, 0, 0, "2026-12-05", "2026-12-30", None, "2027-01-10", "A11FS"),
    ("A17", "Инженерия", "Внутренние сети ХВС/ГВС", "компл.", 1, 0, 0, "2026-12-20", "2027-02-15", None, "2027-02-22", "A12FS"),
    ("A18", "Инженерия", "Электромонтажные работы", "компл.", 1, 0, 0, "2027-01-10", "2027-03-05", None, "2027-03-12", "A16FS"),
    ("A19", "Инженерия", "Вентиляция и кондиционирование", "компл.", 1, 0, 0, "2027-01-20", "2027-03-20", None, "2027-03-28", "A17SS+15"),
    ("A20", "Отделка", "Черновая отделка", "м2", 28600, 0, 0, "2027-02-15", "2027-04-20", None, "2027-04-28", "A17FS"),
    ("A21", "Отделка", "Чистовая отделка МОП", "м2", 4200, 0, 0, "2027-04-01", "2027-05-25", None, "2027-06-05", "A20SS+20"),
    ("A22", "Отделка", "Благоустройство территории", "компл.", 1, 0, 0, "2027-05-10", "2027-06-30", None, "2027-07-10", "A15FS"),
]

# Корпуса демо-КСГ round-robin на имена листовых объектов
def _leaf_buildings(slug: str) -> list[str]:
    out: list[str] = []
    for _stage, _t, kids in OBJECT_TREES.get(slug, []):
        for name, typ in kids:
            if typ in ("building", "parking", "site"):
                out.append(name)
    return out or ["Объект 1"]


def _wipe_all_projects(db) -> list[int]:
    ids = [p.id for p in db.query(Project).all()]
    for project_id in ids:
        cams = db.query(Camera).filter(Camera.project_id == project_id).all()
        cam_ids = [c.id for c in cams]
        frames = db.query(Frame).filter(Frame.project_id == project_id).all()
        frame_ids = [f.id for f in frames]
        runs = db.query(InferenceRun).filter(InferenceRun.frame_id.in_(frame_ids)).all() if frame_ids else []
        run_ids = [r.id for r in runs]
        hyps = db.query(ActivityHypothesis).filter(ActivityHypothesis.camera_id.in_(cam_ids)).all() if cam_ids else []
        hyp_ids = [h.id for h in hyps]
        if hyp_ids:
            db.query(ScheduleMatch).filter(ScheduleMatch.hypothesis_id.in_(hyp_ids)).delete(synchronize_session=False)
            db.query(Evidence).filter(Evidence.hypothesis_id.in_(hyp_ids)).delete(synchronize_session=False)
            db.query(StateEvent).filter(StateEvent.hypothesis_id.in_(hyp_ids)).delete(synchronize_session=False)
            db.query(ActivityHypothesis).filter(ActivityHypothesis.id.in_(hyp_ids)).delete(synchronize_session=False)
        db.query(EvidenceComment).filter(EvidenceComment.project_id == project_id).delete(synchronize_session=False)
        db.query(ProjectObject).filter(ProjectObject.project_id == project_id).delete(synchronize_session=False)
        db.query(Deviation).filter(Deviation.project_id == project_id).delete(synchronize_session=False)
        db.query(Episode).filter(Episode.project_id == project_id).delete(synchronize_session=False)
        db.query(TemporalState).filter(TemporalState.project_id == project_id).delete(synchronize_session=False)
        db.query(ProjectionSnapshot).filter(ProjectionSnapshot.project_id == project_id).delete(synchronize_session=False)
        db.query(DailySummary).filter(DailySummary.project_id == project_id).delete(synchronize_session=False)
        if run_ids:
            db.query(Observation).filter(Observation.inference_run_id.in_(run_ids)).delete(synchronize_session=False)
            db.query(Detection).filter(Detection.inference_run_id.in_(run_ids)).delete(synchronize_session=False)
            db.query(InferenceRun).filter(InferenceRun.id.in_(run_ids)).delete(synchronize_session=False)
        for fr in frames:
            db.delete(fr)
        versions = db.query(ScheduleVersion).filter(ScheduleVersion.project_id == project_id).all()
        for v in versions:
            items = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == v.id).all()
            item_ids = [i.id for i in items]
            if item_ids:
                db.query(ScheduleItemState).filter(ScheduleItemState.schedule_item_id.in_(item_ids)).delete(synchronize_session=False)
            db.query(ScheduleDependency).filter(ScheduleDependency.schedule_version_id == v.id).delete(synchronize_session=False)
            db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == v.id).delete(synchronize_session=False)
            db.delete(v)
        db.query(CameraZoneBinding).filter(CameraZoneBinding.project_id == project_id).delete(synchronize_session=False)
        if cam_ids:
            db.query(CameraVisualZone).filter(CameraVisualZone.camera_id.in_(cam_ids)).delete(synchronize_session=False)
        for c in cams:
            db.delete(c)
        db.delete(db.get(Project, project_id))
    db.commit()
    return ids


def _parse_day(s: str | None) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return datetime.fromisoformat(s[:10])
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if m:
        d, mo, y = m.groups()
        return datetime(int(y), int(mo), int(d))
    return None


def _parse_pred(token: str) -> tuple[str, str, int] | None:
    """Разбор 'A02FS', 'A01SS+5'. Код не должен глотать FS/SS/FF/SF."""
    token = token.strip()
    if not token:
        return None
    m = re.match(r"^([A-Za-z0-9.]+?)(?:(FS|SS|FF|SF))([+-]\d+)?$", token, re.I)
    if m:
        return m.group(1), m.group(2).upper(), int(m.group(3) or 0)
    m = re.match(r"^([A-Za-z0-9.]+)$", token)
    if m:
        return m.group(1), "FS", 0
    return None


def _create_objects(db, project_id: int, slug: str) -> dict[str, ProjectObject]:
    by_name: dict[str, ProjectObject] = {}
    sort = 0
    for stage_name, stage_type, kids in OBJECT_TREES.get(slug, []):
        stage = ProjectObject(
            project_id=project_id,
            parent_id=None,
            name=stage_name,
            object_type=stage_type,
            sort_order=sort,
        )
        db.add(stage)
        db.flush()
        sort += 1
        for child_name, child_type in kids:
            child = ProjectObject(
                project_id=project_id,
                parent_id=stage.id,
                name=child_name,
                object_type=child_type,
                sort_order=sort,
            )
            db.add(child)
            db.flush()
            by_name[child_name] = child
            sort += 1
    return by_name


def _create_demo_schedule(db, project: Project, slug: str, buildings: list[str]) -> ScheduleVersion:
    now = datetime.utcnow()
    wbs_map: dict[str, str] = {}
    wbs: list[dict] = []
    root_id = f"{slug}-wbs-root"
    wbs.append({"id": root_id, "parent_id": None, "name": project.name, "code": "0", "level": 0, "sort_order": 0})
    for i, name in enumerate(sorted({r[1] for r in DEMO_SCHEDULE})):
        nid = f"{slug}-wbs-{i+1}"
        wbs_map[name] = nid
        wbs.append({"id": nid, "parent_id": root_id, "name": name, "code": f"1.{i+1}", "level": 1, "sort_order": i + 1})

    version = ScheduleVersion(
        project_id=project.id,
        source_path=f"{slug}_demo_schedule.xlsx",
        checksum=f"p3-demo-{slug}",
        imported_at=now,
        is_active=True,
        kind="CURRENT",
        version_state="PUBLISHED",
        revision=1,
        published_at=now,
        updated_at=now,
        wbs_json=json.dumps(wbs, ensure_ascii=False),
        source_filename="demo_schedule.xlsx",
    )
    db.add(version)
    db.flush()

    wt_by_code = {w.code: w.id for w in db.query(WorkType).all()}
    alias_index = build_alias_index()
    # Явный корпус из индекса DEMO-строки → листовой объект (без modulo fallback для остатка)
    leaf_buildings = [b for b in buildings if b != COMMON_BUILDING]
    by_code: dict[str, ScheduleItem] = {}
    for i, row in enumerate(DEMO_SCHEDULE):
        code, wbs_name, name, unit, qty, plan, fact, start, end, actual, forecast, pred = row
        building = leaf_buildings[i] if i < len(leaf_buildings) else None
        b_src = "demo_table" if building else "unassigned"
        ps = _parse_day(start) or datetime(2026, 7, 1)
        pe = _parse_day(end) or ps
        wm = map_work_name(name, wt_by_code=wt_by_code, alias_index=alias_index)
        item = ScheduleItem(
            schedule_version_id=version.id,
            external_id=code,
            raw_name=name,
            work_type_id=wm.work_type_id,
            planned_start=ps,
            planned_finish=pe,
            building=building,
            building_normalized=building,
            building_source=b_src,
            unit=unit,
            planned_quantity=float(qty),
            planned_progress=float(plan),
            actual_progress=float(fact),
            forecast_end=_parse_day(forecast) or pe,
            actual_start=_parse_day(actual),
            sort_order=i + 1,
            mapping_status=wm.mapping_status,
            canonical_work_code=wm.work_type_code,
            canonical_work_name=name,
            wbs_node_id=wbs_map.get(wbs_name, root_id),
            observability_mode=wm.observability,
            observability_reason=wm.reason,
        )
        db.add(item)
        db.flush()
        by_code[code] = item

    for i, row in enumerate(DEMO_SCHEDULE):
        pred = row[11]
        if not pred:
            continue
        for token in re.split(r"[;,]", pred):
            parsed = _parse_pred(token.strip())
            if not parsed:
                continue
            pcode, rel, lag = parsed
            pred_item = by_code.get(pcode)
            succ = by_code.get(row[0])
            if not pred_item or not succ:
                continue
            # Оставляем только date-feasible экспертные демо-связи
            if rel == "FS" and not fs_date_ok(
                pred_item.planned_finish, succ.planned_start, lag * 24 * 60
            ):
                continue
            db.add(
                ScheduleDependency(
                    schedule_version_id=version.id,
                    predecessor_item_id=pred_item.id,
                    successor_item_id=succ.id,
                    link_type=rel,
                    lag_minutes=lag * 24 * 60,
                    predecessor_uid=pred_item.external_id,
                    successor_uid=succ.external_id,
                    link_source="EXPERT_APPROVED",
                )
            )
    return version


def _code_sort_key(code: str) -> list[int]:
    parts: list[int] = []
    for p in str(code).split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def _create_strogino_schedule(db, project: Project, buildings: list[str]) -> ScheduleVersion:
    """Импорт Strogino JSON с реальной иерархией WBS из dotted-кодов (не плоские корзины wbs-name)."""
    now = datetime.utcnow()
    rows = json.loads(STROGINO_JSON.read_text(encoding="utf-8"))
    by_code = {str(r["code"]): r for r in rows}
    codes = list(by_code.keys())
    parents: set[str] = set()
    for c in codes:
        prefix = c + "."
        if any(o != c and o.startswith(prefix) for o in codes):
            parents.add(c)
    leaves = [r for r in rows if str(r["code"]) not in parents]

    def wbs_id(code: str) -> str:
        return f"strogino-wbs-{code}"

    # Иерархический WBS: каждый summary-код → узел; root = код "1" или synthetic
    wbs: list[dict] = []
    if "1" in parents:
        root_id = wbs_id("1")
        root_name = str(by_code["1"].get("name") or project.name)
        wbs.append(
            {
                "id": root_id,
                "parent_id": None,
                "name": root_name,
                "code": "1",
                "level": 0,
                "sort_order": 0,
            }
        )
        summary_codes = sorted((c for c in parents if c != "1"), key=_code_sort_key)
    else:
        root_id = "strogino-wbs-root"
        wbs.append(
            {
                "id": root_id,
                "parent_id": None,
                "name": project.name,
                "code": "0",
                "level": 0,
                "sort_order": 0,
            }
        )
        summary_codes = sorted(parents, key=_code_sort_key)

    for i, code in enumerate(summary_codes):
        parent_code = code.rsplit(".", 1)[0] if "." in code else None
        if parent_code and parent_code in parents:
            parent_id = wbs_id(parent_code)
        else:
            parent_id = root_id
        level = code.count(".")
        if "1" not in parents:
            level = code.count(".") + 1
        row = by_code[code]
        wbs.append(
            {
                "id": wbs_id(code),
                "parent_id": parent_id,
                "name": str(row.get("name") or code),
                "code": code,
                "level": level,
                "sort_order": i + 1,
            }
        )

    version = ScheduleVersion(
        project_id=project.id,
        source_path="strogino360.json",
        checksum="p3-strogino360-v6a",
        imported_at=now,
        is_active=True,
        kind="CURRENT",
        version_state="PUBLISHED",
        revision=1,
        published_at=now,
        updated_at=now,
        wbs_json=json.dumps(wbs, ensure_ascii=False),
        source_filename="PlanSight_Строгино360_4_колонки_для_загрузки.xlsx",
    )
    db.add(version)
    db.flush()

    known = set(buildings) | {COMMON_BUILDING}
    wt_by_code = {w.code: w.id for w in db.query(WorkType).all()}
    alias_index = build_alias_index()
    as_of = datetime(2026, 9, 17)
    created: list[ScheduleItem] = []
    # Архив: старый seed выдумывал FS-цепочки; мы их НЕ воссоздаём (V6 P0-01).
    LEGACY_DEPS_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    if not LEGACY_DEPS_FIXTURE.exists():
        LEGACY_DEPS_FIXTURE.write_text(
            json.dumps(
                {
                    "note": "Legacy INFERRED_UNVERIFIED FS chains removed in V6 Sprint A",
                    "rule": "Do not use for CPM/optimization",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    for i, r in enumerate(leaves):
        ps = _parse_day(r.get("start")) or as_of
        pe = _parse_day(r.get("end")) or ps
        code = str(r.get("code") or "")
        name = str(r.get("name") or "")
        parent_code = code.rsplit(".", 1)[0] if "." in code else None
        if parent_code and parent_code in parents:
            node_id = wbs_id(parent_code)
        else:
            node_id = root_id
        building, b_src = building_from_ancestors(code, by_code, known)
        wm = map_work_name(name, wt_by_code=wt_by_code, alias_index=alias_index)
        # Editorial демо-прогресс (source = DEMO, не факт CV / подрядчика)
        if pe.date() < as_of.date():
            plan, fact = 100.0, 100.0 if i % 5 else 85.0
        elif ps.date() > as_of.date():
            plan, fact = 0.0, 0.0
        else:
            plan, fact = 55.0, 30.0 if i % 3 else 18.0
        # forecast остаётся на плане, пока editorial lag seed не скорректирует позже
        item = ScheduleItem(
            schedule_version_id=version.id,
            external_id=code,
            raw_name=name,
            work_type_id=wm.work_type_id,
            planned_start=ps,
            planned_finish=pe,
            building=building,
            building_normalized=building,
            building_source=b_src,
            unit="компл.",
            planned_progress=plan,
            actual_progress=fact,
            forecast_end=pe,
            actual_start=ps if fact > 0 else None,
            sort_order=i + 1,
            mapping_status=wm.mapping_status,
            canonical_work_code=wm.work_type_code,
            canonical_work_name=name[:255],
            wbs_node_id=node_id,
            observability_mode=wm.observability,
            observability_reason=wm.reason,
            is_milestone=ps.date() == pe.date(),
        )
        db.add(item)
        created.append(item)
    db.flush()
    # Сеть unknown: без выдуманных FS (в JSON нет predecessors)
    return version


def _write_minimal_png(path: Path, *, w: int = 64, h: int = 48, rgb: tuple[int, int, int] = (90, 110, 130)) -> None:
    """Крошечный валидный PNG без OpenCV (синтетический тест-кадр, не фото площадки)."""
    _write_scene_png(path, w=w, h=h, bg=rgb, blobs=[])


def _write_scene_png(
    path: Path,
    *,
    w: int = 640,
    h: int = 480,
    bg: tuple[int, int, int] = (70, 90, 110),
    left_bg: tuple[int, int, int] | None = None,
    right_bg: tuple[int, int, int] | None = None,
    blobs: list[tuple[int, int, int, int, tuple[int, int, int]]] | None = None,
) -> None:
    """Синтетическая сцена PNG: опционально половины K1/K2 + прямоугольники (не фото площадки)."""
    import struct
    import zlib

    path.parent.mkdir(parents=True, exist_ok=True)
    lb = left_bg or bg
    rb = right_bg or bg
    rows: list[bytes] = []
    mid = w // 2
    blob_list = blobs or []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            color = lb if x < mid else rb
            for x1, y1, x2, y2, c in blob_list:
                if x1 <= x < x2 and y1 <= y < y2:
                    color = c
                    break
            row.extend(color)
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)
    comp = zlib.compress(raw, 6)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")
    path.write_bytes(png)


def _seed_cv_lab(db, project: Project, by_name: dict[str, ProjectObject]) -> ScheduleVersion:
    """Отдельный CV fixture (V6): синтетические кадры + VERIFIED K1/K2 — не бренд-фото Strogino."""
    from app.db.models import ModelVersion

    now = datetime.utcnow()
    wt_by_code = {w.code: w.id for w in db.query(WorkType).all()}
    alias_index = build_alias_index()
    root = "cvlab-wbs-root"
    wbs = [
        {"id": root, "parent_id": None, "name": project.name, "code": "0", "level": 0, "sort_order": 0},
        {"id": "cvlab-wbs-1", "parent_id": root, "name": "Земляные работы", "code": "1.1", "level": 1, "sort_order": 1},
    ]
    version = ScheduleVersion(
        project_id=project.id,
        source_path="cvlab_fixture",
        checksum="v6a-cvlab",
        imported_at=now,
        is_active=True,
        kind="CURRENT",
        version_state="PUBLISHED",
        revision=1,
        published_at=now,
        updated_at=now,
        wbs_json=json.dumps(wbs, ensure_ascii=False),
        source_filename="cvlab_fixture.xlsx",
    )
    db.add(version)
    db.flush()

    rows = [
        ("C1", "Разработка котлована зона К1", "Зона К1", "2026-09-10", "2026-09-15"),
        ("C2", "Вывоз грунта зона К1", "Зона К1", "2026-09-16", "2026-09-20"),
        ("C3", "Разработка котлована зона К2", "Зона К2", "2026-09-21", "2026-09-25"),
        ("C4", "Вывоз грунта зона К2", "Зона К2", "2026-09-26", "2026-09-30"),
    ]
    items: list[ScheduleItem] = []
    for i, (code, name, building, start, end) in enumerate(rows):
        wm = map_work_name(name, wt_by_code=wt_by_code, alias_index=alias_index)
        ps, pe = _parse_day(start), _parse_day(end)
        it = ScheduleItem(
            schedule_version_id=version.id,
            external_id=code,
            raw_name=name,
            work_type_id=wm.work_type_id,
            planned_start=ps,
            planned_finish=pe,
            building=building,
            building_normalized=building,
            building_source="expert_fixture",
            planned_progress=60.0,
            actual_progress=25.0,
            forecast_end=pe,
            sort_order=i + 1,
            mapping_status=wm.mapping_status,
            canonical_work_code=wm.work_type_code,
            canonical_work_name=name,
            wbs_node_id="cvlab-wbs-1",
            observability_mode=wm.observability,
            observability_reason=wm.reason,
            project_object_id=(by_name.get(building).id if by_name.get(building) else None),
        )
        db.add(it)
        items.append(it)
    db.flush()
    # Связная экспертная FS-цепочка (date-valid) — одна компонента для честного what-if только на CV Lab
    for pred, succ, pu, su in (
        (items[0], items[1], "C1", "C2"),
        (items[1], items[2], "C2", "C3"),
        (items[2], items[3], "C3", "C4"),
    ):
        if fs_date_ok(pred.planned_finish, succ.planned_start):
            db.add(
                ScheduleDependency(
                    schedule_version_id=version.id,
                    predecessor_item_id=pred.id,
                    successor_item_id=succ.id,
                    link_type="FS",
                    lag_minutes=0,
                    predecessor_uid=pu,
                    successor_uid=su,
                    link_source="EXPERT_APPROVED",
                )
            )

    cam = Camera(project_id=project.id, name="CAM-01 · CV Lab", building_hint=None, enabled=True)
    db.add(cam)
    db.flush()
    z1 = CameraVisualZone(
        project_id=project.id,
        camera_id=cam.id,
        name="Зона К1",
        zone_key="K1",
        polygon_norm_json="[[0.0,0.0],[0.5,0.0],[0.5,1.0],[0.0,1.0]]",
        status="active",
        zone_status="VERIFIED",
        geometry_source="manual",
    )
    z2 = CameraVisualZone(
        project_id=project.id,
        camera_id=cam.id,
        name="Зона К2",
        zone_key="K2",
        polygon_norm_json="[[0.5,0.0],[1.0,0.0],[1.0,1.0],[0.5,1.0]]",
        status="active",
        zone_status="VERIFIED",
        geometry_source="manual",
    )
    db.add(z1)
    db.add(z2)
    db.flush()
    db.add(
        CameraZoneBinding(
            project_id=project.id,
            camera_id=cam.id,
            visual_zone_key="K1",
            visual_zone_id=z1.id,
            building="Зона К1",
            binding_status="VERIFIED",
            binding_source="human_verified",
        )
    )
    db.add(
        CameraZoneBinding(
            project_id=project.id,
            camera_id=cam.id,
            visual_zone_key="K2",
            visual_zone_id=z2.id,
            building="Зона К2",
            binding_status="VERIFIED",
            binding_source="human_verified",
        )
    )

    mv = db.query(ModelVersion).order_by(ModelVersion.id.desc()).first()
    if mv is None:
        mv = ModelVersion(name="cvlab-synthetic", weights_path="synthetic", weights_sha256="0" * 64)
        db.add(mv)
        db.flush()

    frames_dir = ROOT / "data" / "uploads" / f"project_{project.id}" / "cvlab_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    t0 = datetime(2026, 9, 17, 10, 0, 0)
    # 10 последовательных синтетических кадров (стабильный CAM-01). НЕ реальные фото стройки.
    # K1 = левая половина, K2 = правая. Относительные пути для портативного ZIP.
    seq = [
        # (minute_offset, zone, equipment, blob_xyxy_px, left_bg, right_bg)
        (0, z1, "excavator", (40, 120, 220, 360), (55, 95, 125), (90, 90, 90)),
        (10, z1, "excavator", (50, 130, 230, 370), (55, 95, 125), (90, 90, 90)),
        (20, z1, "dump_truck", (60, 180, 250, 400), (55, 95, 125), (90, 90, 90)),
        (30, z1, "excavator", (45, 125, 225, 365), (55, 95, 125), (90, 90, 90)),
        (40, z2, "excavator", (380, 110, 560, 350), (90, 90, 90), (70, 105, 120)),
        (50, z2, "excavator", (390, 120, 570, 360), (90, 90, 90), (70, 105, 120)),
        (60, z2, "dump_truck", (400, 170, 590, 410), (90, 90, 90), (70, 105, 120)),
        (70, z1, "excavator", (55, 140, 235, 380), (55, 95, 125), (90, 90, 90)),
        (80, z2, "excavator", (385, 115, 565, 355), (90, 90, 90), (70, 105, 120)),
        (90, z1, "dump_truck", (70, 190, 260, 420), (55, 95, 125), (90, 90, 90)),
    ]
    W, H = 640, 480
    frame_ids: list[int] = []
    k1_frame_ids: list[int] = []
    for i, (mins, zone, eq, box, lbg, rbg) in enumerate(seq):
        x1, y1, x2, y2 = box
        path = frames_dir / f"synth_{i:02d}.png"
        blob_color = (220, 160, 40) if eq == "excavator" else (180, 70, 50)
        _write_scene_png(
            path,
            w=W,
            h=H,
            left_bg=lbg,
            right_bg=rbg,
            blobs=[(x1, y1, x2, y2, blob_color)],
        )
        rel = f"data/uploads/project_{project.id}/cvlab_frames/synth_{i:02d}.png"
        fr = Frame(
            project_id=project.id,
            camera_id=cam.id,
            captured_at=t0 + timedelta(minutes=mins),
            file_path=rel,
            sha256=f"{'b' * 60}{i:04d}",
            ingest_status="READY",
            image_quality="OK",
            quality_json=json.dumps(
                {
                    "synthetic": True,
                    "data_origin": "SYNTHETIC_TEST_FIXTURE",
                    "license": "synthetic_generated_in_repo",
                    "not_real_site_photo": True,
                    "camera": "CAM-01",
                    "sequence_index": i,
                }
            ),
        )
        db.add(fr)
        db.flush()
        frame_ids.append(fr.id)
        if zone.id == z1.id:
            k1_frame_ids.append(fr.id)
        run = InferenceRun(
            frame_id=fr.id,
            model_version_id=mv.id,
            schedule_version_id=version.id,
            kb_version="kb_v2",
            engine_version="cvlab-synthetic",
            config_hash="cvlab",
            status="COMPLETED",
            finished_at=t0 + timedelta(minutes=mins),
        )
        db.add(run)
        db.flush()
        db.add(
            Detection(
                inference_run_id=run.id,
                equipment_code=eq,
                raw_class_name=eq,
                confidence=0.88 + (i % 5) * 0.01,
                bbox_norm_json=json.dumps(
                    {"x1": x1 / W, "y1": y1 / H, "x2": x2 / W, "y2": y2 / H}
                ),
                zone_id=zone.id,
                zone_ambiguous=False,
            )
        )
        db.add(
            Observation(
                inference_run_id=run.id,
                visual_zone_id=zone.id,
                equipment_vector_json=json.dumps({eq: 0.9}),
                quality_json=json.dumps({"synthetic": True, "zones": {zone.zone_key: {eq: 0.9}}}),
                observability=1.0,
            )
        )

    # Честная метка: SYNTHETIC_DEMO_FINDING — не production CV KPI
    target = items[0]
    evid = k1_frame_ids[:4] or frame_ids[:1]
    db.add(
        Deviation(
            project_id=project.id,
            schedule_item_id=target.id,
            schedule_version_id=version.id,
            code="LOW_ACTIVITY",
            risk_score=0.7,
            heuristic_score=0.7,
            status="OPEN",
            lifecycle="OPEN",
            details_json=json.dumps(
                {
                    "message": "Синтетический учебный кейс К1: техника на кадрах, активность ниже ожидаемой.",
                    "signal_kind": "SYNTHETIC_DEMO_FINDING",
                    "data_origin": "SYNTHETIC_TEST_FIXTURE",
                    "preserve_fixture": True,
                    "camera_visual_zone_id": "K1",
                    "building": "Зона К1",
                    "limitations": [
                        "Кадры синтетические (не фото Строгино и не реального объекта)",
                        "Не юридический факт простоя",
                        "Не учитывать в рабочих показателях по камерам",
                    ],
                    "evidence_frame_ids": evid,
                    "suggested_check": "Сверить зону К1 с планом земляных работ (учебно)",
                },
                ensure_ascii=False,
            ),
            evidence_ids_json=json.dumps(evid),
            event_key=f"fixture:cvlab:SYNTHETIC_DEMO_FINDING:{target.id}",
        )
    )
    return version


def _seed_camera_unbound(db, project: Project) -> None:
    """Камеры Строгино: live без verified binding + PHOTO_ARCHIVE (без temporal claims)."""
    cam = Camera(
        project_id=project.id,
        name="Камера 01 · Строгино 360",
        building_hint=None,
        enabled=True,
    )
    db.add(cam)
    db.flush()
    zone = CameraVisualZone(
        project_id=project.id,
        camera_id=cam.id,
        name="Зона предложена (не подтверждена)",
        zone_key="Z1",
        polygon_norm_json="[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]",
        status="active",
        zone_status="PROPOSED",
    )
    db.add(zone)
    # No CameraZoneBinding until human verifies корпус (building column is NOT NULL)

    archive = Camera(
        project_id=project.id,
        name="Фотоархив · котлован (без live)",
        building_hint=None,
        enabled=True,
        expected_interval_sec=1800,
    )
    db.add(archive)
    db.flush()
    db.add(
        CameraVisualZone(
            project_id=project.id,
            camera_id=archive.id,
            name="Архивная зона (не live)",
            zone_key="ARCHIVE",
            polygon_norm_json="[[0.05,0.05],[0.95,0.05],[0.95,0.95],[0.05,0.95]]",
            status="active",
            zone_status="PROPOSED",
        )
    )


def _seed_strogino_product_cv(db, project: Project, version: ScheduleVersion, by_name: dict[str, ProjectObject]) -> None:
    """Строгино: VERIFIED зоны + реальные демо-кадры (из demo/stills или data/frames)."""
    from app.db.models import ModelVersion
    import hashlib
    import shutil

    b1 = "Корпус 1.1.1"
    b2 = "Корпус 1.1.2"
    if b1 not in by_name:
        b1 = next(iter(by_name.keys()), "Корпус 1")
    if b2 not in by_name:
        b2 = b1

    cam = Camera(
        project_id=project.id,
        name="Камера 02 · обзор корпусов",
        building_hint=b1,
        enabled=True,
        expected_interval_sec=300,
    )
    db.add(cam)
    db.flush()
    z1 = CameraVisualZone(
        project_id=project.id,
        camera_id=cam.id,
        name=f"Зона {b1}",
        zone_key="K11",
        polygon_norm_json="[[0.0,0.0],[0.5,0.0],[0.5,1.0],[0.0,1.0]]",
        status="active",
        zone_status="VERIFIED",
        geometry_source="manual",
    )
    z2 = CameraVisualZone(
        project_id=project.id,
        camera_id=cam.id,
        name=f"Зона {b2}",
        zone_key="K12",
        polygon_norm_json="[[0.5,0.0],[1.0,0.0],[1.0,1.0],[0.5,1.0]]",
        status="active",
        zone_status="VERIFIED",
        geometry_source="manual",
    )
    db.add(z1)
    db.add(z2)
    db.flush()
    db.add(
        CameraZoneBinding(
            project_id=project.id,
            camera_id=cam.id,
            visual_zone_key="K11",
            visual_zone_id=z1.id,
            building=b1,
            binding_status="VERIFIED",
            binding_source="human_verified",
        )
    )
    db.add(
        CameraZoneBinding(
            project_id=project.id,
            camera_id=cam.id,
            visual_zone_key="K12",
            visual_zone_id=z2.id,
            building=b2,
            binding_status="VERIFIED",
            binding_source="human_verified",
        )
    )

    mv = db.query(ModelVersion).order_by(ModelVersion.id.desc()).first()
    if mv is None:
        mv = ModelVersion(name="yolo-demo", weights_path="models/yolo11s_combined_v1_best.pt", weights_sha256="0" * 64)
        db.add(mv)
        db.flush()

    sources = sorted((ROOT / "demo" / "stills").glob("*.png"))
    if not sources:
        sources = sorted((ROOT / "data" / "frames" / "project_2").rglob("*.png"))[:8]
    if not sources:
        # запасной контур: генерируем PNG, если медиа ещё не скопированы
        frames_dir = ROOT / "data" / "uploads" / f"project_{project.id}" / "strogino_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for i in range(6):
            p = frames_dir / f"demo_{i:02d}.png"
            _write_scene_png(p, w=640, h=480, bg=(70, 90, 110))
            sources.append(p)

    frames_dir = ROOT / "data" / "frames" / f"project_{project.id}" / f"camera_{cam.id}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    t0 = datetime(2026, 9, 17, 9, 30, 0)
    frame_ids: list[int] = []
    z1_ids: list[int] = []
    for i, src in enumerate(sources[:8]):
        content = src.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        dest = frames_dir / f"{digest[:16]}.png"
        if not dest.exists():
            shutil.copy2(src, dest)
        rel = f"frames/project_{project.id}/camera_{cam.id}/{dest.name}"
        zone = z1 if i % 2 == 0 else z2
        fr = Frame(
            project_id=project.id,
            camera_id=cam.id,
            captured_at=t0 + timedelta(minutes=15 * i),
            file_path=rel,
            sha256=digest,
            ingest_status="READY",
            image_quality="OK",
            quality_json=json.dumps({"sequence_index": i, "data_origin": "PRODUCT_DEMO"}),
        )
        db.add(fr)
        db.flush()
        frame_ids.append(fr.id)
        if zone.id == z1.id:
            z1_ids.append(fr.id)
        run = InferenceRun(
            frame_id=fr.id,
            model_version_id=mv.id,
            schedule_version_id=version.id,
            kb_version="kb_v2",
            engine_version="product-demo",
            config_hash="strogino-demo",
            status="COMPLETED",
            finished_at=t0 + timedelta(minutes=15 * i),
        )
        db.add(run)
        db.flush()
        eq = "excavator" if i % 3 else "dump_truck"
        db.add(
            Detection(
                inference_run_id=run.id,
                equipment_code=eq,
                raw_class_name=eq,
                confidence=0.86 + (i % 5) * 0.02,
                bbox_norm_json=json.dumps({"x1": 0.1, "y1": 0.2, "x2": 0.45, "y2": 0.7}),
                zone_id=zone.id,
                zone_ambiguous=False,
            )
        )
        db.add(
            Observation(
                inference_run_id=run.id,
                visual_zone_id=zone.id,
                equipment_vector_json=json.dumps({eq: 0.9}),
                quality_json=json.dumps({"zones": {zone.zone_key: {eq: 0.9}}}),
                observability=1.0,
            )
        )

    items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_version_id == version.id, ScheduleItem.is_summary.is_(False))
        .order_by(ScheduleItem.sort_order.asc())
        .all()
    )
    target = next((it for it in items if (it.building or "") == b1 and "котлован" in (it.raw_name or "").lower()), None)
    if target is None:
        target = next((it for it in items if (it.building or "") == b1), None) or (items[0] if items else None)
    if target is None:
        return
    evid = z1_ids[:4] or frame_ids[:3]
    db.add(
        Deviation(
            project_id=project.id,
            schedule_item_id=target.id,
            schedule_version_id=version.id,
            code="REQUIRED_EQUIPMENT_GAP",
            risk_score=0.78,
            heuristic_score=0.78,
            status="OPEN",
            lifecycle="OPEN",
            details_json=json.dumps(
                {
                    "message": f"На кадрах зоны «{b1}» не подтверждён полный состав техники для работы «{target.raw_name}».",
                    "signal_kind": "CV_FINDING",
                    "data_origin": "PRODUCT_DEMO",
                    "demo_primary": True,
                    "camera_visual_zone_id": "K11",
                    "building": b1,
                    "what_seen": ["excavator"],
                    "expected": ["excavator", "dump_truck"],
                    "limitations": [
                        "Отсутствие на кадре не доказывает отсутствие техники на всей площадке",
                    ],
                    "evidence_frame_ids": evid,
                    "suggested_check": f"Сверить зону {b1} с планом земляных работ и составом техники",
                },
                ensure_ascii=False,
            ),
            evidence_ids_json=json.dumps(evid),
            event_key=f"fixture:strogino:REQUIRED_EQUIPMENT_GAP:{target.id}",
        )
    )

def _apply_persona_progress(db, version: ScheduleVersion, persona: str) -> None:
    """Развести прогресс работ, чтобы health давал разные статусы портфеля."""
    from app.services.product.demo_clock import demo_as_of_iso

    as_of = demo_as_of_iso()[:10]
    items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_version_id == version.id, ScheduleItem.is_summary.is_(False))
        .order_by(ScheduleItem.sort_order.asc())
        .all()
    )
    for i, it in enumerate(items):
        plan = float(it.planned_progress or 0)
        end = it.planned_finish.date().isoformat() if it.planned_finish else None
        overdue = bool(end and end < as_of)
        if persona == "on_track":
            # Закрытые / просроченные по плану — факт 100%, иначе почти план
            if plan >= 100 or overdue:
                it.actual_progress = 100.0
            elif plan > 0:
                it.actual_progress = plan
            else:
                it.actual_progress = 0.0
        elif persona == "at_risk":
            if plan >= 100 or overdue:
                # Полностью закрываем просроченные — иначе lag по календарю ≥14 → DELAYED
                it.actual_progress = 100.0
            elif plan > 0:
                it.actual_progress = max(0.0, plan - (12 if i % 2 == 0 else 8))
            else:
                it.actual_progress = 0.0
        elif persona == "delayed":
            if plan >= 100 or overdue:
                it.actual_progress = 55.0 if i % 2 == 0 else 70.0
            elif plan > 0:
                it.actual_progress = max(0.0, plan - (38 if i % 3 == 0 else 25))
            else:
                it.actual_progress = 0.0


def _seed_schedule_editorial_lags(db, project: Project, version: ScheduleVersion, *, n: int = 3) -> None:
    """Editorial-риски КСГ (signal_kind=SCHEDULE_EDITORIAL), data_origin=PRODUCT_DEMO."""
    items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_version_id == version.id, ScheduleItem.is_summary.is_(False))
        .order_by(ScheduleItem.sort_order.asc())
        .all()
    )
    targets = [it for it in items if (it.actual_progress or 0) + 10 < (it.planned_progress or 0)][:n]
    if not targets:
        targets = items[6 : 6 + n]
    for it in targets:
        db.add(
            Deviation(
                project_id=project.id,
                schedule_item_id=it.id,
                schedule_version_id=version.id,
                code="SCHEDULE_LAG",
                risk_score=0.55,
                heuristic_score=0.55,
                status="OPEN",
                lifecycle="OPEN",
                details_json=json.dumps(
                    {
                        "message": f"Отставание по срокам графика: «{it.raw_name}».",
                        "note": "Оценка по плану и факту графика",
                        "hypothesis": f"Прогноз или факт по работе «{it.raw_name}» отстаёт от плана.",
                        "limitations": ["Оценка по полям графика, без подтверждения камерами"],
                        "signal_kind": "SCHEDULE_EDITORIAL",
                        "data_origin": "PRODUCT_DEMO",
                    },
                    ensure_ascii=False,
                ),
                evidence_ids_json="[]",
            )
        )


# Персоны портфеля → разные статусы health (ON_TRACK / AT_RISK / DELAYED / NO_DATA)
PROJECT_PERSONA = {
    "parkline": "on_track",
    "strogino": "at_risk",
    "amursky": "on_track",
    "teatralny": "at_risk",
    "nevsky": "on_track",
    "pravda": "at_risk",
    "plekhanova": "delayed",
    "cvlab": "lab",
}


def main(argv: list[str] | None = None) -> None:
    import argparse

    from seed_guard import (
        DEFAULT_DEMO_DB,
        add_seed_cli_args,
        apply_db_path,
        require_destructive_reset,
    )

    parser = argparse.ArgumentParser(description="Seed PlanSight(3) demo portfolio (V5-safe)")
    add_seed_cli_args(parser, default_db=DEFAULT_DEMO_DB)
    args = parser.parse_args(argv)

    db_path = apply_db_path(Path(args.db_path))
    require_destructive_reset(
        db_path=db_path,
        allow=bool(args.allow_destructive_demo_reset),
        script="seed_plansight3_portfolio.py",
    )

    init_db()
    ensure_schema_patches()
    db = SessionLocal()
    try:
        wiped = _wipe_all_projects(db)
        print("WIPED", wiped, "db=", db_path)
        created = []
        for slug, name, developer, region, address, status, image, commissioning, metro, metro_walk in PROJECT_DEFS:
            persona = PROJECT_PERSONA.get(slug, "at_risk")
            if persona == "lab":
                # CV Lab сидим, cleanup_release_db_v74 удалит его из shipped DB
                pass
            lat, lng = COORDS[slug]
            settings = {
                "slug": slug,
                "developer": {"id": f"dev-{slug}", "name": developer, "groupId": PROJECT_GROUP[slug]},
                "companyGroupId": PROJECT_GROUP[slug],
                "companyGroup": GROUP_NAMES.get(PROJECT_GROUP[slug]),
                "region": region,
                "address": address,
                "status": status,
                "imageUrl": image,
                "commissioning": commissioning,
                "metro": metro,
                "metroWalk": metro_walk,
                "lat": lat,
                "lng": lng,
                "change": CHANGE.get(slug, 0),
                "last_analysis": ANALYSIS[slug],
                "lastAnalysisDate": "2026-09-" + ANALYSIS[slug][0:2],
                "is_demo": True,
                "data_origin": "SYNTHETIC_TEST_FIXTURE" if slug == "cvlab" else "PRODUCT_DEMO",
                "source_graph": "SYNTHETIC_TEST_FIXTURE" if slug == "cvlab" else "PRODUCT_DEMO",
                "source_time": "PRODUCT_DEMO",
                "status_source": "SEED_SETTINGS",
                "progress_source": "UNWEIGHTED_AVG_DEMO",
                "kpi_kind": "DEMO",
                "as_of": "2026-09-17",
                "badge_schedule": None if slug != "cvlab" else "CV Lab",
                "badge_photos": None,
                "persona": persona,
            }
            try:
                d, m, y = ANALYSIS[slug].split()[0].split(".")
                settings["lastAnalysisDate"] = f"{y}-{m}-{d}"
            except Exception:
                settings["lastAnalysisDate"] = "2026-09-17"

            p = Project(name=name, timezone="Europe/Moscow", settings_json=json.dumps(settings, ensure_ascii=False))
            db.add(p)
            db.flush()
            by_name = _create_objects(db, p.id, slug)
            buildings = list(by_name.keys()) or _leaf_buildings(slug)
            version = None

            if slug == "cvlab":
                version = _seed_cv_lab(db, p, by_name)
            elif slug == "strogino" and STROGINO_JSON.exists():
                version = _create_strogino_schedule(db, p, buildings)
                _apply_persona_progress(db, version, "at_risk")
                _seed_camera_unbound(db, p)
                _seed_strogino_product_cv(db, p, version, by_name)
                _seed_schedule_editorial_lags(db, p, version, n=1)
            else:
                version = _create_demo_schedule(db, p, slug, buildings)
                _apply_persona_progress(db, version, persona if persona in ("on_track", "at_risk", "delayed") else "at_risk")
                if persona in ("at_risk", "delayed"):
                    _seed_schedule_editorial_lags(db, p, version, n=3 if persona == "delayed" else 2)

            if version is not None:
                resolve_schedule_item_objects(db, p.id, version.id)
            created.append((p.id, slug, name, version.id if version else None))
        db.commit()
        print("SEEDED", created)
        print("portfolio count", db.query(Project).count())
    finally:
        db.close()


if __name__ == "__main__":
    main()
