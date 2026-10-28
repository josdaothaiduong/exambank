# ExamBank AI — BƯỚC 2: Prototype giao diện + Luồng copy-paste

> Bám đúng Bước 1 (`01-foundation-database-api.md`). Prototype này không vẽ tự do:
> mỗi màn hình tương ứng với 1 nhóm API và 1 trạng thái dữ liệu đã chốt ở nền tảng.

## 1. Mục tiêu của prototype (chỉ kiểm chứng 1 giả thuyết)

Giáo viên có paste 1 đoạn đề từ Word vào web, hệ thống có \*\*giữ được màu đỏ/highlight
của đáp án**&#32;và \*\*bóc tách đúng thành từng câu để duyệt** hay không?
Nếu luồng này không trơn tru, mọi tính năng sau đều vô nghĩa.

Prototype là bản **chạy được trong trình duyệt, dữ liệu mô phỏng ở phía client** —
chưa nối backend thật. Parser trong prototype chính là bản mẫu của Parser Contract
ở Bước 1, mục 6.1.

## 2. Bản đồ màn hình <-> API <-> Trạng thái (Bước 1)

| Màn hình | Việc của giáo viên | API tương ứng (Bước 1) | Trạng thái |
| --- | --- | --- | --- |
| 1. Nhập đề | Điền thông tin đề gốc + paste / chọn đề mẫu | `POST /source-exams`, `POST /source-exams/:id/import` | `draft -> parsing` |
| 2. Kết quả phân tích | Xem thống kê: bao nhiêu câu có đáp án / chưa có / trùng | `GET /import-jobs/:id` | `parsed / needs_answer` |
| 3. Duyệt câu hỏi | Sửa đáp án, gán dạng bài / độ khó / Unit, cho AI giải câu trống, Duyệt hoặc Loại | `GET .../review-queue`, `PATCH /question-items/:id/review`, `POST .../ai-solve` | `pending_review -> approved / rejected` |
| 4. Kho câu hỏi | Lọc theo Lớp x Unit x Dạng bài x Độ khó, tìm kiếm | `GET /question-items?status=approved...` | chỉ `approved` |
| 5. Tạo đề (xem trước) | Chọn mẫu đề, sinh đề từ kho, xem cảnh báo thiếu câu | `POST /exams/generate`, `POST /exams/:id/export` | chỉ lấy `approved` |

## 3. Luồng copy-paste giữ màu/highlight — cách hoạt động

1. Ô paste là `contenteditable`. Khi giáo viên nhấn Ctrl+V, prototype đọc
   `clipboardData.getData('text/html')` — **không** đọc text thuần.
   HTML từ Word/Google Docs mang theo `color:#ff0000` và `background-color:yellow`.
2. Sanitize: chỉ giữ các thuộc tính có ý nghĩa đáp án — `color`, `background-color`,
   `font-weight`, `text-decoration` — và xóa mọi thẻ/script nguy hiểm.
3. Parser duyệt DOM: đoạn text nào có màu đỏ hoặc highlight thì được đánh dấu
   là *vùng đáp án* trước khi chuyển thành text thuần để tách câu.
4. Tách câu theo mẫu `Question 1:` / `Câu 1:`, tách phương án theo `A. B. C. D.`
5. Phương án nào chứa vùng đáp án -> `detected_answer` + `answer_source`:
   đỏ = `red_text` (tin cậy 0.99), highlight = `highlight` (0.97).
   Không có vùng đáp án -> `needs_answer`, chờ AI giải hoặc giáo viên chọn tay.
6. Trùng lặp: tính hash từ nội dung câu + đáp án đã sắp xếp, trùng với câu đã duyệt
   thì đếm vào `duplicates` và cảnh báo ở màn hình duyệt.

> Giới hạn đã biết (ghi rõ trong prototype): paste từ PDF/Zalo thường mất HTML màu,
> khi đó hệ thống không bịa đáp án — câu sẽ rơi vào `needs_answer`.

## 4. Dữ liệu mẫu trong prototype (để thử đủ 3 trường hợp)

- **Mẫu A — Đáp án tô đỏ:** 3 câu Grammar/Vocabulary, đáp án là chữ đỏ.
- **Mẫu B — Đáp án highlight:** 1 passage Reading + 2 câu con, đáp án bôi vàng.
- **Mẫu C — Chưa có đáp án:** 3 câu không đánh dấu, để thử nút "AI giải (mô phỏng)"
  -> AI đề xuất đáp án + lời giải + độ tin cậy, giáo viên vẫn phải duyệt mới vào kho.

## 5. Tiêu chí nghiệm thu Bước 2

- [x] Paste / nạp Mẫu A: parser báo đúng 3/3 câu có đáp án, nguồn `red_text`
- [x] Paste / nạp Mẫu B: passage được giữ thành 1 nhóm, 2 câu con có đáp án `highlight`
- [x] Mẫu C: 3 câu ở trạng thái `needs_answer`; bấm AI giải ra đề xuất, chưa duyệt thì chưa vào kho
- [x] Ở màn hình Duyệt: đổi đáp án bằng cách click phương án -> nguồn đổi thành `teacher_manual`
- [x] Chỉ câu đã Duyệt mới xuất hiện ở Kho và mới được Tạo đề lấy ra
- [x] Tạo đề khi kho thiếu câu phải hiện cảnh báo rõ thiếu bao nhiêu, dạng nào

## 6. Sau Bước 2

Bước 3 sẽ biến prototype này thành lộ trình code thật 4 tuần: thay parser mô phỏng
bằng parser server (mammoth + sanitize), thay dữ liệu client bằng các API ở Bước 1,
và thay AI mô phỏng bằng AI thật có hàng đợi.