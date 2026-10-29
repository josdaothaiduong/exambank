# EB-207 — Đo parser trên 5 ĐỀ THẬT (Ha gửi 2026-10-29)

File gốc lưu tại `~/workspace/user/files/` (KHÔNG commit vào git — tài liệu của giáo viên).

## Kết quả cuối cùng sau khi tinh chỉnh

| File | Bản chất | Tách câu | Đáp án nhận đúng | Phương án hoàn hảo | Passage theo section |
|---|---|---|---|---|---|
| K12_TEST_UNIT_10_LIFELONG_LEARNING.docx | Đề thi 40 câu, đáp án tô đỏ 2 tông (FF0000 + EE0000) | **40/40** | **40/40 (red_text)** | 38/40 | Đúng 5 section [6, 11, 5, 8, 10] |
| UNIT_5_THE_WORLD_OF_WORK_GS12_NYEN__1.docx | Đề 40 câu, đáp án highlight cyan | **40/40** | **40/40 (highlight)** | 35/40 | Đúng 5 section [6, 11, 5, 8, 10] |
| UNIT_3_CITIES_OF_THE_FUTURE.docx | Bộ bài tập 148 câu, KHÔNG đánh dấu đáp án (chữ cái phương án tô hồng trang trí, in đậm tràn lan) | **148/148** | **0 bịa** (đúng bản chất: tất cả vào needs_answer) | 148/148 | 3 nhóm exercise |
| UNIT_1_FAMILY_LIFE_-_TEST_2.pdf | Đề 40 câu bản học sinh, không đáp án | 40/40* | 0 (đúng bản chất) | 40/40* | — |
| UNIT_2_TEST_02_THE_GENERATION_GAP.pdf | Đề 40 câu bản học sinh, không đáp án | 40/40* | 0 (đúng bản chất) | 40/40* | — |

\* PDF đo qua trích text bằng pdftotext (hệ thống CHƯA có nút upload PDF — theo lộ trình, PDF thuộc giai đoạn sau; số liệu cho thấy nếu có trích text sạch thì parser xử lý tốt định dạng này).

Kiểm chứng đầu-cuối bằng importer thật (UNIT_5): import vào DB cho stats 40 câu / 40 có đáp án / 5 PassageGroup riêng, nạp lại lần 2 bị chặn trùng 40/40.

## Điểm số TRƯỚC khi tinh chỉnh (để thấy dữ liệu thật quan trọng thế nào)
- K12: tách 3 câu, nhận 1 đáp án. UNIT_5: tách 17 câu, nhận 2 đáp án. UNIT_3: 148 câu nhưng bịa 3 đáp án từ in đậm.

## 10 bài học từ đề thật đã được đưa vào parser
1. Header câu dùng cả "Question 1." (dấu chấm) — không chỉ dấu hai chấm.
2. Word cắt run cực vụn: "Question" | "7:", "Question 1" + "7" (= 17), "B" + "." + nội dung — mọi regex cấu trúc phải chịu được marker/khoảng trắng chen giữa (GAP).
3. Đáp án tô đỏ có nhiều tông: FF0000, EE0000, C00000 → nhận theo dải đỏ (R cao, G/B thấp) nhưng loại hồng trang trí E8336D (đề UNIT_3 tô hồng MỌI chữ cái phương án).
4. Đáp án có 3 kiểu tô: cả phương án trong 1 run; nhãn và nội dung là 2 run riêng; chỉ tô ở chữ cái (chỉ tin khi duy nhất 1 phương án có dấu).
5. Run "." có thể là 1 run highlight riêng — phải gom dấu chấm về sát chữ cái phương án.
6. Regex phương án không được "ăn" khoảng trắng cuối (lookahead) — nếu không sẽ nuốt mất dấu cách phân tách của phương án kế tiếp.
7. In đậm là trang trí/nội dung tràn lan trong đề thật (UNIT_3: 806 run bold, gồm cả header section) → đáp án bold-only hạ độ tin cậy xuống 0.65 (dưới ngưỡng 0.70, buộc giáo viên kiểm tra), gạch chân giữ 0.80.
8. Section mới bắt đầu ngay sau phương án cuối của câu cuối section trước: phải cắt phần đuôi (instruction + passage) khỏi phương án D và biến nó thành passage của section sau — nếu không, phương án D phình lên hàng nghìn ký tự và passage bị mất.
9. Câu sắp xếp (arrangement): hội thoại cũng đánh nhãn A./B./C. ở đầu dòng → khi có >4 marker, chọn cửa sổ A-B-C-D liên tiếp cuối cùng làm phương án thật.
10. Bảng đáp án: chữ "key" xuất hiện trong thân đề ("is the key to...") suýt cắt sạch đề — chỉ nhận header ĐÁP ÁN/ANSWER KEY khi nằm sau câu hỏi cuối cùng.

## Hạn chế còn lại (trung thực)
- K12 câu 15 (7 marker lẫn lộn) và 16 (3 phương án); UNIT_5 câu 14, 31, 32, 34, 35 (3 phương án): nguyên nhân là run trong file gốc dính liền nhau ("...eD. c - a...") không có ký tự phân tách — parser không tách nổi, giáo viên sửa tay ở màn Duyệt (đây là lý do màn Duyệt tồn tại).
- Upload PDF chưa có trong hệ thống (đo ngoại tuyến cho kết quả tốt về định dạng).
- Các định dạng rút ra từ 5 đề thật đã được đóng thành fixture hồi quy `exam6_real_formats.html` trong bộ đề vàng — từ nay mọi thay đổi parser đều phải qua cả 6 fixture + 29 test (hiện đều đạt, CI ALL GREEN).
