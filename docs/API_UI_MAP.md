# Соответствие UI и API

Адаптер: `frontend/src/api/remoteBackend.ts`, гейты в `frontend/src/api/client.ts`.  
По умолчанию UI работает по HTTP; `VITE_DEMO_MODE=true` включает только localStorage-демо.

| Экран / действие | Endpoint |
|------------------|----------|
| Портфель | `GET /api/portfolio?as_of=` |
| Список проектов | `GET /api/projects` |
| Карточка проекта | `GET /api/projects/{id}` |
| Обзор проекта | `GET /api/projects/{id}/overview` |
| Дерево объектов | `GET/POST/PATCH/DELETE /api/projects/{id}/objects[/{oid}]` |
| Рабочее пространство КСГ | `GET /api/projects/{id}/schedules/workspace` |
| Версии графика | `GET /api/projects/{id}/schedules/versions` |
| Working copy | `POST .../schedules/{vid}/fork` |
| Правки + пересчёт | `PATCH .../schedules/{vid}` |
| Публикация | `POST .../schedules/{vid}/publish` |
| Экспорт | `GET .../schedules/export?format=` |
| Импорт | `POST /api/projects/{id}/schedule` |
| Восстановление сети | `PATCH .../schedules/{vid}` (+ network_recovery) |
| Камеры / зоны | проект → cameras; `.../cameras/{cid}/zones` |
| Кадры | `GET /api/projects/{id}/frames` |
| Отклонения | `GET /api/projects/{id}/deviations` |
| Evidence / комментарии | `.../activities/{aid}/evidence-thread` |
| Evidence finding | `GET .../deviations/{id}/evidence` |
| Decision-trace | `GET .../deviations/{id}/decision-trace` |
| Закрытие работы | `GET/POST .../schedule-items/{id}/complete[-preview]` |
| Каталоги админки | `GET/PUT /api/admin/catalogs/{key}` |
| Профили работ | `GET/PUT /api/admin/work-profiles` |
| Health | `GET /health` или `GET /api/health` |

Скриншоты UI: [acceptance_screens/](acceptance_screens/).
