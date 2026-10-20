#!/usr/bin/env bash
# Запуск демо-стенда на сервере (из корня репозитория).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f models/yolo11s_combined_v1_best.pt ]]; then
  echo "Нет models/yolo11s_combined_v1_best.pt — положите веса YOLO и повторите."
  exit 1
fi

docker compose up -d --build
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "UI:  http://${IP}/"
echo "API: http://${IP}/api/health"
