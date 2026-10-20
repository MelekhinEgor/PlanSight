"""Режим AI для малого VPS: по умолчанию только шаблоны (без Ollama / LLM).

Env:
  PLANSIGHT_AI_MODE = off | template | ollama
  - off / template (по умолчанию): не вызывать Ollama, не зондировать localhost:11434
  - ollama: опциональный LLM/VLM, если доступен

Для 2 CPU / 2 GB RAM оставляйте mode=template.
"""

from __future__ import annotations

import os


def ai_mode() -> str:
    raw = (os.environ.get("PLANSIGHT_AI_MODE") or "template").strip().lower()
    if raw in ("off", "disabled", "none", "0", "false", "no"):
        return "template"
    if raw in ("ollama", "llm", "on", "full", "1", "true", "yes"):
        return "ollama"
    return "template"


def llm_enabled() -> bool:
    return ai_mode() == "ollama"


def ai_user_note_ru() -> str:
    if llm_enabled():
        return "Доступен опциональный ИИ-помощник (если Ollama запущена)."
    return (
        "Разбор строится по правилам и кадрам без нейросетевого помощника — "
        "так стабильнее на небольшом сервере."
    )
