# Tổng kết TUẦN 2 — ExamBank AI (EB-201 → EB-207): HOÀN THÀNH

| Task | Kết quả | Kiểm chứng |
|---|---|---|
| EB-201 Sanitize | `parsers/sanitize.py`: xóa script/style/img + mọi thuộc tính lạ, chỉ giữ color/background/font-weight/text-decoration; hỗ trợ `<font color>` kiểu Word cũ. raw_html đã sanitize được lưu vào source_exams khi import | Test: mã độc bị loại, tín hiệu đỏ còn nguyên; smoke thấy raw_html chứa color |
| EB-202 Parser Python | `parsers/parser.py` port trung thực từ prototype Bước 2: tách Question/Câu, phương án A–D, passage không tách rời câu con, cắt câu chỉ dẫn khỏi nội dung passage | Bộ đề vàng (EB-207) |
| EB-203 Answer Detector | 4 nguồn: red_text (0.99), highlight (0.97), answer_key_table (0.95, cần ≥2 cặp mới tin), bold_underline (0.80, đúng 1 phương án đậm/gạch chân ≥80%). Không có dấu hiệu → None, không bao giờ đoán | Bộ đề vàng: 12/12 đáp án đúng cả nhãn lẫn nguồn; câu không dấu hiệu bịa đáp án = 0 |
| EB-204 Upload docx | **mammoth làm mất hoàn toàn màu chữ đỏ** (đã kiểm chứng: nó không đọc w:color) → tự viết `parsers/docx_reader.py` đọc thẳng document.xml, giữ color/highlight (w:highlight + w:shd)/bold/underline, dùng CHUNG 1 parser với luồng paste | Test tạo .docx thật có đáp án đỏ → nạp được 2/2 câu có đáp án |
| EB-205 Dedup | `parsers/dedup.py` hash sha256(stem + options đã sắp xếp, chuẩn hoá khoảng trắng) theo đúng quy ước Bước 1; trùng trong workspace → bỏ qua, đếm vào stats | Test: nạp lại cùng đề → duplicates = 4, kho không tăng |
| EB-206 Review Queue | API: POST import (paste), POST import-docx, GET import-jobs, GET review-queue (kèm passage), PATCH review (approve bắt buộc có đáp án — chưa có mà không chọn → 422; gán difficulty + tags + sửa đáp án tính là teacher_manual; reject). Giao diện: tab Nhập đề (dán giàu định dạng + nút mẫu + tải .docx + xem stats) và tab Duyệt câu hỏi (chọn đáp án/độ khó/Unit, duyệt/loại) nối API thật | pytest + smoke HTTP thật trọn luồng: đăng ký → tạo đề → import đề highlight (3/3 có đáp án, passage đi kèm) → duyệt kèm VD + gs12_unit3 → kho approved lọc theo Unit ra đúng 1 câu |
| EB-207 Bộ đề vàng | 5 file fixture trong `apps/api/tests/golden_files/`: đề tô đỏ, đề highlight + passage, đề không đáp án + bảng đáp án cuối, đề cloze không đáp án, đề đáp án in đậm/gạch chân. Tổng 16 câu, 12 đáp án kỳ vọng | **Đạt 100% trên bộ fixture** (tách câu, nhãn đáp án, nguồn đáp án, passage). LƯU Ý TRUNG THỰC: đây là fixture mô phỏng đúng định dạng đề thật, chưa phải 5 file đề thật của giáo viên — khi có file thật, đưa vào cùng thư mục này để đo và tinh chỉnh parser tiếp |

**Trạng thái test cuối Tuần 2: pytest 24 passed (16 Tuần 1 + 3 golden + 5 import), CI local ALL GREEN, frontend build thành công.**

## Bổ sung sau phản hồi của Ha (2026-10-29): giữ nguyên in đậm/gạch chân là NỘI DUNG đề
Ha chỉ ra đúng một lỗ hổng thật: in đậm/gạch chân trong đoạn văn và câu hỏi là phần học sinh
phải nhận biết (VD: "từ **crucial** in đậm trong đoạn đồng nghĩa với từ gì?", "câu được gạch
chân trong đoạn 4 ngụ ý gì?"). Kiểm tra lại đã phát hiện 3 lỗi và sửa hết:
1. Marker nội bộ `[[B]]` bị LỌT vào stem/passage lưu trữ, định dạng nhấn mạnh bị mất hẳn →
   nay parser sinh riêng `stem_html` / passage `content_html` / option html khôi phục `<b> <u> <i>`,
   bản text luôn sạch marker (có test cấm lọt `[[`).
2. Đáp án viết bằng `<span style="font-weight: bold">` (kiểu dán từ Word/Google Docs) không được
   nhận diện → nay nhận đậm/gạch chân qua cả thẻ lẫn style (font-weight ≥ 600, text-decoration).
3. Màn Duyệt trước đây hiển thị text thô, giáo viên không đối chiếu được phần nhấn mạnh →
   nay hiển thị đúng in đậm/gạch chân/nghiêng như đề gốc (nội dung đã qua sanitize phía server).
Nguyên tắc phân biệt rõ: nhấn mạnh trong THÂN CÂU/ĐOẠN VĂN = nội dung đề, luôn giữ;
nhấn mạnh trong PHƯƠNG ÁN = tín hiệu đáp án tiềm năng (chỉ khi đúng 1 phương án được nhấn và
không có dấu hiệu mạnh hơn). Kiểm chứng: 5 test hồi quy mới — pytest 29 passed.

## Thay đổi nền tảng kèm theo
- `models.py`: JSONB thêm `.with_variant(JSON, 'sqlite')` — PostgreSQL vẫn dùng JSONB, SQLite (test/dev) dùng JSON. Hết lỗi CompileError khi test các bảng có JSONB (import_jobs, ai_solutions...).
- Import hiện chạy đồng bộ trong request (đủ nhanh với đề ≤ vài trăm câu); chuyển Celery bất đồng bộ để ở Tuần 3 cùng pipeline AI.

## Nợ kỹ thuật / giới hạn còn mở
1. ~~EB-207 chờ 5 file đề thật~~ — ĐÃ ĐÓNG 2026-10-29: Ha gửi đủ 5 đề thật (3 docx + 2 pdf).
   Sau tinh chỉnh: K12 40/40 câu + 40/40 đáp án đỏ; UNIT_5 40/40 + 40/40 highlight;
   UNIT_3 148/148 câu, 0 đáp án bịa; 2 PDF 40/40 câu qua trích text. Chi tiết tại
   `WEEK2-REAL-EXAMS-REPORT.md`. File gốc của giáo viên KHÔNG commit vào git.
2. Import đồng bộ — đề rất lớn (>500 câu) nên chuyển nền ở Tuần 3.
3. Cảnh báo deprecation pydantic-settings ở `app/config.py` vẫn còn (không chặn).
4. Máy hiện tại vẫn không có Docker — kiểm chứng thay bằng SQLite + uvicorn thật như Tuần 1.

## Sẵn sàng cho Tuần 3 (EB-301 → EB-307)
AI giải thật cho câu `needs_answer`: hàng đợi Celery, gọi model có structured output, ngưỡng tin cậy < 0,70 khoá nút Duyệt, chống hallucination bằng self-check, tính chi phí.
