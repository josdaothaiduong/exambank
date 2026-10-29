#!/usr/bin/env bash
# EB-407 — Deploy/ cập nhật ExamBank trên VPS (Đường A: Docker + Caddy HTTPS).
# Chạy TẠI server, trong thư mục repo:  bash scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/4 Kéo code mới nhất =="
git pull --ff-only || echo "(bỏ qua git pull — chạy lần đầu hoặc repo chưa gắn remote)"

echo "== 2/4 Kiểm tra .env.production =="
if [ ! -f .env.production ]; then
  echo "THIẾU .env.production — copy từ .env.example, điền giá trị thật (JWT_SECRET, mật khẩu DB, tên miền qua Caddyfile) rồi chạy lại."
  exit 1
fi

echo "== 3/4 Dựng và chạy lại container =="
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

echo "== 4/4 Chờ API khỏe =="
for i in $(seq 1 30); do
  if curl -fs http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "API OK: $(curl -s http://127.0.0.1:8000/health)"
    echo "Deploy xong. Mở https://<tên miền của bạn> để kiểm tra."
    exit 0
  fi
  sleep 2
done
echo "API chưa lên sau 60 giây — xem log: docker compose -f docker-compose.prod.yml logs api"
exit 1
