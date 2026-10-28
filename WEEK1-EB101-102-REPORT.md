# Báo cáo EB-101 + EB-102 (Tuần 1, phần 1)

## Đã làm
- **EB-101:** Monorepo tại thư mục này: `apps/web` (Next.js khung), `apps/api` (FastAPI),
  `apps/worker` (Celery qua service worker dùng chung image api), `docs/` (bộ ba Bước 1-2-3),
  `docker-compose.yml` đủ 6 service (web, api, worker, db=pvector/pg16, redis, minio),
  `.env.example`, `README.md` (5 dòng chạy hệ thống), git init + commit đầu tiên.
  Service `api` tự chạy `alembic upgrade head` khi khởi động.
- **EB-102:** `apps/api/app/models.py` — SQLAlchemy models cho toàn bộ schema Bước 1;
  `apps/api/migrations/versions/0001_initial.py` — Alembic migration trích nguyên văn SQL
  từ `docs/01` mục 5 cho upgrade(), và downgrade() xóa 15 bảng + 3 enum theo thứ tự ngược.

## Sửa lỗi phát hiện trong lúc code (quan trọng)
Các tài liệu Bước 1/3 ghi "11 bảng" là **đếm sai**. Đếm lại từ SQL gốc: **15 bảng**.
Đã sửa ở README, lộ trình Bước 3 và migration. Models kiểm chứng tự động ra đúng 15 bảng:
users, workspaces, source_exams, import_jobs, passage_groups, tags, question_items,
options, question_tags, ai_solutions, exam_templates, template_sections, exams,
exam_versions, exam_items.

## Kiểm chứng đã chạy (2026-10-28)
- [x] docker-compose.yml parse hợp lệ, đúng 6 service
- [x] Cài dependencies trong venv sạch: `pip install -r requirements.txt` thành công
- [x] Models biên dịch: metadata chứa đúng 15 bảng, không thừa/thiếu
- [x] `alembic upgrade head --sql` (offline) sinh đủ DDL: 15 bảng ứng dụng + alembic_version, 3 enum, indexes, FK
- [x] Endpoint `GET /health` trả `{status: ok}`
- [x] pytest cho schema: `apps/api/tests/test_models.py`

## Giới hạn môi trường (nói thẳng)
Máy làm việc hiện tại **không có Docker và không có PostgreSQL**, nên chưa chạy được
`docker compose up` trực tiếp tại đây và chưa chạy migration lên DB thật.
Việc còn lại để đóng EB-101/102 100%: trên máy có Docker, chạy `cp .env.example .env && docker compose up --build`,
mở `http://localhost:8000/health` và kiểm tra `\dt` trong Postgres thấy 15 bảng.
API đã cấu hình tự chạy migration khi khởi động nên bước này không cần thao tác tay.

## Tiếp theo
EB-103 (seed taxonomy) → EB-104 (auth + workspace) → EB-105 (API khung) → EB-106 (frontend) → EB-107 (CI).
