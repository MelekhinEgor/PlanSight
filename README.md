# PlanSight

Система контроля строительного графика по наблюдениям с камер: кадр → техника → зона → гипотеза работы → строка КСГ → предупреждение → эксперт → preview влияния на срок.

Документация продукта: [docs/README.md](docs/README.md).

## Архитектура

См. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) и [docs/BUSINESS_LOGIC.md](docs/BUSINESS_LOGIC.md).

## Пайплайн

`КСГ + камеры → YOLO → зона → activity → matching → finding → verdict → schedule impact preview`

## Структура репозитория

- `frontend/` — React UI
- `backend/` — FastAPI + engine
- `product_demo/` — предзагруженные БД + кадры для демо
- `data/` — рабочая SQLite и кадры (локально / volume; в git не коммитится)
- `models/` — YOLO weights
- `docs/` — описание продукта и эксплуатация
- `deploy/` — Docker

## Требования

- Python 3.12+, Node 22+
- Windows / Linux / macOS
- Веса YOLO: `models/yolo11s_combined_v1_best.pt` (см. [docs/CV_MODEL.md](docs/CV_MODEL.md))

## Локальный запуск — Windows

```powershell
cd PlanSight\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PLANSIGHT_DATABASE_PATH="..\data\plansight.db"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

В другом терминале:

```powershell
cd PlanSight\frontend
npm ci
npm run dev
```

- UI: http://127.0.0.1:5175
- API: http://127.0.0.1:8010
- health: http://127.0.0.1:8010/health

Frontend ходит в API через proxy Vite. Режим localStorage-демо — только при явном `VITE_DEMO_MODE=true`.

## YOLO weights

Положите файл по пути из `backend/config.yaml` → `detector.model` или задайте `model_fallback`.

## БД

По умолчанию `data/plansight.db`. Тесты используют временную копию и не портят рабочую БД.

Предзагруженное демо — каталог `product_demo/` (БД + кадры). Установка в `data/`:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\install_product_demo.py --force
```

Пересборка снимка из рабочей `data/`: `python scripts/pack_product_demo.py`.  
Демо-сценарий: [docs/DEMO_STROGINO_360.md](docs/DEMO_STROGINO_360.md).

## Тесты

См. [docs/TESTING.md](docs/TESTING.md).

## Docker

Нужны: Docker Engine и файл весов `models/yolo11s_combined_v1_best.pt`.

### Пустая БД

```bash
docker compose up -d --build
```

### Демо с примерами (ставит `product_demo/` в volume, если БД отсутствует)

```bash
docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
```

или на Linux-сервере:

```bash
bash deploy/up-demo.sh
```

- UI: http://localhost:5175
- API: http://localhost:8010

Повторный `docker compose up` не пересоздаёт БД. Подробная выкладка на VPS: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

```bash
cd backend
python scripts/release_preflight.py --with-tests
```

## Переменные окружения

| Var | Meaning |
|-----|---------|
| `PLANSIGHT_DATABASE_PATH` | Путь к SQLite |
| `PLANSIGHT_AI_MODE` | `template` (по умолчанию) / `ollama` |

## Backup / restore

Копируйте `data/plansight.db` и каталоги `data/frames`, `data/uploads`.

## Troubleshooting

- Нет детекций → веса и SHA в [docs/CV_MODEL.md](docs/CV_MODEL.md), `imgsz`, качество кадра
- Impact unavailable → нет / неполная сеть зависимостей КСГ
- Портфель пуст → seed или путь к БД

## Ограничения

См. [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).
