"""Небольшие риски + объяснимые кадры на 7 оригинальных демо-проектах.

- Мягкое отставание по 1–2 работам (портфель → AT_RISK, не DELAYED)
- Синтетические/демо-кадры с bbox, RU-названием техники, conf и подписью
- Finding с каноническими полями explainability (observed_equipment, hypothesis, …)
- Overlay JPEG для /api/frames/{id}/overlay

Запуск::

  cd backend
  $env:PLANSIGHT_DATABASE_PATH="..\\data\\plansight.db"
  .venv/Scripts/python.exe scripts/seed_demo_mild_risks.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.db.migrate import ensure_schema_patches  # noqa: E402
from app.db.models import (  # noqa: E402
    Camera,
    CameraVisualZone,
    CameraZoneBinding,
    Detection,
    Deviation,
    Frame,
    InferenceRun,
    ModelVersion,
    Observation,
    Project,
    ProjectObject,
    ScheduleItem,
)
from app.services.product.demo_clock import demo_as_of_iso  # noqa: E402
from app.services.product.slugs import project_slug  # noqa: E402
from app.services.product.v42_api import settings_of  # noqa: E402
from app.services.schedule.service import get_active_schedule  # noqa: E402

DEMO_SLUGS = (
    "parkline",
    "strogino",
    "amursky",
    "teatralny",
    "nevsky",
    "pravda",
    "plekhanova",
)

# slug → сценарий explainability
SCENARIOS: dict[str, dict] = {
    "strogino": {
        "code": "REQUIRED_EQUIPMENT_GAP",
        "equip": [("excavator", 0.91, (0.12, 0.38, 0.48, 0.82))],
        "observed": ["excavator"],
        "expected": ["excavator", "dump_truck"],
        "missing": ["dump_truck"],
        "caption": "Вижу экскаватор у переднего края котлована; самосвал в зоне не подтверждён.",
        "hypothesis": "Для земляных работ по графику нужен вывоз грунта, а на кадре есть только экскаватор.",
        "check": "Проверьте, есть ли самосвал вне кадра или на соседней захватке.",
        "lag_items": 1,
        "lag_delta": 12,
    },
    "amursky": {
        "code": "UNEXPECTED_EQUIPMENT_IN_ZONE",
        "equip": [("mobile_crane", 0.88, (0.45, 0.15, 0.78, 0.72))],
        "observed": ["mobile_crane"],
        "expected": ["concrete_mixer"],
        "unexpected": ["mobile_crane"],
        "caption": "Вижу автокран у переднего края стройки; для текущего этапа ожидался бетоновоз.",
        "hypothesis": "Кран может относиться к параллельной работе или к соседнему корпусу.",
        "check": "Уточните назначение крана и текущий этап монолитных работ.",
        "lag_items": 1,
        "lag_delta": 11,
    },
    "parkline": {
        "code": "LOW_ACTIVITY",
        "equip": [("loader", 0.84, (0.22, 0.42, 0.55, 0.78))],
        "observed": ["loader"],
        "expected": ["loader", "dump_truck"],
        "caption": "Вижу погрузчик у кромки площадки; активность ниже ожидаемой для окна съёмки.",
        "hypothesis": "Возможна пауза логистики или техника вне основного фронта работ.",
        "check": "Сверьте журнал работ с зоной обзора камеры.",
        "lag_items": 1,
        "lag_delta": 10,
    },
    "teatralny": {
        "code": "UNCONFIRMED_ACTIVITY",
        "equip": [("concrete_pump", 0.86, (0.30, 0.28, 0.68, 0.75))],
        "observed": ["concrete_pump"],
        "expected": ["concrete_pump", "concrete_mixer"],
        "missing": ["concrete_mixer"],
        "caption": "Вижу бетононасос у корпуса; миксер в кадре не подтверждён.",
        "hypothesis": "Подача бетона могла идти с другой стороны площадки, вне обзора.",
        "check": "Проверьте вторую сторону корпуса и график бетонирования.",
        "lag_items": 1,
        "lag_delta": 11,
    },
    "nevsky": {
        "code": "POSSIBLE_PAUSE",
        "equip": [("bulldozer", 0.82, (0.18, 0.48, 0.52, 0.85))],
        "observed": ["bulldozer"],
        "expected": ["bulldozer"],
        "caption": "Вижу бульдозер у края пятна застройки; перемещений грунта почти нет.",
        "hypothesis": "Возможна технологическая пауза или ожидание вывоза.",
        "check": "Уточните, была ли плановая остановка работ.",
        "lag_items": 1,
        "lag_delta": 10,
    },
    "pravda": {
        "code": "REQUIRED_EQUIPMENT_GAP",
        "equip": [("crane_unknown", 0.79, (0.50, 0.10, 0.88, 0.70))],
        "observed": ["crane_unknown"],
        "expected": ["crane_unknown", "truck_unknown"],
        "missing": ["truck_unknown"],
        "caption": "Вижу кран у переднего края стройки; грузовой транспорт рядом не подтверждён.",
        "hypothesis": "Для монтажа по плану обычно нужен подвоз — на кадре его нет.",
        "check": "Проверьте подъезд и соседние ракурсы камеры.",
        "lag_items": 1,
        "lag_delta": 12,
    },
    "plekhanova": {
        "code": "UNEXPECTED_EQUIPMENT_IN_ZONE",
        "equip": [
            ("excavator", 0.87, (0.10, 0.40, 0.42, 0.80)),
            ("dump_truck", 0.83, (0.55, 0.50, 0.90, 0.88)),
        ],
        "observed": ["excavator", "dump_truck"],
        "expected": ["roller"],
        "unexpected": ["excavator", "dump_truck"],
        "caption": "Вижу экскаватор и самосвал у переднего края площадки; для этапа ожидался каток.",
        "hypothesis": "Состав техники больше похож на земляные работы, чем на уплотнение.",
        "check": "Сверьте фактический этап с графиком и зоной камеры.",
        "lag_items": 1,
        "lag_delta": 12,
    },
}

EQ_RU = {
    "excavator": "Экскаватор",
    "dump_truck": "Самосвал",
    "mobile_crane": "Автокран",
    "crane_unknown": "Кран",
    "concrete_mixer": "Автобетоносмеситель",
    "concrete_pump": "Бетононасос",
    "bulldozer": "Бульдозер",
    "loader": "Погрузчик",
    "truck_unknown": "Грузовик",
    "roller": "Каток",
}


def _font(size: int = 18) -> ImageFont.ImageFont:
    for name in (
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
    ):
        p = Path(name)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _render_scene(w: int, h: int, equip: list[tuple[str, float, tuple]], caption: str) -> Image.Image:
    """Синтетический кадр площадки + техника + подпись объяснения."""
    img = Image.new("RGB", (w, h), (92, 108, 122))
    d = ImageDraw.Draw(img)
    # небо / земля
    d.rectangle((0, 0, w, int(h * 0.42)), fill=(168, 188, 205))
    d.rectangle((0, int(h * 0.42), w, h), fill=(120, 108, 88))
    # «корпус»
    d.rectangle((int(w * 0.55), int(h * 0.18), int(w * 0.92), int(h * 0.55)), fill=(190, 196, 202), outline=(70, 78, 86), width=2)
    for i in range(4):
        for j in range(5):
            x0 = int(w * 0.58) + j * int(w * 0.06)
            y0 = int(h * 0.22) + i * int(h * 0.07)
            d.rectangle((x0, y0, x0 + 18, y0 + 14), fill=(90, 130, 160))
    # техника как цветные блоки
    colors = {
        "excavator": (220, 160, 40),
        "dump_truck": (200, 70, 60),
        "mobile_crane": (240, 200, 50),
        "crane_unknown": (235, 190, 45),
        "concrete_pump": (80, 140, 200),
        "concrete_mixer": (70, 120, 180),
        "bulldozer": (210, 150, 50),
        "loader": (180, 140, 60),
        "truck_unknown": (160, 80, 70),
        "roller": (100, 100, 110),
    }
    for code, _conf, box in equip:
        x1, y1, x2, y2 = [int(v * dim) for v, dim in zip(box, (w, h, w, h))]
        d.rounded_rectangle((x1, y1, x2, y2), radius=8, fill=colors.get(code, (180, 180, 60)), outline=(30, 30, 30), width=2)
        # «кабина»
        d.rectangle((x1 + 8, y1 + 8, x1 + max(24, (x2 - x1) // 3), y1 + max(24, (y2 - y1) // 3)), fill=(40, 45, 50))
    # нижняя плашка с текстом объяснения
    bar_h = 54
    d.rectangle((0, h - bar_h, w, h), fill=(18, 32, 48))
    d.text((12, h - bar_h + 10), caption, fill=(240, 244, 248), font=_font(16))
    return img


def _draw_overlay(base: Image.Image, equip: list[tuple[str, float, tuple]], caption: str) -> Image.Image:
    img = base.copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    w, h = img.size
    font = _font(17)
    font_s = _font(14)
    for code, conf, box in equip:
        x1, y1, x2, y2 = [int(v * dim) for v, dim in zip(box, (w, h, w, h))]
        d.rectangle((x1, y1, x2, y2), outline=(232, 184, 74), width=3)
        label = f"{EQ_RU.get(code, code)} {conf * 100:.0f}%"
        tw, th = d.textbbox((0, 0), label, font=font_s)[2:]
        ly = max(4, y1 - th - 8)
        d.rectangle((x1, ly, x1 + tw + 10, ly + th + 6), fill=(232, 184, 74))
        d.text((x1 + 5, ly + 2), label, fill=(20, 30, 40), font=font_s)
    # caption поверх
    bar_h = 56
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((0, h - bar_h, w, h), fill=(12, 28, 48, 210))
    od.text((12, h - bar_h + 12), caption, fill=(255, 255, 255, 255), font=font)
    return Image.alpha_composite(img, overlay).convert("RGB")


def _ensure_model(db) -> ModelVersion:
    mv = db.query(ModelVersion).order_by(ModelVersion.id.desc()).first()
    if mv:
        return mv
    mv = ModelVersion(name="yolo-demo", weights_path="models/yolo11s_combined_v1_best.pt", weights_sha256="0" * 64)
    db.add(mv)
    db.flush()
    return mv


def _apply_mild_lag(db, version_id: int, *, n_items: int, delta: float) -> list[ScheduleItem]:
    """Лёгкое отставание только на работах, у которых срок ещё не прошёл (иначе health → DELAYED)."""
    as_of = demo_as_of_iso()[:10]
    items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_version_id == version_id, ScheduleItem.is_summary.is_(False))
        .order_by(ScheduleItem.sort_order.asc())
        .all()
    )
    # просроченные по календарю держим закрытыми — иначе max_dev = дни календаря
    for it in items:
        end = it.planned_finish.date().isoformat() if it.planned_finish else None
        if end and end < as_of:
            it.actual_progress = 100.0
            it.forecast_end = it.planned_finish

    candidates = [
        it
        for it in items
        if 20 <= float(it.planned_progress or 0) <= 90
        and it.planned_finish
        and it.planned_finish.date().isoformat() >= as_of
    ]
    if not candidates:
        candidates = [
            it
            for it in items
            if float(it.planned_progress or 0) > 0
            and it.planned_finish
            and it.planned_finish.date().isoformat() >= as_of
        ]
    targets = candidates[:n_items]
    for it in targets:
        plan = float(it.planned_progress or 0)
        # fact+10 < plan → problem; delta 12 даёт мягкий risk без календарного DELAYED
        it.actual_progress = max(0.0, min(plan - delta, plan - 11))
        it.forecast_end = it.planned_finish + timedelta(days=2)
    return targets


def _seed_project(db, project: Project, scenario: dict) -> dict:
    slug = project_slug(settings_of(project))
    version = get_active_schedule(db, project.id)
    if not version:
        return {"slug": slug, "error": "no_schedule"}

    lag_targets = _apply_mild_lag(
        db, version.id, n_items=int(scenario.get("lag_items") or 1), delta=float(scenario.get("lag_delta") or 11)
    )
    buildings = [
        o.name
        for o in db.query(ProjectObject)
        .filter(ProjectObject.project_id == project.id)
        .order_by(ProjectObject.sort_order.asc())
        .all()
        if (o.object_type or "") != "stage"
    ]
    building = (lag_targets[0].building if lag_targets and lag_targets[0].building else None) or (
        buildings[0] if buildings else "Корпус 1"
    )

    # камера + зона
    cam = (
        db.query(Camera)
        .filter(Camera.project_id == project.id, Camera.name.ilike("%объясним%"))
        .first()
    )
    if cam is None:
        cam = Camera(
            project_id=project.id,
            name="Камера 01 · объяснимый ракурс",
            building_hint=building,
            enabled=True,
            expected_interval_sec=300,
        )
        db.add(cam)
        db.flush()
    zone = (
        db.query(CameraVisualZone)
        .filter(CameraVisualZone.camera_id == cam.id, CameraVisualZone.zone_key == "K11")
        .first()
    )
    if zone is None:
        zone = CameraVisualZone(
            project_id=project.id,
            camera_id=cam.id,
            name=f"Зона {building}",
            zone_key="K11",
            polygon_norm_json="[[0.05,0.15],[0.95,0.15],[0.95,0.92],[0.05,0.92]]",
            status="active",
            zone_status="VERIFIED",
            geometry_source="manual",
        )
        db.add(zone)
        db.flush()
        db.add(
            CameraZoneBinding(
                project_id=project.id,
                camera_id=cam.id,
                visual_zone_key="K11",
                visual_zone_id=zone.id,
                building=building,
                binding_status="VERIFIED",
                binding_source="human_verified",
            )
        )

    # удалить прошлые demo explainable findings этого скрипта
    old = (
        db.query(Deviation)
        .filter(Deviation.project_id == project.id, Deviation.event_key.like(f"fixture:{slug}:explainable:%"))
        .all()
    )
    for d in old:
        db.delete(d)

    equip = scenario["equip"]
    caption = scenario["caption"]
    stills = sorted((REPO / "demo" / "stills").glob("*.png"))
    if stills and slug == "strogino":
        base = Image.open(stills[0]).convert("RGB").resize((960, 640))
    else:
        base = _render_scene(960, 640, equip, caption)

    frames_dir = get_settings().frames_dir() / f"project_{project.id}" / f"camera_{cam.id}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir = get_settings().overlays_dir() / f"project_{project.id}"
    overlays_dir.mkdir(parents=True, exist_ok=True)

    mv = _ensure_model(db)
    t0 = datetime.fromisoformat(demo_as_of_iso()[:10] + "T11:20:00")
    frame_ids: list[int] = []
    for i in range(2):
        # чуть сдвинем технику на 2-м кадре
        shifted = []
        for code, conf, box in equip:
            x1, y1, x2, y2 = box
            dx = 0.03 * i
            shifted.append((code, max(0.75, conf - 0.02 * i), (min(0.9, x1 + dx), y1, min(0.98, x2 + dx), y2)))
        if i == 0 and slug == "strogino" and stills:
            scene = base
        else:
            scene = _render_scene(960, 640, shifted, caption)
        overlay_img = _draw_overlay(scene, shifted, caption)
        import io

        buf = io.BytesIO()
        scene.save(buf, format="JPEG", quality=88)
        content = buf.getvalue()
        digest = hashlib.sha256(content).hexdigest()
        dest = frames_dir / f"{digest[:16]}.jpg"
        dest.write_bytes(content)
        rel = f"frames/project_{project.id}/camera_{cam.id}/{dest.name}"
        fr = Frame(
            project_id=project.id,
            camera_id=cam.id,
            captured_at=t0 + timedelta(minutes=8 * i),
            file_path=rel,
            sha256=digest,
            ingest_status="READY",
            image_quality="OK",
            quality_json=json.dumps(
                {
                    "data_origin": "PRODUCT_DEMO",
                    "explainable_demo": True,
                    "caption_ru": caption,
                },
                ensure_ascii=False,
            ),
        )
        db.add(fr)
        db.flush()
        frame_ids.append(fr.id)
        run = InferenceRun(
            frame_id=fr.id,
            model_version_id=mv.id,
            schedule_version_id=version.id,
            kb_version="kb_v2",
            engine_version="explainable-demo",
            config_hash=f"explain-{slug}",
            status="COMPLETED",
            finished_at=t0 + timedelta(minutes=8 * i),
        )
        db.add(run)
        db.flush()
        eq_vec = {code: conf for code, conf, _ in shifted}
        for code, conf, box in shifted:
            x1, y1, x2, y2 = box
            db.add(
                Detection(
                    inference_run_id=run.id,
                    equipment_code=code,
                    raw_class_name=code,
                    confidence=float(conf),
                    bbox_norm_json=json.dumps({"x1": x1, "y1": y1, "x2": x2, "y2": y2}),
                    zone_id=zone.id,
                    zone_ambiguous=False,
                )
            )
        db.add(
            Observation(
                inference_run_id=run.id,
                visual_zone_id=zone.id,
                equipment_vector_json=json.dumps(eq_vec),
                quality_json=json.dumps({"zones": {"K11": eq_vec}, "caption_ru": caption}, ensure_ascii=False),
                observability=1.0,
            )
        )
        ov_path = overlays_dir / f"frame_{fr.id}_run_{run.id}.jpg"
        overlay_img.save(ov_path, format="JPEG", quality=90)

    target_item = lag_targets[0] if lag_targets else None
    if target_item is None:
        target_item = (
            db.query(ScheduleItem)
            .filter(ScheduleItem.schedule_version_id == version.id, ScheduleItem.is_summary.is_(False))
            .order_by(ScheduleItem.sort_order.asc())
            .first()
        )
    details = {
        "message": caption,
        "hypothesis": scenario["hypothesis"],
        "signal_kind": "CV_VERIFIED_FINDING",
        "data_origin": "PRODUCT_DEMO",
        "demo_primary": True,
        "explainable_demo": True,
        "camera_visual_zone_id": "K11",
        "building": building,
        "observed_equipment": scenario.get("observed") or [],
        "expected_equipment": scenario.get("expected") or [],
        "not_confirmed_equipment": scenario.get("missing") or [],
        "unexpected_equipment": scenario.get("unexpected") or [],
        "limitations": [
            "Отсутствие на кадре не доказывает отсутствие техники на всей площадке",
            "Синтетический демо-кадр для объяснимости решения",
        ],
        "suggested_check": scenario.get("check"),
        "evidence_frame_ids": frame_ids,
        "caption_ru": caption,
    }
    db.add(
        Deviation(
            project_id=project.id,
            schedule_item_id=target_item.id if target_item else None,
            schedule_version_id=version.id,
            code=scenario["code"],
            risk_score=0.62,
            heuristic_score=0.62,
            status="OPEN",
            lifecycle="OPEN",
            details_json=json.dumps(details, ensure_ascii=False),
            evidence_ids_json=json.dumps(frame_ids),
            event_key=f"fixture:{slug}:explainable:{scenario['code']}",
            first_seen=t0,
            last_seen=t0 + timedelta(minutes=8),
        )
    )
    return {"slug": slug, "frames": frame_ids, "lag_items": [t.id for t in lag_targets], "caption": caption}


def main() -> int:
    init_db()
    ensure_schema_patches()
    db = SessionLocal()
    out = []
    try:
        projects = db.query(Project).order_by(Project.id.asc()).all()
        by_slug = {project_slug(settings_of(p)): p for p in projects}
        for slug in DEMO_SLUGS:
            p = by_slug.get(slug)
            if not p:
                out.append({"slug": slug, "error": "missing"})
                continue
            sc = SCENARIOS[slug]
            out.append(_seed_project(db, p, sc))
            print("SEEDED", out[-1], flush=True)
        db.commit()
    finally:
        db.close()
    print("DONE", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
