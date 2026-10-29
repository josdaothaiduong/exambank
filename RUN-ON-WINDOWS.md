# Chạy ExamBank AI trên máy tính cá nhân (Windows) — 0 đồng

Dùng cho giai đoạn sử dụng cá nhân: đăng ký tài khoản, nạp đề, duyệt câu hỏi,
quản lý kho ngân hàng đề, sinh đề và xuất Word — đầy đủ tính năng, dữ liệu nằm
ngay trên máy của bạn, không cần thuê máy chủ.

## 1. Yêu cầu máy tính

- Windows 10/11 64-bit, RAM từ 8 GB trở lên (4 GB chạy rất chậm), ổ cứng trống ~10 GB.
- Kết nối internet (chỉ cần khi cài đặt lần đầu và khi dùng AI giải đề).

## 2. Cài Docker Desktop (làm 1 lần)

1. Tải tại https://www.docker.com/products/docker-desktop/ → cài như phần mềm thường.
2. Nếu trình cài đặt hỏi về WSL 2: đồng ý (đây là thành phần bắt buộc).
3. Khởi động lại máy nếu được yêu cầu, mở Docker Desktop và đợi biểu tượng
   cá voi ở góc màn hình chuyển sang trạng thái "Engine running".

## 3. Tải mã nguồn ExamBank (bản mới nhất)

1. Vào https://github.com/josdaothaiduong/exambank (đăng nhập GitHub của bạn).
2. Nút **Code** (màu xanh lá) → **Download ZIP** → giải nén vào một thư mục cố định,
   ví dụ `D:\ExamBank`. (Bản ZIP đã tải ngày 2026-10-28 đã cũ, đừng dùng lại.)

## 4. Chạy hệ thống

1. Mở thư mục đã giải nén, chạy file **`start-exambank.bat`**.
   - Lần đầu: hệ thống tự tạo file cấu hình và tự dựng mọi thành phần,
     mất khoảng 5–10 phút tùy mạng. Các lần sau chỉ ~30 giây.
2. Trình duyệt tự mở tại **http://localhost:3000** → bấm Đăng ký, tạo tài khoản
   đầu tiên cho bạn. Từ đây dùng như một website bình thường.
3. Tắt hệ thống: chạy **`stop-exambank.bat`**. Dữ liệu ngân hàng đề vẫn được
   giữ nguyên; mở lại bất cứ lúc nào bằng `start-exambank.bat`.

## 5. Bật AI giải đề thật bằng key Google Gemini của bạn

Mặc định hệ thống chạy AI ở chế độ demo (offline, độ chính xác thấp).
Để AI giải thật:

1. Mở file `.env` trong thư mục ExamBank bằng Notepad.
2. Sửa 4 dòng sau:

   ```
   AI_PROVIDER=openai
   AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
   AI_MODEL=gemini-2.5-flash
   AI_API_KEY=<dán key Google của bạn vào đây>
   ```

3. Lưu file, chạy `stop-exambank.bat` rồi `start-exambank.bat` để áp dụng.

File `.env` chứa key của bạn — không gửi file này cho ai, và nó đã bị chặn
khỏi GitHub nên không bao giờ bị đẩy lên mạng.

## 6. Sao lưu dữ liệu

Toàn bộ ngân hàng đề nằm trong thư mục dự án + dữ liệu Docker.
Cách đơn giản nhất: định kỳ sao chép cả thư mục ExamBank sang ổ cứng
ngoài/Google Drive. Khi chuyển lên VPS sau này, dữ liệu được mang theo
nguyên vẹn bằng bản sao lưu cơ sở dữ liệu — không mất câu nào.

## 7. Muốn truy cập từ điện thoại/máy khác?

Giai đoạn cá nhân chỉ cần dùng trên máy này. Khi cần mở từ xa, bổ sung
Cloudflare Tunnel (miễn phí) — nhờ Muse hướng dẫn khi bạn sẵn sàng,
không phải cài lại từ đầu.
