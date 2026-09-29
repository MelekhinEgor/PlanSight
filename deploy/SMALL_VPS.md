# Режим без ИИ (малый VPS)

Рекомендуемый минимум: **2 CPU / 2 GB RAM / 40 GB диск**. Ollama/Qwen не поднимаем (`PLANSIGHT_AI_MODE=template`).

```bash
cp deploy/.env.small-vps.example .env
# для демо с данными:
bash deploy/up-demo.sh
# или пустая БД:
# docker compose up -d --build
```

Полная инструкция: [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).
