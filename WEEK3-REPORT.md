# Báo cáo Tuần 3 — AI giải đề (EB-301 → EB-307)

Ngày: 2026-10-29 · Trạng thái: **HOÀN THÀNH 7/7 task** · pytest **42 passed** · CI local **ALL GREEN** · smoke HTTP thật đạt.

## EB-301 — AIProvider trừu tượng + log ai_solutions
- `app/ai/provider.py`: interface chung `solve(system, user, valid_labels)`; đổi nhà cung cấp/model **bằng env** (`AI_PROVIDER`, `AI_MODEL`, `AI_BASE_URL`, `AI_API_KEY`), không sửa code. Đã nối sẵn vào docker-compose (api + worker) và `.env.example`.
- Hai provider: `OpenAICompatibleProvider` (OpenAI chính hãng hoặc mọi endpoint tương thích OpenAI — gồm Gemini qua endpoint tương thích của Google) và `DemoProvider` (bộ giải quy tắc offline, xem EB-307).
- Mọi lần giải đều ghi `ai_solutions`: model, đáp án đề xuất, lời giải thích, gợi ý độ khó + tags, confidence, raw response + token usage + chi phí ước tính (bảng giá theo model trong provider).

## EB-302 — Prompt theo dạng bài + ép JSON + retry
- `app/ai/prompts.py`: system prompt giáo viên THPT + gợi ý riêng cho 11 dạng bài (ngữ pháp, từ vựng, đồng/trái nghĩa, đọc hiểu, điền khuyết, sắp xếp câu, viết lại câu, tìm lỗi sai, phát âm, trọng âm...).
- Ép JSON schema 5 trường (answer_label, explanation_vi, confidence, difficulty, tags); validate chặt (label phải thuộc phương án có thật, confidence trong [0,1]); sai định dạng → retry 1 lần → lỗi rõ ràng, **không lưu đáp án rác**.

## EB-303 — Celery ai_solve_batch + self-check + cổng confidence 0.70
- `app/ai/pipeline.py`: giải → **kiểm chứng chéo** (xáo trộn thứ tự phương án, giải độc lập lần 2; khớp nội dung thì tăng tin cậy, lệch thì hạ mạnh và ghi cảnh báo vào lời giải) → lưu ai_solutions → câu chuyển `pending_review` với `answer_source=ai_solved`.
- Celery task `app.worker.ai_solve_batch` dùng chung pipeline (đã đăng ký task; chạy thật khi có Redis trong Docker — máy hiện tại không có Redis nên kiểm chứng qua đường đồng bộ, cùng một code path). API: `POST /source-exams/{id}/solve-ai` (đồng bộ ở dev, Celery khi `AI_ASYNC=1`), `POST /question-items/{id}/solve-ai`.
- **Cổng 0.70 ở API duyệt**: câu AI giải với confidence < 0.70 thì duyệt "mù" bị chặn HTTP 422 — giáo viên phải tự tay chọn đáp án (khi đó nguồn chuyển thành `teacher_manual`). Smoke HTTP xác nhận: 422 khi không chọn, 200 khi giáo viên tự chọn.

## EB-304 — Màn Duyệt AI
- Thẻ câu hiển thị panel AI: model, độ tin cậy (nền đỏ khi < 70%), lời giải thích, gợi ý độ khó; nút "Duyệt vào kho" **bị khoá giao diện** đúng điều kiện của cổng server cho đến khi giáo viên tự chọn đáp án.
- Nút "✦ AI giải các câu chưa có đáp án" ở tab Duyệt: giải toàn bộ câu needs_answer của đề đã chọn, báo số câu đã giải / số câu tin cậy thấp / chi phí ước tính.

## EB-305 — Lọc kho 1000 câu
- Test quy mô: nạp 1000 câu, lọc đồng thời 4 trục (Unit × dạng bài × độ khó) trả **đúng tập kỳ vọng**, tổng thời gian 2 truy vấn (gồm cả tìm kiếm + phân trang) **0,08 giây** (< 1 giây theo tiêu chí).

## EB-306 — Chống trùng ngữ nghĩa (P1)
- `app/ai/similarity.py`: tương tự cosine trên tập từ của thân câu + phương án (không cần API ngoài; khi có embedding thật sẽ thay bằng pgvector, giữ nguyên giao diện).
- Khi import: câu mới giống ≥ 0.85 với câu **khác hash** đã có trong kho → vẫn nạp nhưng kèm cảnh báo `near_duplicates` (số liệu trong stats + panel ⚠ ở tab Nhập đề). Test: bản diễn đạt lại của một câu bị bắt đúng 1 cảnh báo; câu khác hẳn không bị báo nhầm.

## EB-307 — Đo chất lượng trên 50 câu vàng (đề thật)
- Bộ vàng `apps/api/tests/ai_golden_50.json`: 50 câu trích từ đề thật **UNIT_3** của Ha (trải đều 148 câu: từ vựng 18, ngữ pháp 19, đồng nghĩa 8, trái nghĩa 1, điền khuyết 2, đọc hiểu 2), đáp án chuẩn do Muse giải và đối chiếu ngữ cảnh từng câu (gồm cả việc đọc trọn đoạn văn cho câu điền khuyết/sắp xếp câu) — Ha có thể kiểm chứng lại bất kỳ câu nào.
- Kết quả **DemoProvider: đúng 9/50 (18%)** — đúng như bản chất của nó: bộ giải quy tắc offline chỉ bắt được các mẫu ngữ pháp rõ ràng (since → hiện tại hoàn thành, so sánh hơn...), KHÔNG đủ sức giải đề thật. Giá trị của EB-307 ở giai đoạn này là **harness đo đã sẵn sàng**: cắm provider thật vào là chạy lại ra ngay tỉ lệ đúng theo từng dạng bài.
- Điểm an toàn quan trọng: **41/41 câu DemoProvider trả lời sai đều có confidence < 0.70** — tức cổng duyệt sẽ chặn tất cả, buộc giáo viên tự quyết; 0 câu sai nào lọt qua dạng "AI tự tin nói sai".

## So sánh nhà cung cấp AI (giá tra cứu 2026-10-29, USD/1M token vào/ra)
| Model | Giá vào | Giá ra | Ghi chú |
|---|---|---|---|
| Gemini 2.5 Flash (Google) | $0.30 | $2.50 | Có **hạn mức miễn phí** qua AI Studio để thử; có endpoint tương thích OpenAI → cắm thẳng vào provider hiện tại, không sửa code |
| GPT-4o-mini (OpenAI) | $0.15 | $0.60 | Rẻ nhất trong nhóm mạnh; JSON mode ổn định |
| Claude Haiku 4.5 (Anthropic) | $1.00 | $5.00 | Đắt hơn ~7 lần, chất lượng tiếng Anh tốt |

Ước tính chi phí thực tế (mỗi câu gọi 2 lượt: giải + kiểm chứng chéo, ~900 token vào + ~240 token ra): GPT-4o-mini ≈ **$0.0003/câu** → giải trọn 148 câu Unit 3 ≈ **$0,04 (khoảng 1.000đ)**. Chi phí không phải rào cản; chỉ cần Ha chọn nhà cung cấp và tạo API key.

## Việc còn chờ Ha
1. **Chọn nhà cung cấp + tạo API key** (khuyến nghị: thử Gemini miễn phí trước, hoặc GPT-4o-mini). Có key → chạy lại EB-307 lấy tỉ lệ đúng thật + giải 148 câu Unit 3 thật.
2. GitHub: tạo repo trống và gửi link để đẩy code (điểm treo từ Tuần 1).

## Giới hạn còn mở (nói thẳng)
- Celery/Redis chưa chạy thật trên máy này (không có Docker/Redis) — task đã đăng ký và dùng chung pipeline đã kiểm chứng qua đường đồng bộ; khi deploy Docker (Tuần 4) sẽ chạy nền thật.
- DemoProvider chỉ để kiểm chứng hệ thống, không dùng giải đề cho học sinh.
- Phân loại dạng bài của parser với bộ bài tập Unit 3 còn thô (phần lớn bị gán reading_comprehension vì có "passage" là tiêu đề bài tập) — đáng cải thiện ở tuần sau nếu Ha muốn lọc kho theo dạng bài chính xác hơn.
