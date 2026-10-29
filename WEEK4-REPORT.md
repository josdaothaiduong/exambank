# Báo cáo Tuần 4 — Sinh đề, xuất bản, UAT, deploy (EB-401 → EB-407)

Ngày: 2026-10-29 · pytest **49 passed** · CI local **ALL GREEN** · UAT vòng 1 trên đề thật: **trọn vòng đời đạt**.
Quyết định của Ha tuần này: chưa cần API key AI — đi thẳng Tuần 4 (provider demo vẫn là mặc định).

## EB-401 — 3 template hệ thống (seed idempotent)
- Đề thi thử TN THPT 50 câu/60' (11 phần), Kiểm tra 45' 40 câu (9 phần), Kiểm tra 15' 10 câu (ngữ pháp + từ vựng). Tổng từng mẫu khớp đúng số câu công bố; mỗi phần có tỉ lệ độ khó NB/TH/VD/VDC riêng.

## EB-402 — Thuật toán sinh đề
- Chỉ lấy câu **approved + có đáp án**; câu thuộc đoạn văn đi theo **nguyên nhóm đoạn**, phần khác chỉ lấy câu độc lập; ưu tiên câu ít dùng nhất (used_count); tỉ lệ độ khó theo từng phần (thiếu mức khó thì mượn mức khác, thiếu tổng thể thì báo lỗi).
- Thiếu câu → **HTTP 422 liệt kê từng phần: cần bao nhiêu, kho có bao nhiêu** (đã xác nhận cả ở test lẫn UAT thật).
- Tinh chỉnh từ UAT: cho phép dùng một phần của một nhóm đoạn khi không ghép vừa nguyên nhóm (đoạn vẫn đi nguyên vẹn cùng các câu được chọn).

## EB-403 — Hoán vị + mã đề + cân bằng đáp án
- Sinh 1–8 mã đề từ cùng một bộ câu: hoán vị thứ tự (nhóm đoạn di chuyển nguyên khối, không bị xé lẻ) + hoán vị phương án từng câu; nhãn đáp án đúng được phân bổ cân bằng — UAT thật đạt **6/6/6/6 ở cả 4 mã đề** (tiêu chí lệch ≤ 10%: đạt tuyệt đối).
- Bất biến đã kiểm chứng tự động: sau hoán vị, nội dung phương án đúng ở mọi mã đề vẫn khớp đáp án gốc trong kho (0 vi phạm trên đề thật).

## EB-404 — Export Word (python-docx)
- 3 bản: **học sinh** (không đáp án), **giáo viên** (đáp án in đậm + gạch chân, kèm giải thích và bảng đáp án cuối mỗi mã đề), **ma trận đề** (cấu trúc phần + cân bằng đáp án theo mã). Giữ định dạng in đậm/gạch chân/nghiêng của thân câu khi sang Word. File xuất từ cùng snapshot với bản xem trước nên khớp tuyệt đối.

## EB-405 — Xem trước + bản in/PDF
- Tab **Tạo đề**: chọn mẫu → sinh đề → xem trước từng mã ngay trên web (bật/tắt hiện đáp án), nút mở **bản in HTML** (nút In/Lưu PDF của trình duyệt) dùng chung nguồn dữ liệu với Word.

## EB-406 — UAT vòng 1 trên đề thật (K12 Unit 10 + UNIT_5): bắt và vá 4 vấn đề thật
Chạy trọn vòng đời qua HTTP thật (`scripts/uat_week4.py`): đăng ký → nạp 2 đề .docx thật → duyệt 74 câu → sinh đề → xuất Word. Phát hiện:
1. **Sập import 500 vì 1 câu lỗi**: câu 16 của đề K12 có 2 dãy nhãn A-B-C-D (lỗi đã biết ở file gốc) làm vi phạm UNIQUE và đánh sập cả lượt nạp 40 câu. ĐÃ VÁ: câu có nhãn phương án trùng bị cách ly thành câu lỗi trong error_log, phần còn lại nạp bình thường (K12: 39 câu vào + 1 câu lỗi rõ ràng). Có test hồi quy riêng.
2. **Router sinh đề chưa được đăng ký vào app** (viết xong, test hàm trực tiếp đều pass nhưng HTTP trả 404). ĐÃ VÁ + thêm test chốt danh sách route bắt buộc.
3. **Phân loại dạng bài quá thô** (68/74 câu bị gán đọc hiểu → không mẫu nào sinh được từ kho thật): đã nâng cấp bộ phân loại theo dấu hiệu thân câu (chỗ trống → điền khuyết; dấu hiệu hỏi về đoạn → đọc hiểu; sắp xếp câu...). Kho thật sau vá: điền khuyết 37, đọc hiểu 31, trái nghĩa 4, đồng nghĩa 2.
4. **Ghép nhóm đoạn quá cứng** — đã nới như ghi ở EB-402.
- Kết quả cuối: mẫu TN bị chặn 422 với lý do rõ ràng (kho từ 2 đề dạng TN không có câu phát âm/trọng âm/ngữ pháp độc lập — đúng thực tế); template khớp kho (Điền khuyết 11 + Đọc hiểu 13) sinh thành công **4 mã × 24 câu**, cân bằng tuyệt đối, xuất Word 3 bản mở đọc bình thường.

## EB-407 — Bộ deploy Đường A (chưa deploy thật — chờ VPS)
- `scripts/deploy.sh` (kéo code → kiểm tra env → dựng container → chờ API khỏe), `scripts/backup.sh` (pg_dump, giữ 14 bản), `DEPLOY-RUNBOOK.md` (hướng dẫn 1 trang), compose production + Caddyfile đã kiểm tra cú pháp.
- **Điểm chờ Ha** (không đổi từ Tuần 1): thuê VPS + (nên có) tên miền + tạo GitHub repo gửi link. Xong 3 việc này là đưa lên mạng được ngay theo runbook.

## Hạn chế / nợ kỹ thuật còn mở sau MVP
- Chưa có giao diện tạo **template tự chế** (UAT phải tạo qua DB) — ứng viên số 1 sau MVP, vì kho của mỗi giáo viên có hình dạng khác nhau.
- Phân loại dạng bài: câu độc lập điền trống vẫn mặc định gán ngữ pháp (chưa tách được từ vựng/ngữ pháp tinh), câu đồng/trái nghĩa nằm trong đoạn đọc hiểu được tính là câu độc lập khi lọc theo phần — cần 1 vòng tinh chỉnh nữa nếu muốn sinh mẫu TN trọn vẹn từ kho thật.
- Chưa có upload PDF; Celery/Redis mới chạy thật khi lên Docker ở VPS.
- AI thật vẫn chờ API key của Ha (mọi khung đo EB-307 đã sẵn sàng).
