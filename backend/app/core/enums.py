from __future__ import annotations

from enum import Enum


class IngestStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    ERROR = "ERROR"
    NEEDS_TIMESTAMP = "NEEDS_TIMESTAMP"


class FrameQualityStatus(str, Enum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    UNUSABLE = "UNUSABLE"


class ScoreKind(str, Enum):
    UNCALIBRATED_SCORE = "uncalibrated_score"
    MODEL_ESTIMATE = "model_estimate"
    HUMAN_CONFIRMED = "human_confirmed"


class PhysicalState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class UiStatus(str, Enum):
    """Недостаточность интерфейса — не физическое состояние."""

    UNKNOWN = "UNKNOWN"


class EventType(str, Enum):
    LIKELY_START = "LIKELY_START"
    CONTINUE = "CONTINUE"
    POSSIBLE_PAUSE = "POSSIBLE_PAUSE"
    RESUME = "RESUME"
    LIKELY_FINISH = "LIKELY_FINISH"
    UNCONFIRMED = "UNCONFIRMED"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"


class DeviationCode(str, Enum):
    LATE_START_RISK = "LATE_START_RISK"
    EARLY_START = "EARLY_START"
    WORK_AFTER_PLAN = "WORK_AFTER_PLAN"
    POSSIBLE_PAUSE = "POSSIBLE_PAUSE"
    WORK_NOT_CONFIRMED = "WORK_NOT_CONFIRMED"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    UNEXPECTED_ACTIVITY = "UNEXPECTED_ACTIVITY"


class MatchReason(str, Enum):
    COMPATIBLE_TYPE = "COMPATIBLE_TYPE"
    TEMPORAL_OK = "TEMPORAL_OK"
    TEMPORAL_WEAK = "TEMPORAL_WEAK"
    LOCATION_UNKNOWN = "LOCATION_UNKNOWN"
    AMBIGUOUS_LOCATION = "AMBIGUOUS_LOCATION"
    SOFT_LOCATION_CANDIDATE = "SOFT_LOCATION_CANDIDATE"
    UNMATCHED = "UNMATCHED"
    SEQUENCE_OK = "SEQUENCE_OK"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED_IDEMPOTENT = "SKIPPED_IDEMPOTENT"
