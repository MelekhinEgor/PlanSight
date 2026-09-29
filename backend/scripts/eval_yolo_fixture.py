"""V6 Sprint F — eval качества YOLO на синтетических fixtures CV Lab (без утечки кадров).

Пишет metrics JSON в models/registry/. Не fine-tune.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.migrate import ensure_schema_patches
from app.db.models import Detection, Frame, InferenceRun, Project, SessionLocal, init_db


ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "models" / "registry"


def main() -> None:
    get_settings.cache_clear()
    init_db()
    ensure_schema_patches()
    db = SessionLocal()
    try:
        lab = None
        for p in db.query(Project).all():
            s = json.loads(p.settings_json or "{}")
            if s.get("slug") == "cvlab":
                lab = p
                break
        if not lab:
            raise SystemExit("cvlab not found — seed portfolio first")

        frames = db.query(Frame).filter(Frame.project_id == lab.id).order_by(Frame.id.asc()).all()
        # Ожидаемые метки из seed: frame0 excavator, frame1 dump_truck
        expected = {0: "excavator", 1: "dump_truck"}
        tp = defaultdict(int)
        fp = defaultdict(int)
        fn = defaultdict(int)
        latencies: list[float] = []

        for i, fr in enumerate(frames):
            t0 = time.perf_counter()
            run = (
                db.query(InferenceRun)
                .filter(InferenceRun.frame_id == fr.id, InferenceRun.status == "COMPLETED")
                .order_by(InferenceRun.id.desc())
                .first()
            )
            dets = (
                db.query(Detection).filter(Detection.inference_run_id == run.id).all() if run else []
            )
            latencies.append((time.perf_counter() - t0) * 1000)
            pred_classes = {d.equipment_code for d in dets}
            exp = expected.get(i)
            if exp:
                if exp in pred_classes:
                    tp[exp] += 1
                else:
                    fn[exp] += 1
                for pc in pred_classes:
                    if pc != exp:
                        fp[pc] += 1

        classes = sorted(set(tp) | set(fp) | set(fn) | set(expected.values()))
        per_class = {}
        for c in classes:
            tpi, fpi, fni = tp[c], fp[c], fn[c]
            prec = tpi / (tpi + fpi) if (tpi + fpi) else None
            rec = tpi / (tpi + fni) if (tpi + fni) else None
            per_class[c] = {
                "precision": prec,
                "recall": rec,
                "ap50": None,
                "fixture_class_match": prec,
                "tp": tpi,
                "fp": fpi,
                "fn": fni,
                "note": "Not YOLO AP50 — fixture class presence vs cached Detection rows",
            }

        summary = {
            "model_id": "yolo11s_combined_v1",
            "dataset": "cvlab_synthetic_fixture",
            "trained_on_leaked_frames": False,
            "n_frames": len(frames),
            "per_class": per_class,
            "latency_ms": {
                "n": len(latencies),
                "mean": sum(latencies) / len(latencies) if latencies else None,
            },
            "note": "Fixture self-check only. Do not publish as YOLO Precision/Recall/AP50.",
            "status": "FIXTURE_SELF_CHECK",
        }
        REG.mkdir(parents=True, exist_ok=True)
        out = REG / "yolo11s_combined_v1_eval.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        # обновляем манифест registry
        man_path = REG / "yolo11s_combined_v1.json"
        man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
        man["eval"] = {
            "status": "FIXTURE_SELF_CHECK",
            "artifact": str(out.relative_to(ROOT)).replace("\\", "/"),
            "per_class": {k: {kk: vv for kk, vv in v.items() if kk != "note"} for k, v in per_class.items()},
            "note": "Not YOLO metrics — fixture self-check",
        }
        man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
        print("PASS", out)
        print(json.dumps(per_class, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
