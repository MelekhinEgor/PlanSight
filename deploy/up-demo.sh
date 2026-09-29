#!/usr/bin/env bash
# Запуск демо-стенда на сервере (из корня репозитория).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f models/yolo11s_combined_v1_best.pt ]]; then
  echo "Нет models/yolo11s_combined_v1_best.pt — положите веса YOLO и повторите."
  exit 1
fi

docker compose -f docker-compose.yml -f compose.product-demo.yml up -d --build
echo "UI:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):5175"
echo "API: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8010/health"
