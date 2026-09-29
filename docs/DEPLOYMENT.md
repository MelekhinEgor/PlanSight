# Развёртывание

## Что поднимается

| Сервис | Порт (по умолчанию) | Роль |
|--------|---------------------|------|
| `web` | 5175 → 80 | UI (nginx) |
| `api` | 8010 | FastAPI + YOLO |
| volume `plansight_data` | — | SQLite, кадры, uploads |

В образ API входит снимок `product_demo/` (~26 MB). Веса YOLO **не** в образе — файл монтируется с хоста: `./models:/models:ro`.

## Требования

- Docker Engine + Docker Compose v2  
  - **Windows:** Docker Desktop (WSL2 backend)  
  - **Ubuntu:** Docker уже установлен
- ~2 CPU / 2 GB RAM / 10+ GB диск (YOLO ест RAM)
- Файл `models/yolo11s_combined_v1_best.pt` в корне проекта рядом с `docker-compose.yml`

Команда запуска с демо (одна и та же на Windows и Linux):

```bash
docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
```

---

## Windows (Docker Desktop)

Нужны: [Docker Desktop](https://www.docker.com/products/docker-desktop/) запущен, в трее зелёный; PowerShell или Terminal.

### Вариант A — уже есть папка репозитория

```powershell
cd E:\PlanSight

# веса на месте?
Test-Path .\models\yolo11s_combined_v1_best.pt

# снимок демо на месте?
Test-Path .\product_demo\plansight.db

Copy-Item .\deploy\.env.small-vps.example .\.env -Force

docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
```

Первая сборка может занять 5–15 минут. Дальше:

- UI: http://127.0.0.1:5175  
- API: http://127.0.0.1:8010/health  

```powershell
docker compose -f docker-compose.yml -f compose.product-demo.yml ps
docker compose -f docker-compose.yml -f compose.product-demo.yml logs -f api
```

Остановка:

```powershell
docker compose -f docker-compose.yml -f compose.product-demo.yml down
```

### Вариант B — распаковать архив (ZIP / tar)

Если прислали `plansight-ship.zip` или `plansight-ship.tgz`:

```powershell
# ZIP
Expand-Archive -Path .\plansight-ship.zip -DestinationPath .\PlanSight -Force
cd .\PlanSight

# или tar.gz (Windows 10+)
# tar -xzf plansight-ship.tgz
# cd .\PlanSight   # если архив уже с корнем файлов — остаётесь в распакованной папке

# положите веса, если их не было в архиве
New-Item -ItemType Directory -Force -Path .\models | Out-Null
# Copy-Item <путь>\yolo11s_combined_v1_best.pt .\models\

Copy-Item .\deploy\.env.small-vps.example .\.env -Force
docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
```

В архиве должны быть минимум: `backend/`, `frontend/`, `deploy/`, `product_demo/`, `models/` (или веса отдельно), `docker-compose.yml`, `compose.product-demo.yml`.

### Собрать архив для передачи (с этой машины)

Из корня `E:\PlanSight` в PowerShell:

```powershell
tar -czf plansight-ship.tgz `
  --exclude=.venv --exclude=backend/.venv --exclude=node_modules `
  --exclude=frontend/node_modules --exclude=data --exclude=.git `
  backend frontend deploy product_demo models docs `
  docker-compose.yml compose.product-demo.yml README.md .dockerignore .gitignore
```

### Без Docker (dev)

См. [README.md](../README.md) и [DEMO_STROGINO_360.md](DEMO_STROGINO_360.md):

```powershell
cd E:\PlanSight\backend
.\.venv\Scripts\python.exe scripts\install_product_demo.py --force
$env:PLANSIGHT_DATABASE_PATH="E:\PlanSight\data\plansight.db"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

В другом окне: `cd E:\PlanSight\frontend` → `npm ci` → `npm run dev` → http://127.0.0.1:5175

---

## Ubuntu-сервер (Docker уже установлен)

### Вариант A — репозиторий на GitHub

На сервере:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone <URL> ~/PlanSight
cd ~/PlanSight
mkdir -p models
```

С Windows (PowerShell), веса (и при необходимости `product_demo/`):

```powershell
scp E:\PlanSight\models\yolo11s_combined_v1_best.pt user@SERVER_IP:~/PlanSight/models/
scp -r E:\PlanSight\product_demo user@SERVER_IP:~/PlanSight/
```

Запуск:

```bash
cd ~/PlanSight
cp deploy/.env.small-vps.example .env
chmod +x deploy/up-demo.sh
bash deploy/up-demo.sh
```

Или:

```bash
docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
```

### Вариант B — архивом с Windows

На Windows (см. «Собрать архив» выше), затем:

```powershell
scp plansight-ship.tgz user@SERVER_IP:~/
```

На Ubuntu:

```bash
mkdir -p ~/PlanSight && cd ~/PlanSight
tar -xzf ~/plansight-ship.tgz
cp deploy/.env.small-vps.example .env
docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
```

### Порты и проверка (Ubuntu)

```bash
sudo ufw allow 5175/tcp
sudo ufw allow 8010/tcp   # снаружи можно не открывать, если хватает UI
docker compose -f docker-compose.yml -f compose.product-demo.yml ps
curl -s http://127.0.0.1:8010/health
docker compose -f docker-compose.yml -f compose.product-demo.yml logs --tail=80 api
```

В браузере: `http://SERVER_IP:5175`

---

## Пустая БД (без демо)

```bash
docker compose up -d --build
```

## Повторный запуск и сброс демо

`docker compose up` **не** затирает volume: снимок ставится только если `/data/plansight.db` ещё нет.

Сброс:

```bash
docker compose -f docker-compose.yml -f compose.product-demo.yml down
docker volume ls | grep plansight
docker volume rm <имя_volume>    # например plansight_plansight_data
docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
```

На Windows те же команды в PowerShell (Docker Desktop).

## Переменные (.env)

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `PLANSIGHT_AI_MODE` | `template` | без Ollama |
| `PLANSIGHT_WEB_PORT` | `5175` | порт UI на хосте |
| `PLANSIGHT_API_PORT` | `8010` | порт API на хосте |
| `PLANSIGHT_RBAC` | `0` | RBAC выкл |
| `PLANSIGHT_API_TOKEN` | пусто | опциональный токен |

## Reverse proxy (опционально)

Nginx/Caddy на хосте → `http://127.0.0.1:5175`. API уже проксируется из контейнера `web` на `api:8010` по пути `/api/`.
