# Model registry (V6 Sprint F)

Канонические артефакты моделей. Не коммитить большие веса — только манифесты.

Пример манифеста: `yolo11s_combined_v1.json`.

Правила:
- обучение только на разрешённых датасетах (без leaked demo frames);
- в проде указывайте `weights_sha256` и `eval` метрики class-wise;
- threshold calibration — отдельный артефакт `calibration_*.json`.
