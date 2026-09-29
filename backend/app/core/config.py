from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.paths import BACKEND_ROOT, REPO_ROOT


def _resolve(path: str | Path, *, prefer_existing: bool = False) -> Path:
    """Детерминированно: относительные пути от BACKEND_ROOT (../data → репозиторий).

    Не выбираем путь по существованию файла — иначе новая SQLite уезжает за пределы репо.
    """
    p = Path(path)
    if p.is_absolute():
        return p
    backend_cand = (BACKEND_ROOT / p).resolve()
    if prefer_existing:
        if backend_cand.exists():
            return backend_cand
        repo_cand = (REPO_ROOT / p).resolve()
        if repo_cand.exists():
            return repo_cand
    return backend_cand


class Settings:
    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    def raw(self) -> dict[str, Any]:
        return self._raw

    def section(self, name: str) -> dict[str, Any]:
        value = self._raw.get(name) or {}
        if not isinstance(value, dict):
            raise KeyError(f"config section '{name}' must be a mapping")
        return value

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.section(section).get(key, default)

    def require(self, section: str, key: str) -> Any:
        if key not in self.section(section):
            raise KeyError(f"missing config {section}.{key}")
        return self.section(section)[key]

    def path(self, section: str, key: str) -> Path:
        return _resolve(str(self.require(section, key)))

    def data_dir(self) -> Path:
        return _resolve(str(self.require("storage", "data_dir")))

    def frames_dir(self) -> Path:
        return _resolve(str(self.require("storage", "frames_dir")))

    def overlays_dir(self) -> Path:
        return _resolve(str(self.require("storage", "overlays_dir")))

    def uploads_dir(self) -> Path:
        return _resolve(str(self.require("storage", "uploads_dir")))

    def database_path(self) -> Path:
        env = os.environ.get("PLANSIGHT_DATABASE_PATH")
        if env:
            return Path(env).expanduser().resolve()
        return _resolve(str(self.require("storage", "database_path")))

    def model_path(self) -> Path:
        primary = _resolve(str(self.require("detector", "model")), prefer_existing=True)
        if primary.exists():
            return primary
        fallback = self.get("detector", "model_fallback")
        if fallback:
            fb = Path(str(fallback))
            if fb.exists():
                return fb
        raise FileNotFoundError(
            f"CV weights not found at {primary}"
            + (f" or fallback {fallback}" if fallback else "")
        )

    def kb_path(self) -> Path:
        return _resolve(str(self.require("knowledge_base", "path")), prefer_existing=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    path = BACKEND_ROOT / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings = Settings(raw)
    for d in (
        settings.data_dir(),
        settings.frames_dir(),
        settings.overlays_dir(),
        settings.uploads_dir(),
        settings.database_path().parent,
    ):
        d.mkdir(parents=True, exist_ok=True)
    return settings


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
