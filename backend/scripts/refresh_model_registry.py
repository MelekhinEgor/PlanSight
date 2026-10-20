"""Обновление YOLO registry: FIXTURE_SELF_CHECK, ap50=null, опциональный sha256 весов."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "models" / "registry"
WEIGHTS = ROOT / "models" / "yolo11s_combined_v1_best.pt"


def main() -> None:
    # Повтор class-presence check на fixture (YOLO не вызываем)
    from scripts.eval_yolo_fixture import main as eval_main

    try:
        eval_main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print("eval warning:", exc)

    eval_path = REG / "yolo11s_combined_v1_eval.json"
    if eval_path.exists():
        data = json.loads(eval_path.read_text(encoding="utf-8"))
        for _c, row in (data.get("per_class") or {}).items():
            row["ap50"] = None
            row["ap50_95"] = None
            row["fixture_class_match"] = row.get("precision")
            row["note"] = "Not YOLO AP50 — fixture class presence vs cached Detection rows"
        data["status"] = "FIXTURE_SELF_CHECK"
        data["publishable_as_yolo_metrics"] = False
        data["note"] = "Fixture self-check only. Do not publish as YOLO Precision/Recall/AP50."
        # Latency здесь — SQL lookup, не wall-clock детектора
        if "latency_ms" in data:
            data["latency_ms"]["note"] = "SQL Detection lookup — not YOLO inference ms"
        eval_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    man_path = REG / "yolo11s_combined_v1.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    sha = None
    if WEIGHTS.exists():
        h = hashlib.sha256()
        with WEIGHTS.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        sha = h.hexdigest()
    man["weights_sha256"] = sha
    man["weights_path"] = "models/yolo11s_combined_v1_best.pt"
    man["eval"] = {
        "status": "FIXTURE_SELF_CHECK",
        "artifact": "models/registry/yolo11s_combined_v1_eval.json",
        "publishable_as_yolo_metrics": False,
        "note": "Not YOLO metrics — fixture self-check; ap50 forced null",
    }
    if eval_path.exists():
        ev = json.loads(eval_path.read_text(encoding="utf-8"))
        man["eval"]["per_class"] = {
            k: {kk: vv for kk, vv in v.items() if kk != "note"} for k, v in (ev.get("per_class") or {}).items()
        }
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")

    from app.services.activity.activity_net import ensure_registry_stub

    ensure_registry_stub()
    print("PASS registry_refresh", "sha256", (sha or "")[:16])


if __name__ == "__main__":
    main()
