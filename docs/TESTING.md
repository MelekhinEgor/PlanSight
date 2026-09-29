# Тесты

```powershell
cd backend
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m pytest -q
```

Тесты копируют продуктовую БД во временный файл (`tests/conftest.py`) — рабочая БД не портится.

Проверка демо-целостности:

```powershell
.\.venv\Scripts\python.exe scripts\verify_product_demo.py
```

CV golden (при наличии фикстур):

```powershell
.\.venv\Scripts\python.exe scripts\eval_yolo_golden.py --imgsz 640,960,1280
```
