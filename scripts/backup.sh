#!/usr/bin/env bash
# EB-407 — Sao lưu PostgreSQL của ExamBank (giữ 14 bản gần nhất).
# Gợi ý cron trên server:  30 2 * * *  cd /opt/exambank && bash scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
STAMP="$(date +%Y%m%d-%H%M%S)"
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db \
  pg_dump -U "${POSTGRES_USER:-exambank}" "${POSTGRES_DB:-exambank}" | gzip > "backups/exambank-${STAMP}.sql.gz"
ls -1t backups/exambank-*.sql.gz | tail -n +15 | xargs -r rm -f
echo "Đã sao lưu: backups/exambank-${STAMP}.sql.gz"
