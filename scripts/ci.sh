#!/usr/bin/env bash
# EB-107 — Chạy CI ngay tại máy local, giống hệt .github/workflows/ci.yml
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== [1/3] Backend tests =="
(cd apps/api && python3 -m pytest tests/ -q)

echo "== [2/3] Frontend build =="
(cd apps/web && npm run build)

echo "== [3/3] Docker Compose config =="
if command -v docker >/dev/null 2>&1; then
  docker compose config -q && echo "compose OK"
else
  python3 -c "import yaml; d=yaml.safe_load(open('docker-compose.yml')); assert len(d['services'])==6; print('compose YAML OK (máy không có Docker, kiểm tra cú pháp thay thế)')"
fi

echo "CI LOCAL: ALL GREEN"
