from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class Organization(Base):
    """Застройщик / юрлицо. group_id — группа компаний (PlanSight(3) companyGroupId)."""

    __tablename__ = "organization"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    # Может хранить поля карточки PlanSight(3) и флаг is_demo.
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cameras: Mapped[list[Camera]] = relationship(back_populates="project")


class ProjectObject(Base):
    """Дерево объектов проекта (корпус / захватка / узел)."""

    __tablename__ = "project_object"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("project_object.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), default="building")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class EvidenceComment(Base):
    """Комментарии evidence-панели (activity / deviation thread)."""

    __tablename__ = "evidence_comment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    activity_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    deviation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(128), default="")
    initials: Mapped[str] = mapped_column(String(16), default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="user")  # user|pm|system
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KbCatalogItem(Base):
    """Админ-каталоги: work_types | equipment."""

    __tablename__ = "kb_catalog_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # work_types|equipment
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkEquipmentProfile(Base):
    """Связь вид работ ↔ техника (required|expected|optional + min_qty)."""

    __tablename__ = "work_equipment_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_type_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    equipment_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), default="expected")  # required|expected|optional
    min_qty: Mapped[int] = mapped_column(Integer, default=1)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Camera(Base):
    __tablename__ = "camera"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_interval_sec: Mapped[int] = mapped_column(Integer, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    building_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project: Mapped[Project] = relationship(back_populates="cameras")


class ScheduleVersion(Base):
    __tablename__ = "schedule_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    kind: Mapped[str] = mapped_column(String(32), default="CURRENT")  # BASELINE|CURRENT|SCENARIO
    source_file_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Редакторская ось (V4): независимо от plan_kind
    version_state: Mapped[str] = mapped_column(String(32), default="IMPORTED")  # IMPORTED|WORKING|PUBLISHED|ARCHIVED
    parent_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    wbs_json: Mapped[str] = mapped_column(Text, default="[]")
    source_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Предложения network recovery (JSON или null)
    network_recovery_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScheduleDependency(Base):
    """Связь MSPDI PredecessorLink — только внутри одной schedule_version."""

    __tablename__ = "schedule_dependency"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_version_id: Mapped[int] = mapped_column(ForeignKey("schedule_version.id"), nullable=False, index=True)
    successor_item_id: Mapped[int] = mapped_column(ForeignKey("schedule_item.id"), nullable=False, index=True)
    predecessor_item_id: Mapped[int] = mapped_column(ForeignKey("schedule_item.id"), nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String(16), default="FS")  # FS|SS|FF|SF
    lag_minutes: Mapped[int] = mapped_column(Integer, default=0)
    predecessor_uid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    successor_uid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Источник связи: IMPORTED | EXPERT_APPROVED | INFERRED_UNVERIFIED | UNKNOWN
    link_source: Mapped[str] = mapped_column(String(32), default="UNKNOWN")


class CameraZoneBinding(Base):
    """Ручная привязка камеры/ROI к корпусу (дешёвый binding)."""

    __tablename__ = "camera_zone_binding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), nullable=False, index=True)
    visual_zone_key: Mapped[str] = mapped_column(String(64), default="WHOLE_FRAME")
    visual_zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    building: Mapped[str] = mapped_column(String(64), nullable=False)
    workface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Источник привязки: unknown | proposed | human_verified | imported_verified
    binding_source: Mapped[str] = mapped_column(String(32), default="unknown")
    # Статус привязки: PROPOSED | VERIFIED | REJECTED
    binding_status: Mapped[str] = mapped_column(String(32), default="PROPOSED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(128), default="operator")


class CameraVisualZone(Base):
    """Производственная визуальная зона (ROI) на кадре камеры."""

    __tablename__ = "camera_visual_zone"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)  # «К1-КОТЛОВАН»
    zone_key: Mapped[str] = mapped_column(String(64), nullable=False)  # K1 / K2 / WHOLE_FRAME
    # [[x,y], ...] в нормализованных 0..1 координатах кадра
    polygon_norm_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="active")  # active|draft|archived
    # Способ нарезки зон: manual | auto_activity_cluster | auto_strips
    geometry_source: Mapped[str] = mapped_column(String(32), default="manual")
    # Статус привязки: PROPOSED | VERIFIED | REJECTED (семантическая привязка отдельно от geometry)
    zone_status: Mapped[str] = mapped_column(String(32), default="PROPOSED")
    created_by: Mapped[str] = mapped_column(String(128), default="operator")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)


class WorkType(Base):
    __tablename__ = "work_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("work_type.id"), nullable=True)


class EquipmentType(Base):
    __tablename__ = "equipment_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cv_aliases_json: Mapped[str] = mapped_column(Text, default="[]")


class EquipmentWorkRule(Base):
    __tablename__ = "equipment_work_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kb_version: Mapped[str] = mapped_column(String(64), nullable=False)
    work_type_id: Mapped[int] = mapped_column(ForeignKey("work_type.id"), nullable=False)
    equipment_type_id: Mapped[int] = mapped_column(ForeignKey("equipment_type.id"), nullable=False)
    theta: Mapped[float] = mapped_column(Float, nullable=False)
    necessity: Mapped[str] = mapped_column(String(32), default="possible")
    source: Mapped[str] = mapped_column(String(64), default="expert_seed")


class ScheduleItem(Base):
    __tablename__ = "schedule_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_version_id: Mapped[int] = mapped_column(ForeignKey("schedule_version.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_name: Mapped[str] = mapped_column(String(512), nullable=False)
    work_type_id: Mapped[int | None] = mapped_column(ForeignKey("work_type.id"), nullable=True)
    planned_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    planned_finish: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    building: Mapped[str | None] = mapped_column(String(64), nullable=True)
    building_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    building_normalized: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Источник корпуса: schedule_explicit | wbs_parent | human_verified | unknown
    building_source: Mapped[str] = mapped_column(String(32), default="unknown")
    workface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    floor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observability_mode: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    observability_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    wbs: Mapped[str | None] = mapped_column(String(128), nullable=True)
    normalized_operation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Редакторские поля графика (не CV-скоры)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    planned_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    mapping_status: Mapped[str] = mapped_column(String(32), default="UNMAPPED")
    canonical_work_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_work_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wbs_node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Связь с деревом объектов; soft building остаётся для CV matching
    project_object_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_object.id"), nullable=True, index=True
    )


class ModelVersion(Base):
    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    weights_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    weights_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    class_map_json: Mapped[str] = mapped_column(Text, default="{}")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Frame(Base):
    __tablename__ = "frame"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ingest_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    image_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quality_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InferenceRun(Base):
    __tablename__ = "inference_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("frame.id"), nullable=False, index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"), nullable=False)
    schedule_version_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_version.id"), nullable=True)
    kb_version: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Detection(Base):
    __tablename__ = "detection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inference_run_id: Mapped[int] = mapped_column(ForeignKey("inference_run.id"), nullable=False, index=True)
    equipment_type_id: Mapped[int | None] = mapped_column(ForeignKey("equipment_type.id"), nullable=True)
    equipment_code: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_class_name: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_norm_json: Mapped[str] = mapped_column(Text, nullable=False)
    track_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    zone_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)


class Episode(Base):
    __tablename__ = "episode"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), nullable=False)
    visual_zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    composition_json: Mapped[str] = mapped_column(Text, default="{}")
    frame_count: Mapped[int] = mapped_column(Integer, default=1)


class Observation(Base):
    __tablename__ = "observation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inference_run_id: Mapped[int] = mapped_column(ForeignKey("inference_run.id"), nullable=False, unique=True)
    visual_zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_json: Mapped[str] = mapped_column(Text, default="{}")
    equipment_vector_json: Mapped[str] = mapped_column(Text, default="{}")
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episode.id"), nullable=True)
    observability: Mapped[float] = mapped_column(Float, default=1.0)


class ActivityHypothesis(Base):
    __tablename__ = "activity_hypothesis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inference_run_id: Mapped[int] = mapped_column(ForeignKey("inference_run.id"), nullable=False, index=True)
    work_type_id: Mapped[int] = mapped_column(ForeignKey("work_type.id"), nullable=False)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), nullable=False)
    visual_zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episode.id"), nullable=True)
    interval_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    interval_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    activity_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_kind: Mapped[str] = mapped_column(String(32), default="uncalibrated_score")
    state_distribution_json: Mapped[str] = mapped_column(Text, default="{}")
    ui_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    explanation_json: Mapped[str] = mapped_column(Text, default="{}")


class ScheduleMatch(Base):
    __tablename__ = "schedule_match"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("activity_hypothesis.id"), nullable=False, index=True)
    schedule_item_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_item.id"), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_kind: Mapped[str] = mapped_column(String(32), default="uncalibrated_score")
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    is_unmatched: Mapped[bool] = mapped_column(Boolean, default=False)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("activity_hypothesis.id"), nullable=False, index=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("frame.id"), nullable=False)
    detection_id: Mapped[int | None] = mapped_column(ForeignKey("detection.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class StateEvent(Base):
    __tablename__ = "state_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("activity_hypothesis.id"), nullable=False)
    schedule_item_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_item.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="model_estimate")
    source: Mapped[str] = mapped_column(String(64), default="temporal_filter")
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class Deviation(Base):
    __tablename__ = "deviation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    schedule_item_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_item.id"), nullable=True)
    schedule_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("state_event.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # deprecated alias
    heuristic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")  # legacy
    lifecycle: Mapped[str] = mapped_column(String(32), default="OPEN")  # OPEN|ACKNOWLEDGED|RESOLVED
    event_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EstimateStagingRow(Base):
    """Таблица staging из Raschet_dlitelnosti.xlsx — не источник θ."""

    __tablename__ = "estimate_staging"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file: Mapped[str] = mapped_column(String(512), nullable=False)
    sheet: Mapped[str] = mapped_column(String(128), nullable=False)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    operation: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    equipment_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    equipment_canonical: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[str | None] = mapped_column(String(128), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    machine_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    labor_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_duration: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    detectable_by_cv: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class HumanVerdict(Base):
    __tablename__ = "human_verdict"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    correction_json: Mapped[str] = mapped_column(Text, default="{}")
    user_id: Mapped[str] = mapped_column(String(128), default="operator")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DailySummary(Base):
    __tablename__ = "daily_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    run_version: Mapped[str] = mapped_column(String(64), nullable=False)


class TemporalState(Base):
    """Состояние activity_type_state(camera, visual_zone, work_type) — не смешивать корпуса КСГ."""

    __tablename__ = "temporal_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), nullable=False)
    work_type_id: Mapped[int] = mapped_column(ForeignKey("work_type.id"), nullable=False)
    visual_zone_key: Mapped[str] = mapped_column(String(64), default="WHOLE_FRAME")
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    distribution_json: Mapped[str] = mapped_column(Text, default="{}")
    frame_support: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_dt_sec: Mapped[float] = mapped_column(Float, default=0.0)


class ScheduleItemState(Base):
    """Состояние конкретной строки КСГ (отдельно от TypeState по виду работ)."""

    __tablename__ = "schedule_item_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_version_id: Mapped[int] = mapped_column(ForeignKey("schedule_version.id"), nullable=False, index=True)
    schedule_item_id: Mapped[int] = mapped_column(ForeignKey("schedule_item.id"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    observed_activity: Mapped[float] = mapped_column(Float, default=0.0)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    ui_status: Mapped[str] = mapped_column(String(64), default="UNCONFIRMED")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class ProjectionSnapshot(Base):
    """Атомарный снимок derived-проекции (P0-G)."""

    __tablename__ = "projection_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScenarioRun(Base):
    """Сохранённый what-if (immutable input/result). Publish — отдельное действие."""

    __tablename__ = "scenario_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    scenario_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    source_schedule_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="WHAT_IF_PREVIEW")
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    published: Mapped[bool] = mapped_column(Boolean, default=False)


class JobRun(Base):
    """Долговечная запись job. Дополняет in-memory очередь; переживает restart API."""

    __tablename__ = "job_run"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    mode: Mapped[str] = mapped_column(String(32), default="sync")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    timings_json: Mapped[str] = mapped_column(Text, default="{}")


_ENGINE = None
_SessionLocal = None


def get_engine():
    global _ENGINE, _SessionLocal
    if _ENGINE is None:
        db_path = get_settings().database_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _ENGINE = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        _SessionLocal = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False)
    return _ENGINE


def reset_engine() -> None:
    """Сбросить кэш engine — следующий SessionLocal подхватит PLANSIGHT_DATABASE_PATH."""
    global _ENGINE, _SessionLocal
    if _ENGINE is not None:
        try:
            _ENGINE.dispose()
        except Exception:
            pass
    _ENGINE = None
    _SessionLocal = None


def SessionLocal():
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    from app.db.migrate import ensure_schema_patches

    ensure_schema_patches()
