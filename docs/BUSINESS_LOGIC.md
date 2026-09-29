# Бизнес-логика

## Пайплайн наблюдения

`кадр → YOLO → зона (VERIFIED) → гипотеза работы → matching → finding → вердикт → impact preview`

CV и matching **не** выставляют процент готовности работы. Прогресс и даты КСГ меняет только эксперт (редактирование графика / закрытие работы).

## Сопоставление со строкой КСГ (matching)

1. Корпус с VERIFIED / human_verified привязкой — жёсткий gate: нельзя уехать на другой корпус.
2. Мягкий префикс (`К1` ↔ «Корпус 1…») — только кандидат, не авто-`ACCEPTED`.
3. Статус `ACCEPTED` — только при совместимом типе работы, temporal-окне и локации.

Если matching ≠ `ACCEPTED`, UI не показывает строку КСГ как установленный факт.

## Findings и evidence

| Сигнал | Смысл |
|--------|--------|
| По камерам (`CV_VERIFIED_FINDING`) | Есть VERIFIED-зона и кадры в `evidence_ids` (= Frame.id) |
| По графику (`RISK_FROM_SCHEDULE`) | Календарный риск без обязательных кадров |
| `NEEDS_CAMERA_SETUP` | Нет VERIFIED-зоны — не раздувать coverage gap |
| `REQUIRED_EQUIPMENT_GAP` | Нет обязательной техники по профилю работы |
| `EQUIPMENT_COMPOSITION_ANOMALY` | Нет типичной (не required) техники |

Provenance в `details_json` (hypothesis / match / frame / zone / camera) **неизменяем** после создания. Decision-trace в UI читает сохранённые id, не пересчитывает «ближайшую» гипотезу заново.

Кадры `PHOTO_ARCHIVE` не участвуют в temporal-findings (late / pause / work-after-plan).

## Вердикт и влияние на срок

1. Confirm finding **не** завершает работу в КСГ и не публикует новый график.
2. После подтверждения задержки строится `ScenarioRun` (CPM на рабочей копии). Published-версия не меняется.
3. При неполной сети зависимостей — `PARTIAL_NETWORK_PREVIEW`: прогноз по связанному фрагменту, без claim срока всего проекта.
4. Нет связей / сеть INVALID → `FORECAST_UNAVAILABLE`.

## Закрытие работы по КСГ

| Действие | Меняет | Не меняет |
|----------|--------|-----------|
| Verdict (`confirm`) | lifecycle finding | даты КСГ, статусы работ |
| «Работа завершена» | статус работы, факт прогресса | published план без явной публикации |
| Каскад предшественников | только выбранные pred по рёбрам сети | автозакрытие «логических» предков без рёбер |

API: `GET/POST .../schedule-items/{id}/complete-preview|complete`. Список предшественников оператор подтверждает явно.

## Кадры

- Не в evidence → можно удалить из БД.
- В evidence → `ARCHIVED` (скрыт из ленты, provenance finding сохранён).
- Hard-delete кадров из evidence запрещён.

## Decision-trace (вкладка «Логика»)

1. Источник — камера, кадр, время  
2. Что увидела модель — техника, bbox, confidence  
3. Где — verified-зона / корпус  
4. Что предположено — тип работы  
5. Как сопоставлено — строка КСГ и статус matching  
6. Почему warning — правило + evidence-кадры  
