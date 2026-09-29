#!/usr/bin/env python3
"""Оценка YOLO-адаптера на golden CV set (V7.3 §5.3).

Запуск:
  PYTHONPATH=. python scripts/eval_yolo_golden.py
  PYTHONPATH=. python scripts/eval_yolo_golden.py --imgsz 640,960,1280
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "cv_golden"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imgsz", default="", help="comma list, e.g. 640,960,1280")
    args = parser.parse_args()
    manifest_path = GOLDEN / "manifest.json"
    if not manifest_path.is_file():
        print("FAIL: missing", manifest_path)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images = manifest.get("images") or {}
    real = {k: v for k, v in images.items() if (GOLDEN / k).is_file()}
    if not real:
        print("WARN: no golden image files present — schema OK, skipping inference")
        print("PASS_SCHEMA")
        return 0

    from app.core.config import get_settings
    from app.services.cv_adapter.service import YoloAdapter

    sizes = [int(x) for x in args.imgsz.split(",") if x.strip()] or [int(get_settings().section("detector").get("imgsz") or 960)]
    for imgsz in sizes:
        print(f"\n=== imgsz={imgsz} ===")
        adapter = YoloAdapter()
        adapter.imgsz = imgsz
        latencies: list[float] = []
        per_class = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        misses: list[str] = []
        for name, meta in real.items():
            expected = {str(k): int(v) for k, v in (meta.get("expected") or {}).items()}
            img = cv2.imread(str(GOLDEN / name))
            t0 = time.perf_counter()
            dets = adapter.infer(img)
            latencies.append((time.perf_counter() - t0) * 1000)
            got: dict[str, int] = defaultdict(int)
            for d in dets:
                got[d.class_name] += 1
            for cls, n_exp in expected.items():
                n_got = got.get(cls, 0)
                per_class[cls]["tp"] += min(n_exp, n_got)
                if n_got < n_exp:
                    per_class[cls]["fn"] += n_exp - n_got
                    misses.append(f"{name}: missing {cls} expected={n_exp} got={n_got}")
                if n_got > n_exp:
                    per_class[cls]["fp"] += n_got - n_exp
            for cls, n_got in got.items():
                if cls not in expected:
                    per_class[cls]["fp"] += n_got
        print("latency_ms median", round(statistics.median(latencies), 1), "p95", round(sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)], 1))
        for cls, s in sorted(per_class.items()):
            prec = s["tp"] / (s["tp"] + s["fp"]) if (s["tp"] + s["fp"]) else 0
            rec = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) else 0
            print(f"  {cls}: P={prec:.2f} R={rec:.2f} tp={s['tp']} fp={s['fp']} fn={s['fn']}")
        if misses:
            print("misses:")
            for m in misses[:20]:
                print(" ", m)
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
