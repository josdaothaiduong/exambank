# ExamBank AI — Ngân hàng đề Tiếng Anh THPT

Xây từ gốc: Bước 1 Dữ liệu (`docs/01-foundation-database-api.md`) →
Bước 2 Prototype (`docs/02-prototype-spec.md`, bản chạy được ở `prototype/index.html`) →
Bước 3 Lộ trình MVP (`docs/03-mvp-roadmap-4-weeks.md`, backlog `docs/03-backlog.csv`).

## Chạy hệ thống (5 dòng)

```bash
cp .env.example .env
docker compose up --build
# Web:  http://localhost:3000
# API:  http://localhost:8000/health  |  Swagger: http://localhost:8000/docs
# MinIO console: http://localhost:9001
```

API tự chạy `alembic upgrade head` khi khởi động (tạo đủ 15 bảng theo Bước 1).

## Chạy migration thủ công (ngoài Docker)

```bash
cd apps/api
pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg://exambank:exambank_dev@localhost:5432/exambank alembic upgrade head
alembic downgrade base   # gỡ toàn bộ schema
```

## Trạng thái thi công

- [x] EB-101 Repo + Docker Compose 6 service (web, api, worker, db, redis, minio)
- [x] EB-102 SQLAlchemy models + Alembic migration #1 (15 bảng)
- [x] EB-103 Seed taxonomy: 68 tags (30 Unit Global Success 10-11-12, 15 dạng bài, 4 độ khó...) + `GET /api/v1/tags`
- [ ] EB-104 Auth JWT + Workspace
- [x] EB-105 API khung: Source-Exams (tạo/list/chi tiết) + Question-Items lọc 4 trục (khối qua tag/Unit/dạng bài/độ khó) + trạng thái + search + phân trang, mọi truy vấn qua chốt quyền workspace.
- [x] EB-106 Frontend Next.js nối API thật (đăng nhập, đề gốc, kho) — build thành công, smoke test đạt
- [x] EB-107 CI (GitHub Actions + scripts/ci.sh) — CI local ALL GREEN

**TUẦN 1 HOÀN THÀNH** — xem `WEEK1-REPORT.md`. Tiếp theo: Tuần 2 (EB-201 parser server).
