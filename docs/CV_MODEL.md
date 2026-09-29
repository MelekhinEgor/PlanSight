# Модель компьютерного зрения

## Веса

| Поле | Значение |
|------|----------|
| Файл | `models/yolo11s_combined_v1_best.pt` |
| Конфиг | `detector.model` (+ `model_fallback`) в `backend/config.yaml` |
| SHA256 | `f2f736aadb5878b93806380cd11ea1f1074513176e2cd8440fd41b5be0a1882f` |
| Архитектура | YOLO11s (Ultralytics) |
| `imgsz` | 1280 |
| `max_det` | 150 |

## Классы техники / сцены

`bulldozer`, `cleaning_equipment`, `concrete_mixer`, `crane_manipulator`, `dump_truck`, `excavator`, `forklift`, `gazelle`, `grader`, `machinery`, `mobile_crane`, `person`, `road_roller`, `tanker`, `telehandler`, `trailer`, `vehicle`, `wheel_loader`

PPE / safety (не драйверы типа работ): `hard_hat`, `mask`, `no_hard_hat`, `no_mask`, `no_safety_vest`, `safety_cone`, `safety_vest`

## Канонический class map

См. `detector.class_map` в `backend/config.yaml`. Пример: generic `truck` / `trailer` / `gazelle` → `truck_unknown` (без тихого апгрейда до `dump_truck`).

Пороги confidence — `detector.class_confidence`.

## Ограничения модели

- Отдельного класса башенного крана в текущих весах нет; сильнее `mobile_crane` / `crane_manipulator`.
- Мелкая / дальняя техника: предпочтителен `imgsz` 1280.
- Отсутствие детекции ≠ отсутствие техники на площадке.

## Оценка на golden-наборе

```bash
cd backend
PYTHONPATH=. python scripts/eval_yolo_golden.py --imgsz 640,960,1280
```
