# HƯỚNG DẪN ĐƯA EXAMBANK LÊN MẠNG — 1 TRANG (Đường A: VPS + Docker + Caddy)

## Cần chuẩn bị (việc của Ha, ~30 phút)
1. **Thuê VPS**: Hetzner (Singapore) gói 2 vCPU / 4 GB RAM (~$8–15/tháng) hoặc nhà cung cấp tương tự. Hệ điều hành: Ubuntu 24.04.
2. **Tên miền** (tùy chọn nhưng nên có để có HTTPS đẹp): trỏ bản ghi A của tên miền về IP của VPS.
3. **Tài khoản GitHub**: tạo repo trống, báo lại để đẩy code lên (sau đó server kéo code từ GitHub).

## Lần đầu cài đặt (trên VPS, ~10 phút)
```bash
# 1. Cài Docker
curl -fsSL https://get.docker.com | sh

# 2. Lấy code
git clone <link-repo-github> exambank && cd exambank

# 3. Tạo cấu hình thật
cp .env.example .env.production
nano .env.production   # điền: POSTGRES_PASSWORD (mạnh), JWT_SECRET (chuỗi ngẫu nhiên dài),
                       # AI_PROVIDER/AI_API_KEY/AI_MODEL nếu đã có key AI (chưa có thì để demo)

# 4. Khai tên miền trong infra/Caddyfile (biến DOMAIN) — hoặc sửa trực tiếp dòng đầu thành tên miền của bạn

# 5. Chạy
bash scripts/deploy.sh
```
API tự chạy migration khi khởi động. Sau khi deploy xong, mở `https://<tên miền>` → đăng ký tài khoản giáo viên đầu tiên → nạp đề dùng thử trọn vòng đời (Nhập đề → Duyệt → Tạo đề → tải Word).

## Cập nhật phiên bản mới
```bash
cd exambank && bash scripts/deploy.sh
```
(script tự kéo code, dựng lại container, kiểm tra API khỏe mới báo xong)

## Sao lưu (rất nên bật ngay ngày đầu)
```bash
crontab -e   # thêm dòng:  30 2 * * *  cd ~/exambank && bash scripts/backup.sh
```
Sao lưu nằm ở thư mục `backups/`, giữ 14 bản gần nhất. Khôi phục: `gunzip -c backups/<file>.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U exambank exambank`

## Khi có sự cố
- Xem log: `docker compose -f docker-compose.prod.yml logs -f api` (hoặc `web`, `db`)
- Khởi động lại: `docker compose -f docker-compose.prod.yml restart`
- API không lên sau deploy: kiểm tra `.env.production` (thiếu biến là lỗi thường gặp nhất).

## Trạng thái hiện tại
Bộ script + cấu hình production đã sẵn sàng và đã kiểm tra cú pháp. **Chưa deploy thật** vì chưa có VPS/tên miền — hoàn tất mục "Cần chuẩn bị" ở trên là triển khai được ngay.
