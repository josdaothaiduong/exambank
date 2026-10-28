# ExamBank AI — BƯỚC 3: Lộ trình MVP 4 tuần để code thật

> Bám Bước 1 (Database/API) và Bước 2 (Prototype). Lộ trình này không thêm tính năng mới nào
> ngoài việc biến prototype mô phỏng thành sản phẩm thật, nối backend thật, parser thật, AI thật.
> Giả định nguồn lực: **1 lập trình viên full-stack làm toàn thời gian** + giáo viên (chủ sản phẩm)
> tham gia kiểm thử 2 buổi/tuần. Nếu làm bán thời gian, nhân đôi mọi mốc thời gian — không cắt bớt Tuần 1.

---

## 1. Chốt công nghệ (locked — không bàn lại trong 4 tuần)

| Tầng | Lựa chọn | Lý do chốt |
|---|---|---|
| Frontend | Next.js + TypeScript + TipTap Editor | TipTap giữ được HTML màu/highlight khi paste, hệ sinh thái React mạnh |
| Backend | FastAPI (Python) | Mạnh nhất cho xử lý docx/AI/export Word: `mammoth`, `python-docx`, thư viện AI đều ở Python |
| Database | PostgreSQL 16 + `pgvector` | Đúng schema Bước 1, vừa quan hệ vừa vector chống trùng |
| Hàng đợi | Redis + Celery | AI giải hàng loạt và parse file lớn phải chạy nền, không treo giao diện |
| Lưu file | MinIO (dev) / S3 (prod) | File gốc private, signed URL ngắn hạn |
| AI | Lớp trừu tượng `AIProvider` — model cấu hình qua biến môi trường | Không khóa cứng vào 1 nhà cung cấp; đổi model không sửa code nghiệp vụ |
| Đóng gói | Docker Compose (web, api, worker, db, redis, minio) | 1 lệnh chạy toàn bộ môi trường dev giống hệt staging |
| Kiểm thử | pytest (backend) + Vitest/Playwright (frontend) + bộ đề vàng | Xem mục 6 |

**Cấu trúc repo (monorepo):**
```
exambank/
  apps/
    web/            # Next.js + TipTap (port giao diện từ prototype Bước 2)
    api/            # FastAPI — routers: source_exams, imports, questions, ai, exams, exports
      app/
        models/     # SQLAlchemy models khớp schema Bước 1
        parsers/    # paste_html_parser.py, docx_parser.py, answer_detector.py, dedup.py
        ai/         # provider.py, prompts/ (mỗi dạng bài 1 prompt), solver.py
        examgen/    # generator.py (cân bằng đáp án, hoán vị), exporter_docx.py, exporter_pdf.py
      migrations/   # Alembic — migration đầu tiên chính là SQL ở Bước 1, mục 5
      tests/        # gồm golden_files/ chứa đề thật đã ẩn danh
    worker/         # Celery tasks: parse_job, ai_solve_batch
  infra/docker-compose.yml
  docs/             # 3 file bước 1-2-3 này được copy vào đây làm nguồn sự thật
```

---

## 2. Phạm vi MVP — làm gì và dứt khoát KHÔNG làm gì

**Trong MVP (phải có để gọi là xong):**
1. Đăng nhập + Workspace cá nhân
2. Nạp đề bằng paste HTML và upload `.docx` (PDF để sau — xem dưới)
3. Parser server tách câu/passage, nhận đáp án tô đỏ/highlight, chống trùng cứng
4. Hàng đợi duyệt: sửa đáp án/dạng bài/độ khó/Unit, Duyệt/Loại
5. AI giải câu chưa có đáp án + lời giải + confidence (có cổng < 0.70)
6. Kho câu hỏi lọc theo Lớp × Unit × Dạng bài × Độ khó + tìm kiếm
7. Sinh đề theo 3 template có sẵn, nhiều mã đề, hoán vị đáp án, cân bằng A/B/C/D
8. Xuất Word + PDF: bản học sinh (không đáp án), bản giáo viên (có đáp án + lời giải), ma trận đề

**Ngoài MVP (ghi vào Phase 2, không làm chệch 4 tuần):**
Upload PDF giữ màu, Listening có audio, tự luận chấm tay, Google Form/Azota export,
kho chung tổ bộ môn & phân quyền nhiều người, app di động, thanh toán.

---

## 3. TUẦN 1 — Nền móng code (Foundation Sprint)

*Mục tiêu cuối tuần: chạy `docker compose up` là có web + api + db, đăng nhập được,
migration tạo đúng 15 bảng của Bước 1, seed xong taxonomy. Chưa cần parser.*

| Ngày | Task | ID | Đầu ra kiểm chứng được |
|---|---|---|---|
| D1 | Khởi tạo monorepo, Docker Compose, `.env.example`, README cách chạy | EB-101 | Clone về, 1 lệnh chạy lên cả 6 service |
| D1-2 | Migration #1 từ SQL Bước 1 + SQLAlchemy models + kiểm tra khóa ngoại `correct_option_id` | EB-102 | `\dt` trong Postgres thấy đủ 15 bảng, chạy migration lên/xuống được |
| D2 | Seed taxonomy: khối 10-12, Global Success 10 Unit/khối, 14 QuestionType, NB-TH-VD-VDC | EB-103 | `GET /tags?kind=unit&grade=12` trả đúng 10 Unit |
| D3 | Auth JWT + Workspace: đăng ký/đăng nhập, middleware lọc theo `workspace_id` | EB-104 | User A không đọc được dữ liệu của User B (có test tự động) |
| D3-4 | API khung: `POST/GET /source-exams`, `GET /question-items` (list + lọc 4 trục, chưa có dữ liệu thật vẫn trả đúng cấu trúc) | EB-105 | Gọi API bằng Swagger UI thấy đúng contract Bước 1, mục 6 |
| D4-5 | Frontend khung: port 4 tab từ prototype Bước 2 sang Next.js, nối API khung, màn hình đăng nhập | EB-106 | Đăng nhập trên web, tạo được 1 đề gốc, thấy trong danh sách |
| D5 | CI: lint + test tự chạy khi push; backup DB dev | EB-107 | Push code là CI chạy, báo đỏ khi test hỏng |

**Nghiệm thu Tuần 1:** Người không phải lập trình viên cũng chạy được hệ thống theo README;
không còn bảng/enum nào khác với Bước 1.

## 4. TUẦN 2 — Import & Parser thật (phần khó nhất, chiếm trọn 1 tuần là đúng)

*Mục tiêu cuối tuần: paste hoặc upload docx 1 đề thật 40 câu -> tách đúng câu,
nhận đúng đáp án đỏ/highlight, duyệt được trên web, câu approved nằm trong DB thật.*

| Ngày | Task | ID | Đầu ra kiểm chứng được |
|---|---|---|---|
| D1 | Sanitize HTML server-side (chỉ giữ color/background/bold/underline) + lưu `raw_html` | EB-201 | Paste HTML có thẻ lạ/script -> bị stripping, màu đáp án còn nguyên |
| D1-2 | Port parser từ prototype (JS) sang Python: tách `Question n:`, tách A-D, gộp passage | EB-202 | Parser chạy trên 3 mẫu A/B/C cho kết quả giống hệt prototype |
| D2-3 | Answer Detector: đỏ -> highlight -> bold/underline -> bảng đáp án ở cuối đề; không chắc thì để trống + warning | EB-203 | Đúng Parser Contract Bước 1: có `detected_answer{label,source,confidence}` hoặc `null` |
| D3 | Upload `.docx` qua `mammoth` (docx->HTML giữ màu) dùng chung 1 đường parser với paste | EB-204 | Cùng 1 đề, paste và upload docx cho kết quả tách câu giống nhau ≥ 95% |
| D4 | Dedup: `dedup_hash` chặn trùng cứng + cảnh báo trùng nội dung | EB-205 | Nạp lại cùng 1 đề lần 2 -> báo trùng, không tạo câu mới |
| D4-5 | Review Queue UI thật: sửa đáp án bằng click, sửa type/difficulty/Unit, Duyệt/Loại gọi `PATCH .../review` | EB-206 | Duyệt xong, câu biến khỏi hàng đợi và xuất hiện khi `GET ?status=approved` |
| D5 | Kiểm thử với **bộ đề vàng**: 5 đề thật của giáo viên (đã ẩn danh) | EB-207 | Đạt chỉ số ở mục 6; lỗi parser được ghi thành danh sách fix, không sửa cảm tính |

**Nghiệm thu Tuần 2 (cột mốc quan trọng nhất của MVP):** Giáo viên tự nạp 1 đề thật của mình,
không cần lập trình viên hỗ trợ, và duyệt xong ít nhất 30 câu vào kho.

## 5. TUẦN 3 — AI giải + Kho câu hỏi hoàn chỉnh

*Mục tiêu cuối tuần: câu chưa có đáp án được AI giải hàng loạt ở nền, giáo viên chỉ duyệt;
kho lọc/tìm kiếm mượt với vài trăm câu.*

| Ngày | Task | ID | Đầu ra kiểm chứng được |
|---|---|---|---|
| D1 | `AIProvider` trừu tượng + cấu hình model qua `.env` + ghi log chi phí/lượt gọi vào `ai_solutions` | EB-301 | Đổi model bằng biến môi trường, không sửa code |
| D1-2 | Prompt riêng theo dạng bài (grammar, vocabulary, reading, cloze...) + ép AI trả JSON đúng schema: `{answer_label, explanation, suggested_tags, difficulty, confidence}` | EB-302 | AI trả sai định dạng -> tự retry 1 lần -> vẫn sai thì đánh dấu lỗi, không lưu bừa |
| D2-3 | Celery task `ai_solve_batch` + thanh tiến độ trên UI + cổng confidence: < 0.70 khóa nút Duyệt | EB-303 | Chọn 20 câu chưa đáp án, bấm 1 lần, quay lại sau thấy đã có đề xuất |
| D3-4 | Duyệt AI: màn hình so sánh cạnh nhau — đáp án AI, lời giải, nút Sửa/Duyệt; lưu `answer_source='ai_solved'` | EB-304 | Không câu nào do AI giải mà vào kho khi chưa qua tay giáo viên |
| D4 | Tìm kiếm & lọc kho: full-text trên `stem_text` + lọc 4 trục + phân trang; hiển thị `used_count/last_used_at` | EB-305 | Lọc Unit 3 + VD + reading ra đúng tập câu, < 1 giây với 1.000 câu |
| D5 | Chống trùng ngữ nghĩa bằng embedding (cosine > 0.92 -> cảnh báo ở màn hình duyệt) | EB-306 | Nạp câu diễn đạt khác nhưng cùng nội dung -> có cảnh báo trùng mềm |
| D5 | Kiểm thử chất lượng AI trên 50 câu vàng đã có đáp án chuẩn (giáo viên giữ kín đáp án để chấm AI) | EB-307 | Đo được % AI đúng theo từng dạng bài; dạng nào < 85% thì ghi rõ trong báo cáo tuần |

**Nghiệm thu Tuần 3:** Nạp 1 đề *không có đáp án*, AI giải xong, giáo viên duyệt/sửa
và đưa được ≥ 80% số câu vào kho mà không phải gõ lại nội dung câu nào.

## 6. TUẦN 4 — Sinh đề + Xuất bản + Chạy thật với giáo viên

*Mục tiêu cuối tuần: từ kho đã duyệt, sinh được đề hoàn chỉnh in được ngay,
và 1-2 giáo viên thật dùng thử trọn vòng đời mà không cần hỗ trợ kỹ thuật.*

| Ngày | Task | ID | Đầu ra kiểm chứng được |
|---|---|---|---|
| D1 | Seed 3 template: Tốt nghiệp THPT 40 câu, 45 phút, 15 phút (theo `template_sections` Bước 1) | EB-401 | Chọn template thấy đúng cấu trúc từng phần |
| D1-2 | Thuật toán sinh đề: lọc theo section -> ưu tiên câu ít dùng/chưa dùng gần đây -> kiểm tra đủ câu, thiếu thì lỗi 422 nói rõ thiếu phần nào bao nhiêu câu | EB-402 | Kho thiếu câu VDC reading -> báo đúng "thiếu 2 câu VDC reading", không sinh đề chắp vá |
| D2 | Hoán vị câu + hoán vị đáp án sinh nhiều mã đề, cân bằng đáp án A/B/C/D lệch ≤ 10%, ghi `shuffled_correct_label` + `snapshot_json` | EB-403 | 4 mã đề cùng nội dung, thứ tự/đáp án khác nhau, đáp án từng mã tra đúng |
| D3 | Export Word bằng `python-docx` theo mẫu trường (Times New Roman, header, mã đề): bản HS, bản GV có đáp án+lời giải, ma trận đề | EB-404 | File Word mở lên in được ngay, không phải sửa format |
| D3-4 | Export PDF từ cùng dữ liệu + trang xem trước đề trên web | EB-405 | PDF và Word giống hệt nội dung |
| D4 | Vá lỗi UAT vòng 1 + xử lý các ca biên giáo viên phát hiện khi nạp đề thật của họ | EB-406 | Danh sách lỗi UAT được đóng ≥ 90% |
| D5 | Deploy staging (Docker trên 1 VPS), backup tự động, hướng dẫn sử dụng 1 trang + buổi dùng thử vòng 2 | EB-407 | Giáo viên truy cập link staging, tự làm trọn vòng đời |

**Nghiệm thu MVP (Định nghĩa "xong" toàn dự án):** Xem kịch bản vàng ở mục 7 — chạy thông
kịch bản đó trên staging, không lỗi chặn, thì MVP hoàn thành.

---

## 7. Kịch bản vàng nghiệm thu cuối cùng (Golden Scenario)

1. Giáo viên đăng nhập, tạo đề gốc "Giữa kỳ 1 — Lớp 12".
2. Paste 1 đề thật có đáp án tô đỏ (≥ 30 câu, có ít nhất 1 passage Reading).
3. Hệ thống báo đúng: tổng câu, số câu có đáp án, số câu chưa có, số câu trùng.
4. Giáo viên cho AI giải các câu chưa có đáp án, sửa 1-2 câu AI sai, duyệt tất cả câu đạt.
5. Ở Kho: lọc Unit + dạng Reading + độ khó VD ra đúng các câu vừa duyệt.
6. Chọn template 45 phút, sinh 4 mã đề — đáp án cân bằng, mỗi mã tra đáp án đúng.
7. Xuất Word bản học sinh (không còn màu đỏ/highlight, không lộ đáp án) và bản giáo viên
   (có đáp án + lời giải + ma trận). Mở file in thử — format đúng mẫu trường.

## 8. Chỉ số chất lượng bắt buộc (đo bằng bộ đề vàng, không đo bằng cảm giác)

| Chỉ số | Ngưỡng đạt |
|---|---|
| Tách đúng số câu (đề docx chuẩn format) | ≥ 95% |
| Nhận đúng đáp án tô đỏ / highlight | ≥ 95% |
| Passage bị tách rời khỏi câu con | 0 trường hợp |
| AI giải đúng — Grammar/Vocabulary | ≥ 90% trên tập vàng 50 câu |
| AI giải đúng — Reading/Cloze | ≥ 85% trên tập vàng |
| Câu chưa duyệt lọt vào đề được sinh | 0 trường hợp |
| Thời gian sinh 4 mã đề từ kho 1.000 câu | < 10 giây |

## 9. Rủi ro chính & cách chặn từ đầu

| Rủi ro | Cách chặn đã nằm trong lộ trình |
|---|---|
| Đề thật của giáo viên có format "mỗi trường một kiểu", parser vỡ | Tuần 2 D5 dùng 5 đề thật làm đề vàng; parser sửa theo dữ liệu thật, không theo tưởng tượng. Định dạng lạ -> câu vào hàng đợi sửa tay, không mất dữ liệu gốc (`raw_html` luôn được giữ) |
| AI giải sai làm giáo viên mất niềm tin | Cổng confidence + bắt buộc duyệt (Tuần 3) + đo % đúng công khai theo dạng bài (EB-307) |
| File Word xuất ra sai format trường học | Lấy đúng file mẫu của trường làm template export ngay Tuần 4 D3, in thử trong kịch bản vàng |
| Phạm vi phình to làm trễ MVP | Mục 2 khóa ngoài-phạm vi; mọi yêu cầu mới ghi vào Phase 2, không chen vào 4 tuần |
| 1 người làm, ốm/trễ 1 tuần | Thứ tự tuần đã xếp theo độ cốt lõi: trễ thì cắt Tuần 4 phần PDF (giữ Word), không cắt Tuần 1-2 |

## 10. Checklist khởi động Ngay — Ngày 1 của Tuần 1 (làm theo thứ tự)

- [ ] Tạo repo `exambank`, tạo cấu trúc thư mục ở mục 1
- [ ] Viết `infra/docker-compose.yml` với 6 service: web, api, worker, db, redis, minio
- [ ] Copy 3 file `01-*.md`, `02-*.md`, `03-*.md` vào `docs/` trong repo
- [ ] Chuyển SQL Bước 1 mục 5 thành Alembic migration đầu tiên, chạy thử lên DB rỗng
- [ ] Tạo `.env.example` (DATABASE_URL, REDIS_URL, S3_*, JWT_SECRET, AI_API_KEY, AI_MODEL) — không commit key thật
- [ ] Viết README: 5 dòng là chạy được hệ thống ở máy mới

---
*Hoàn thành Bước 3 = hoàn thành bộ ba nền tảng: Bước 1 (dữ liệu) -> Bước 2 (trải nghiệm) -> Bước 3 (lộ trình thi công).*
*Việc tiếp theo ngoài bộ ba này là bắt tay code Tuần 1 / EB-101.*
