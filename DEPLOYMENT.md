# DEPLOYMENT — Đưa ExamBank lên GitHub & Public Web

## 0. Nguyên tắc kiến trúc (đọc trước để khỏi chọn sai đường)

ExamBank **không phải** một trang web tĩnh. Nó có 4 phần phải chạy liên tục:
giao diện (Next.js), API (FastAPI), hàng đợi xử lý nền/AI (Celery), cơ sở dữ liệu (PostgreSQL).

Hệ quả quan trọng: **Vercel chỉ chứa được phần giao diện.**
Vercel rất tốt cho Next.js, nhưng không chạy được Docker, Celery worker, Redis hay PostgreSQL lâu dài.
Đưa cả hệ thống lên "chỉ Vercel" là không thể — phải chọn 1 trong 3 đường ở dưới.

GitHub thì khác: GitHub là nơi **lưu mã nguồn** cho mọi đường đi, không phải nơi chạy ứng dụng
(trừ CI đã có sẵn ở `.github/workflows/ci.yml` — đẩy code lên là tự chạy test).

---

## 1. Đưa mã nguồn lên GitHub (làm 1 lần, ~5 phút)

Repo này đã sẵn sàng: chỉ 57 file mã nguồn được theo dõi bởi git,
`node_modules/`, `.next/`, `.env` thật đều đã bị `.gitignore` chặn — **không có bí mật nào trong repo**.

```bash
# 1) Trên github.com: tạo repo mới tên "exambank" (để Private khi đang phát triển)
# 2) Tại thư mục dự án trên máy bạn:
git remote add origin https://github.com/<tai-khoan-cua-ban>/exambank.git
git branch -M main
git push -u origin main
```

Sau đó, ở bất kỳ máy tính nào khác, lấy nguồn về và chạy chỉ bằng:

```bash
git clone https://github.com/<tai-khoan-cua-ban>/exambank.git
cd exambank
cp .env.example .env
docker compose up --build     # -> http://localhost:3000
```

Đây chính là vòng "có nguồn GitHub -> chạy trên máy tính" — GitHub là kho trung tâm,
máy nào clone về cũng chạy giống hệt nhau vì Docker đóng gói mọi phụ thuộc.

## 2. Ba đường public web — chọn 1

### Đường A (KHUYẾN NGHỊ cho giai đoạn này): VPS + Docker + tên miền
Giữ nguyên kiến trúc hiện tại, không phải viết lại gì. Chi phí thấp, toàn quyền dữ liệu của giáo viên.

1. Thuê VPS (2 CPU / 4 GB RAM là đủ cho MVP), cài Docker, trỏ tên miền về IP của VPS (bản ghi A).
2. `git clone` repo lên VPS, tạo `.env.production` từ `.env.production.example` (đổi hết mật khẩu/JWT_SECRET).
3. Chạy bản production:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```
   Caddy tự xin HTTPS (Let's Encrypt). Chỉ cổng 80/443 mở ra internet;
   DB/Redis/kho file nằm trong mạng nội bộ. Web và API chung 1 tên miền nên không vướng CORS.
4. Cập nhật phiên bản mới: `git pull && docker compose -f ... up -d --build`.

### Đường B: Vercel (giao diện) + dịch vụ quản trị cho phần còn lại
Hợp khi muốn giao diện tải nhanh toàn cầu và không muốn tự trông máy chủ. Phải chia hệ thống:

| Phần ở bản Docker hiện tại | Thay bằng dịch vụ |
|---|---|
| Web (Next.js) | **Vercel** — kết nối GitHub, đặt Root Directory = `apps/web`, biến `NEXT_PUBLIC_API_URL` = địa chỉ API |
| API + Worker (FastAPI/Celery) | **Render** hoặc **Railway** (chạy được tiến trình nền) — 2 service dùng chung image từ `apps/api` |
| PostgreSQL + pgvector | **Neon** hoặc **Supabase** (đều hỗ trợ pgvector) — lấy `DATABASE_URL` của họ |
| Redis | **Upstash Redis** — lấy `REDIS_URL` |
| MinIO (kho file) | **Cloudflare R2** hoặc **AWS S3** (MinIO vốn tương thích S3 nên ít phải sửa code) |

Việc bắt buộc ở đường B: đặt biến môi trường ở dashboard từng dịch vụ (không để trong code),
và thêm tên miền Vercel của bạn vào `CORS_ORIGINS` của API — tính năng này đã được dự trù sẵn trong code.

### Đường C: Chỉ Vercel — KHÔNG khả thi cho toàn hệ thống
Chỉ dùng nếu sau này tách riêng một trang giới thiệu/tải tài liệu tĩnh. Đừng chọn cho ứng dụng chính.

## 3. Checklist an toàn trước khi public (bắt buộc)

- [ ] Đổi toàn bộ mật khẩu mặc định trong `.env.production` (PostgreSQL, JWT_SECRET, MinIO/S3)
- [ ] Repo GitHub để Private cho tới khi sẵn sàng công khai; không bao giờ commit `.env` thật
- [ ] Khóa học phí AI: đặt hạn mức chi tiêu cho `AI_API_KEY` ở nhà cung cấp AI (từ Tuần 3 khi AI thật được nối)
- [ ] Bật sao lưu DB tự động trên VPS/dịch vụ quản trị
- [ ] Kiểm tra chỉ 80/443 mở ra internet (bản prod đã cấu hình sẵn điều này)

## 4. Trạng thái dự trù đã làm sẵn trong code

- [x] `.gitignore` sạch bí mật, repo đẩy lên GitHub được ngay
- [x] CI tự chạy khi đẩy code (EB-107)
- [x] `apps/web/vercel.json` cho đường B
- [x] `docker-compose.prod.yml` + `infra/Caddyfile` (HTTPS tự động) cho đường A
- [x] CORS cấu hình qua biến môi trường `CORS_ORIGINS` (thêm tên miền public không cần sửa code)
- [x] `.env.production.example` liệt kê mọi bí mật cần đặt ở môi trường public
