# Tổng kết TUẦN 1 — ExamBank AI (EB-101 → EB-107): HOÀN THÀNH

| Task | Kết quả | Kiểm chứng |
|---|---|---|
| EB-101 Repo + Docker | Monorepo, compose 6 service, README, git | Compose YAML hợp lệ, đúng 6 service |
| EB-102 Models + Migration | 15 bảng (đính chính từ "11" ghi sai trước đó), migration 0001 trích nguyên văn Bước 1 | Alembic offline sinh đủ DDL, models = đúng 15 bảng |
| EB-103 Seed taxonomy | 68 tags: 30 Unit Global Success (đối chiếu mục lục SGK), 15 dạng bài, NB/TH/VD/VDC, skills, topics; `GET /api/v1/tags` | Seed chạy 2 lần không trùng; mỗi khối đúng 10 Unit |
| EB-104 Auth + Workspace | JWT + PBKDF2, migration 0002 bổ sung `password_hash` (schema gốc thiếu), đăng ký tự tạo workspace, cách ly owner (người khác -> 404) | Test cách ly 2 user đầy đủ |
| EB-105 API khung | Source-Exams CRUD khung + Question-Items lọc 4 trục + search + phân trang | Lọc kết hợp 4 trục ra đúng câu; kiểm chứng qua HTTP thật |
| EB-106 Frontend | Next.js: đăng nhập/đăng ký, dashboard Đề gốc (tạo/list thật) + Kho (lọc thật, Unit lấy từ /tags); tab Nhập đề/Tạo đề ghi rõ thuộc Tuần 2/4, không dùng dữ liệu giả. Bắt và sửa lỗi thiếu CORS | `npm run build` thành công; smoke test thật: đăng ký -> tạo đề -> liệt kê, CORS preflight đúng |
| EB-107 CI | GitHub Actions 3 job (backend test, frontend build, compose config) + `scripts/ci.sh` chạy local | CI local: **ALL GREEN** (16 test passed + build OK) |

**Trạng thái test cuối Tuần 1: pytest 16 passed.**

## Nợ kỹ thuật / giới hạn còn mở (ghi trung thực)
1. Máy phát triển hiện tại không có Docker/PostgreSQL: `docker compose up` chưa chạy tại đây;
   đã kiểm chứng thay thế bằng SQLite + uvicorn thật + build thật. Cần 1 lần chạy Docker ở máy có Docker để đóng hẳn.
2. Cảnh báo deprecation ở `app/config.py` (class-based Config của pydantic-settings) — không chặn, xử lý ở Tuần 2.
3. Workspace nhiều thành viên (tổ bộ môn) — Phase 2 theo lộ trình.

## Sẵn sàng cho Tuần 2 (EB-201 → EB-207)
Parser server là việc khó nhất dự án; nền móng dữ liệu/API/auth/frontend đã sẵn:
đề gốc tạo được, câu hỏi lọc được, chỉ còn thiếu parser nạp câu vào kho và hàng đợi duyệt.
