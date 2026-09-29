# Модель данных

## Структура объекта

- **Organization** — застройщик / группа
- **Project** — строительный объект (`settings_json`: адрес, регион, обложка, флаги демо)
- **ProjectObject** — дерево корпусов / захваток (`parent_id`, координаты)

## Календарный график

- **ScheduleVersion** — IMPORTED | WORKING | PUBLISHED
- **ScheduleItem** — работа; editorial-прогресс и даты (не CV-%)
- **ScheduleDependency** — FS / SS / FF / SF + лаг
- Логический ключ работы — `external_id` / canonical work code + статус mapping

## Наблюдения vs факты

| Сущность | Смысл |
|----------|--------|
| ReportedActual / поля ScheduleItem | Внешне подтверждённый факт графика |
| Detection / ActivityHypothesis / VisualObservation | Признаки с камер; **не** % выполнения |
| Deviation (finding) | Проверяемый сигнал для эксперта |
| Evidence / Frame / InferenceRun | Кадры и прогоны детекции |
| EvidenceComment | Комментарии по activity / finding |

## Камеры и зоны

Camera → CameraVisualZone → CameraZoneBinding (`PROPOSED` / `VERIFIED`).

## База знаний

- **KbCatalogItem** — типы работ и техника
- **WorkEquipmentProfile** — required / expected / optional + min_qty

## Демо-данные

Продуктовый seed: `backend/scripts/seed_plansight3_portfolio.py` (и post-seed скрипты сценария Строгино). Не смешивать с `VITE_DEMO_MODE` в браузере.
