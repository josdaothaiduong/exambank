# ExamBank AI — BƯỚC NỀN TẢNG 1

## Thiết kế Database + API + Kiến trúc dữ liệu (Bản gốc để code MVP)

> Nguyên tắc: Xây từ gốc lên. Database sai thì prototype và code đều phải đập đi.
> Vì vậy bước này chốt trước: **dữ liệu lưu thế nào, câu hỏi là gì, đáp án đến từ đâu, trạng thái nào được dùng để ra đề.**
> Đối tượng: Tiếng Anh THPT Việt Nam (lớp 10-11-12), format đề hiện hành + đề kiểm tra thường xuyên.

---

## 1. Năm nguyên tắc nền tảng (không thay đổi về sau)

1. **Atomic Item, không lưu đề nguyên văn làm trung tâm**
   Đề gốc chỉ là *nguồn nhập*. Đơn vị tái sử dụng là `QuestionItem` và `PassageGroup`.
   Một đề gốc -> tách thành nhiều item -> các item kết hợp thành vô số đề mới.
2. **Passage không bao giờ tách rời câu con**
   Reading, Cloze, Listening transcript, Announcement, Leaflet, Sentence Arrangement
   đều là `PassageGroup (1) — (n) QuestionItem`. Xóa/sửa passage phải kiểm tra item con.
3. **Đáp án phải có nguồn gốc (provenance)**
   Mọi đáp án đều ghi rõ: đến từ tô đỏ, highlight, bảng đáp án, AI giải, hay giáo viên nhập tay.
   Không có đáp án "không rõ nguồn" trong kho chính thức.
4. **AI không được tự publish**
   AI chỉ tạo bản *đề xuất*. Chỉ câu ở trạng thái `approved` (giáo viên duyệt) mới được
   Exam Builder lấy ra để tạo đề. Đây là chốt an toàn chất lượng.
5. **Mọi câu đều phải lọc được theo 4 trục**
   `Khối lớp x Sách/Unit x Dạng bài/Kỹ năng x Mức độ (NB-TH-VD-VDC)`
   Thiếu 1 trục là sau này không tạo được ma trận đề.

---

## 2. Bản đồ domain (Domain Map)

```
User / Workspace (giáo viên / tổ bộ môn)
  └─ SourceExam        : đề gốc được nạp vào (Word/PDF/paste)
       └─ ImportJob    : 1 lần parse/AI xử lý, có log lỗi để thử lại
            ├─ PassageGroup : đoạn văn, bài đọc, bài điền, thông báo...
            └─ QuestionItem : từng câu hỏi độc lập
                 ├─ Option    : A/B/C/D (hoặc True/False, hoặc đáp án tự luận ngắn)
                 ├─ Answer    : đáp án + nguồn gốc + độ tin cậy
                 ├─ Explanation: lời giải (giáo viên / AI)
                 └─ Tag[]     : Unit, chủ đề, kỹ năng, dạng bài, độ khó

Taxonomy (danh mục chuẩn, dùng chung toàn hệ thống)
  ├─ Grade (10/11/12) / Textbook (Global Success, i-Learn Smart World, Friends Global...)
  ├─ Unit / Lesson / Topic
  ├─ Skill & QuestionType
  └─ Difficulty & Cognitive Level

ExamTemplate (ma trận / format mẫu)
  └─ TemplateSection[] : mỗi phần bao nhiêu câu, dạng gì, độ khó ra sao

Exam (đề được sinh ra)
  └─ ExamVersion[] (mã đề 101, 102...)
       └─ ExamItem[] : tham chiếu tới QuestionItem + thứ tự + đáp án sau hoán vị
```

**Quyết định quan trọng:** `ExamItem` chỉ *tham chiếu* `QuestionItem.id`, không copy nội dung.
Khi câu gốc được sửa, hệ thống biết đề nào bị ảnh hưởng. Khi xuất bản, mới snapshot nội dung
vào bản xuất để đề đã phát hành không bị thay đổi ngược về sau (`exam_items.snapshot_json`).

---

## 3. Taxonomy chuẩn Tiếng Anh THPT — phải chốt ở nền tảng

### 3.1. QuestionType (enum — không dùng text tự do)

| code | Tên hiển thị | Nhóm |
| --- | --- | --- |
| `pronunciation` | Phát âm | Phonetics |
| `stress` | Trọng âm | Phonetics |
| `grammar_mc` | Ngữ pháp trắc nghiệm | Grammar |
| `vocabulary_mc` | Từ vựng trắc nghiệm | Vocabulary |
| `synonym` / `antonym` | Đồng nghĩa / Trái nghĩa | Vocabulary |
| `word_formation` | Dạng từ | Vocabulary |
| `communication` | Giao tiếp / Chức năng ngôn ngữ | Communication |
| `error_identification` | Tìm lỗi sai | Grammar |
| `cloze` | Đọc điền từ (theo passage) | Reading |
| `reading_comprehension` | Đọc hiểu (theo passage) | Reading |
| `reading_announcement` | Đọc thông báo / tờ rơi / quảng cáo | Reading |
| `sentence_arrangement` | Sắp xếp câu / đoạn / thư | Reading/Writing |
| `sentence_transformation` | Viết lại câu (giai đoạn sau) | Writing |
| `listening_mc` | Nghe trắc nghiệm (giai đoạn sau, cần audio) | Listening |

### 3.2. Difficulty — theo thông tư Việt Nam

`NB` Nhận biết | `TH` Thông hiểu | `VD` Vận dụng | `VDC` Vận dụng cao
Kèm `difficulty_score: 1..10` để sắp xếp mịn hơn khi sinh đề.

### 3.3. AnswerSource (nguồn gốc đáp án)

`red_text` | `highlight` | `bold_underline` | `marker_star` | `answer_key_table`
| `ai_solved` | `teacher_manual` | `unknown`

### 3.4. Trạng thái vòng đời câu hỏi (QuestionStatus)

```
draft -> parsed -> needs_answer -> ai_solving -> pending_review
      -> approved -> archived
                    \-> rejected (trùng / sai / không đạt)
```

Chỉ `approved` mới vào kho dùng được. Mọi chuyển trạng thái đều ghi log.

---

## 4. Sơ đồ quan hệ (ERD rút gọn)

```
users 1-n workspaces (owner/member)
workspaces 1-n source_exams 1-n import_jobs
source_exams 1-n passage_groups 1-n question_items
source_exams 1-n question_items (câu độc lập, passage_id = NULL)
question_items 1-n options
question_items 1-1 answers (current) , 1-n answer_history
question_items n-n tags  qua question_tags
question_items 1-n ai_solutions
exam_templates 1-n template_sections
exams n-1 exam_templates
exams 1-n exam_versions 1-n exam_items n-1 question_items
```

---

## 5. SQL Schema — PostgreSQL (bản MVP, chạy được ngay)

```sql
-- Cần: CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE question_status AS ENUM
  ('draft','parsed','needs_answer','ai_solving','pending_review','approved','rejected','archived');
CREATE TYPE answer_source AS ENUM
  ('red_text','highlight','bold_underline','marker_star','answer_key_table','ai_solved','teacher_manual','unknown');
CREATE TYPE difficulty_level AS ENUM ('NB','TH','VD','VDC');

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'teacher', -- teacher | dept_head | admin
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, -- VD: "Tổ Tiếng Anh - THPT ABC" hoặc "Cá nhân cô Ha"
  school_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_exams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL,               -- VD: Đề giữa kỳ 1 - Lớp 12 - 2025
  grade SMALLINT CHECK (grade IN (10,11,12)),
  exam_kind TEXT,                    -- 15min | 45min | mid_term | final | graduation | mock
  source_name TEXT,                  -- Sở GD / Trường / Đề minh họa BGD
  school_year TEXT,                  -- 2025-2026
  original_file_url TEXT,            -- file gốc trên S3/MinIO, giữ để đối chiếu
  raw_html TEXT,                     -- HTML gốc sau paste/upload, GIỮ NGUYÊN màu/highlight
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE import_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_exam_id UUID NOT NULL REFERENCES source_exams(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued', -- queued|parsing|ai_solving|done|failed
  stats JSONB NOT NULL DEFAULT '{}',     -- {total, with_answer, needs_answer, duplicates}
  error_log JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE passage_groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_exam_id UUID REFERENCES source_exams(id) ON DELETE SET NULL,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  passage_type TEXT NOT NULL, -- reading|cloze|announcement|leaflet|arrangement|listening_transcript
  title TEXT,
  content_html TEXT NOT NULL, -- giữ định dạng, blank được đánh dấu ____(12)____
  content_text TEXT NOT NULL, -- bản plain text để search / embedding
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind TEXT NOT NULL, -- grade|textbook|unit|topic|skill|grammar_point|vocab_theme
  code TEXT NOT NULL, -- VD: grade_12, gs12_unit3, topic_environment
  label TEXT NOT NULL,
  parent_id UUID REFERENCES tags(id),
  UNIQUE (kind, code)
);

CREATE TABLE question_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  source_exam_id UUID REFERENCES source_exams(id) ON DELETE SET NULL,
  passage_id UUID REFERENCES passage_groups(id) ON DELETE SET NULL,
  question_type TEXT NOT NULL,
  order_in_source INT,
  stem_html TEXT NOT NULL,
  stem_text TEXT NOT NULL,
  status question_status NOT NULL DEFAULT 'draft',
  difficulty difficulty_level,
  difficulty_score SMALLINT CHECK (difficulty_score BETWEEN 1 AND 10),
  correct_option_id UUID, -- FK thêm sau khi options được tạo (xem bên dưới)
  answer_source answer_source NOT NULL DEFAULT 'unknown',
  answer_confidence NUMERIC(4,3), -- 0.000 - 1.000, bắt buộc nếu answer_source='ai_solved'
  explanation_html TEXT,
  dedup_hash TEXT NOT NULL,   -- hash(stem_text chuẩn hóa + options) để chống trùng cứng
  embedding vector(1536),     -- để chống trùng theo ngữ nghĩa + tìm kiếm thông minh
  used_count INT NOT NULL DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  created_by UUID NOT NULL REFERENCES users(id),
  reviewed_by UUID REFERENCES users(id),
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_q_workspace_status ON question_items(workspace_id, status);
CREATE INDEX idx_q_type_diff ON question_items(question_type, difficulty);
CREATE UNIQUE INDEX idx_q_dedup ON question_items(workspace_id, dedup_hash);

CREATE TABLE options (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id UUID NOT NULL REFERENCES question_items(id) ON DELETE CASCADE,
  label TEXT NOT NULL,        -- A | B | C | D
  content_html TEXT NOT NULL,
  content_text TEXT NOT NULL,
  position SMALLINT NOT NULL, -- 0..3
  UNIQUE (question_id, label)
);
ALTER TABLE question_items
  ADD CONSTRAINT fk_q_correct_option
  FOREIGN KEY (correct_option_id) REFERENCES options(id) ON DELETE SET NULL;

CREATE TABLE question_tags (
  question_id UUID NOT NULL REFERENCES question_items(id) ON DELETE CASCADE,
  tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  is_ai_suggested BOOLEAN NOT NULL DEFAULT false,
  PRIMARY KEY (question_id, tag_id)
);

CREATE TABLE ai_solutions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id UUID NOT NULL REFERENCES question_items(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  suggested_option_id UUID REFERENCES options(id),
  explanation_html TEXT,
  suggested_tags JSONB NOT NULL DEFAULT '[]',
  suggested_difficulty difficulty_level,
  confidence NUMERIC(4,3) NOT NULL,
  raw_response JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exam_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE, -- NULL = template hệ thống
  name TEXT NOT NULL, -- VD: Tốt nghiệp THPT 2025 - 40 câu - 50 phút
  grade SMALLINT, total_questions INT NOT NULL, duration_minutes INT NOT NULL,
  is_system BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE template_sections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id UUID NOT NULL REFERENCES exam_templates(id) ON DELETE CASCADE,
  section_order SMALLINT NOT NULL,
  name TEXT NOT NULL, -- VD: Đọc hiểu 2
  question_type TEXT NOT NULL,
  passage_type TEXT,  -- NULL nếu là câu độc lập
  question_count INT NOT NULL,
  difficulty_mix JSONB NOT NULL DEFAULT '{}', -- {"NB":0.4,"TH":0.3,"VD":0.2,"VDC":0.1}
  tag_filter JSONB NOT NULL DEFAULT '{}'      -- {"unit_codes":["gs12_unit3"]}
);

CREATE TABLE exams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  template_id UUID REFERENCES exam_templates(id),
  title TEXT NOT NULL,
  grade SMALLINT, duration_minutes INT,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exam_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exam_id UUID NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
  code TEXT NOT NULL, -- 101, 102, 103, 104
  answer_balance JSONB NOT NULL DEFAULT '{}', -- {"A":10,"B":10,"C":10,"D":10} để kiểm tra cân bằng
  UNIQUE (exam_id, code)
);

CREATE TABLE exam_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exam_version_id UUID NOT NULL REFERENCES exam_versions(id) ON DELETE CASCADE,
  question_id UUID NOT NULL REFERENCES question_items(id),
  passage_id UUID REFERENCES passage_groups(id),
  position SMALLINT NOT NULL,
  shuffled_correct_label TEXT, -- đáp án đúng SAU khi hoán vị ở mã đề này
  snapshot_json JSONB NOT NULL, -- nội dung đóng băng tại thời điểm xuất đề
  UNIQUE (exam_version_id, position)
);
```

### Chỉ mục & quy tắc dữ liệu bắt buộc

- Không cho tạo `ExamItem` từ câu chưa `approved` — kiểm tra ở tầng API + trigger DB.
- `dedup_hash` = hash của stem đã chuẩn hóa (bỏ dấu câu thừa, lower-case) + options đã sắp xếp.
  Trùng cứng -> chặn. Trùng ngữ nghĩa (cosine embedding > 0.92) -> cảnh báo, giáo viên quyết định.
- Mọi bảng đều có `workspace_id` để phân quyền tổ bộ môn / cá nhân — không truy vấn chéo workspace.

---

## 6. API Contract — REST /api/v1 (chốt trước khi code frontend)

Nguyên tắc: Frontend (prototype ở Bước 2) chỉ được gọi đúng các endpoint này.
Đổi API phải đổi file này trước.

### 6.1. Nhập đề & bóc tách — trái tim của hệ thống

```
POST /api/v1/source-exams
  Tạo đề gốc. Body: { title, grade, exam_kind, source_name, school_year }

POST /api/v1/source-exams/:id/import
  Nạp nội dung. Hỗ trợ 3 dạng (chọn 1):
    a) { mode:"paste_html", html:"<p>...<span style='color:red'>since</span>...</p>" }
    b) { mode:"upload_docx", file: multipart }   -> server dùng mammoth chuyển docx->HTML giữ màu
    c) { mode:"upload_pdf",  file: multipart }   -> cảnh báo: có thể mất màu đáp án
  Response 202: { import_job_id, status:"queued" }

GET  /api/v1/import-jobs/:id
  -> { status, stats:{ total:50, with_answer:38, needs_answer:12, duplicates:2 },
       error_log:[{ line_hint:"Question 23", issue:"only_3_options" }] }

GET  /api/v1/source-exams/:id/review-queue
  -> Danh sách câu đã parse để giáo viên duyệt: passage + câu + đáp án đoán được + ô sửa nhanh
PATCH /api/v1/question-items/:id/review
  Body: { action:"approve"|"reject"|"edit_and_approve",
          correct_option_id?, difficulty?, explanation_html?, tag_ids?[] }
```

**Hợp đồng parser (Parser Contract) — đầu ra bắt buộc của bước parse:**

```json
{
  "passages": [{ "temp_id": "p1", "passage_type": "reading_comprehension",
                 "content_html": "...", "question_temp_ids": ["q31","q32"] }],
  "questions": [{
    "temp_id": "q12", "passage_temp_id": null,
    "question_type": "grammar_mc",
    "stem_html": "She has lived here ______ 2010.",
    "options": [{ "label":"A","content_text":"for" },
                { "label":"B","content_text":"since" }],
    "detected_answer": { "label":"B", "source":"red_text", "confidence": 0.99 },
    "warnings": []
  }]
}
```

Parser không chắc -> `detected_answer = null` + `warnings:["ambiguous_format"]`,
tuyệt đối không đoán bừa đáp án.

### 6.2. AI giải câu chưa có đáp án

```
POST /api/v1/question-items/:id/ai-solve        -> tạo ai_solution, status -> ai_solving
POST /api/v1/question-items/ai-solve-batch      Body: { question_ids:[...] } -> hàng đợi Redis
GET  /api/v1/question-items/:id/ai-solutions    -> xem đề xuất + confidence + lời giải
```

Quy tắc: `confidence < 0.70` -> bắt buộc giáo viên sửa tay, nút Duyệt bị khóa kèm lý do.

### 6.3. Kho câu hỏi — tìm & lọc

```
GET /api/v1/question-items?workspace_id=&status=approved&grade=12
    &unit=gs12_unit3&question_type=reading_comprehension&difficulty=VD
    &search=environment&page=1&page_size=20
POST /api/v1/question-items            -> tạo câu thủ công (giáo viên tự soạn)
PATCH /api/v1/question-items/:id       -> sửa câu / đáp án / tag
DELETE /api/v1/question-items/:id      -> chỉ archive, không xóa cứng nếu đã dùng trong đề
GET /api/v1/tags?kind=unit&grade=12    -> lấy taxonomy cho bộ lọc
```

### 6.4. Template & Sinh đề

```
GET/POST /api/v1/exam-templates
GET/POST /api/v1/exam-templates/:id/sections
POST /api/v1/exams/generate
  Body: { template_id, title, version_count:4, version_codes:["101","102","103","104"],
          filters:{ grade:12, unit_codes:["gs12_unit1","gs12_unit2","gs12_unit3"] },
          avoid_recently_used_days: 90 }
  Response: { exam_id, versions:[{ code:"101", total:40, warnings:
              ["Thiếu 2 câu VDC dạng reading - đã bù bằng câu VD"] }] }
  Lỗi 422 nếu kho không đủ câu đạt chuẩn - phải nói rõ thiếu phần nào, bao nhiêu câu.
POST /api/v1/exams/:id/export
  Body: { format:"docx"|"pdf", include_answers:bool, include_explanations:bool,
          include_matrix:bool, school_template_id? }
  -> { download_url }
```

### 6.5. Bảo mật & phân quyền (làm ngay từ MVP)

- JWT auth, mọi query đều lọc theo `workspace_id` của user (Row-Level Security ở Postgres nếu có thể).
- HTML nạp vào phải sanitize (chỉ giữ: color, background-color/highlight, bold, italic, underline)
  để tránh XSS và giữ đúng tín hiệu đáp án.
- File gốc lưu private trên S3/MinIO, chỉ cấp signed URL ngắn hạn.

---

## 7. Thứ tự code từ nền tảng này (để Bước 2 và 3 bám vào)

1. Chạy migration SQL ở mục 5 -> có DB thật.
2. Seed taxonomy: khối 10-12, Unit của Global Success (mỗi khối 10 Unit), QuestionType, Difficulty.
3. API tối thiểu: `source-exams` + `import (paste_html)` + `review-queue` + `question-items (list/filter)`.
4. Chỉ sau khi 3 việc trên chạy được mới làm giao diện prototype (Bước 2) và AI solve.

## 8. Tiêu chí nghiệm thu Bước nền tảng 1

- [x] Tạo được 1 đề gốc, paste 1 đoạn HTML có đáp án đỏ, parse ra đúng cấu trúc ở mục 6.1
- [x] Câu chưa duyệt (`pending_review`) không xuất hiện khi gọi API sinh đề
- [x] Lọc được câu theo Unit + Dạng bài + Độ khó cùng lúc
- [x] Nhập trùng 1 câu lần 2 bị chặn/cảnh báo bởi `dedup_hash`

---

*File này là nguồn sự thật (single source of truth) cho database/API. Bước 2 và 3 phải bám đúng file này.*