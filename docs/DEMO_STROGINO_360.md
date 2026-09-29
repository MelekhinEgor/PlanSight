# Демо-сценарий: ЖК «Строгино 360»

| Слой | Содержание |
|------|------------|
| Объект | ЖК «Строгино 360» |
| КСГ | График работ по корпусам |
| Камеры | Зоны с привязкой к корпусам, кадры наблюдений |
| Риски | Отклонения по камерам и по графику |

## Предзагруженные данные

В репозитории лежит снимок `product_demo/` (SQLite + кадры) — тот же портфель, что в рабочей копии до упаковки.

```bat
cd backend
.venv\Scripts\python.exe scripts\install_product_demo.py --force
set PLANSIGHT_DATABASE_PATH=..\data\plansight.db
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Docker:

```bash
docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
```

На сервер: образ уже содержит `product_demo/`; при первом старте снимок копируется в volume `/data`.  
Либо скопируйте каталог `product_demo/` на хост и выполните `install_product_demo.py` с `PLANSIGHT_DATABASE_PATH`.

Пересборка снимка из локальной `data/` (или из другой копии):

```bat
.venv\Scripts\python.exe scripts\pack_product_demo.py --src-data ..\data --out ..\product_demo
```

## Сценарий 6–8 мин

1. Портфель → карточка Строгино  
2. Дерево → корпус → фильтр графика  
3. Предупреждение на Gantt → карточка с кадрами и вкладкой «Логика»  
4. Камеры: зоны и привязка к корпусу  
5. Подтверждение finding / закрытие работы по КСГ  

Frontend: `cd frontend && npm run dev` → http://127.0.0.1:5175/
