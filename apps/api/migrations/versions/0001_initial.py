"""EB-102 — Migration #1: toàn bộ schema Bước 1 (15 bảng, 3 enum, pgvector).

SQL trong upgrade() được trích nguyên văn từ docs/01-foundation-database-api.md mục 5
để đảm bảo migration và tài liệu nền tảng không bao giờ lệch nhau.

Revision ID: 0001_initial
Revises:
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('-- Cần: CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS vector;')
    op.execute("CREATE TYPE question_status AS ENUM\n  ('draft','parsed','needs_answer','ai_solving','pending_review','approved','rejected','archived');")
    op.execute("CREATE TYPE answer_source AS ENUM\n  ('red_text','highlight','bold_underline','marker_star','answer_key_table','ai_solved','teacher_manual','unknown');")
    op.execute("CREATE TYPE difficulty_level AS ENUM ('NB','TH','VD','VDC');")
    op.execute("CREATE TABLE users (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  email TEXT UNIQUE NOT NULL,\n  full_name TEXT NOT NULL,\n  role TEXT NOT NULL DEFAULT 'teacher', -- teacher | dept_head | admin\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);")
    op.execute('CREATE TABLE workspaces (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  owner_id UUID NOT NULL REFERENCES users(id),\n  name TEXT NOT NULL, -- VD: "Tổ Tiếng Anh - THPT ABC" hoặc "Cá nhân cô Ha"\n  school_name TEXT,\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);')
    op.execute('CREATE TABLE source_exams (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,\n  title TEXT NOT NULL,               -- VD: Đề giữa kỳ 1 - Lớp 12 - 2025\n  grade SMALLINT CHECK (grade IN (10,11,12)),\n  exam_kind TEXT,                    -- 15min | 45min | mid_term | final | graduation | mock\n  source_name TEXT,                  -- Sở GD / Trường / Đề minh họa BGD\n  school_year TEXT,                  -- 2025-2026\n  original_file_url TEXT,            -- file gốc trên S3/MinIO, giữ để đối chiếu\n  raw_html TEXT,                     -- HTML gốc sau paste/upload, GIỮ NGUYÊN màu/highlight\n  created_by UUID NOT NULL REFERENCES users(id),\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);')
    op.execute("CREATE TABLE import_jobs (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  source_exam_id UUID NOT NULL REFERENCES source_exams(id) ON DELETE CASCADE,\n  status TEXT NOT NULL DEFAULT 'queued', -- queued|parsing|ai_solving|done|failed\n  stats JSONB NOT NULL DEFAULT '{}',     -- {total, with_answer, needs_answer, duplicates}\n  error_log JSONB NOT NULL DEFAULT '[]',\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),\n  finished_at TIMESTAMPTZ\n);")
    op.execute('CREATE TABLE passage_groups (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  source_exam_id UUID REFERENCES source_exams(id) ON DELETE SET NULL,\n  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,\n  passage_type TEXT NOT NULL, -- reading|cloze|announcement|leaflet|arrangement|listening_transcript\n  title TEXT,\n  content_html TEXT NOT NULL, -- giữ định dạng, blank được đánh dấu ____(12)____\n  content_text TEXT NOT NULL, -- bản plain text để search / embedding\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);')
    op.execute('CREATE TABLE tags (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  kind TEXT NOT NULL, -- grade|textbook|unit|topic|skill|grammar_point|vocab_theme\n  code TEXT NOT NULL, -- VD: grade_12, gs12_unit3, topic_environment\n  label TEXT NOT NULL,\n  parent_id UUID REFERENCES tags(id),\n  UNIQUE (kind, code)\n);')
    op.execute("CREATE TABLE question_items (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,\n  source_exam_id UUID REFERENCES source_exams(id) ON DELETE SET NULL,\n  passage_id UUID REFERENCES passage_groups(id) ON DELETE SET NULL,\n  question_type TEXT NOT NULL,\n  order_in_source INT,\n  stem_html TEXT NOT NULL,\n  stem_text TEXT NOT NULL,\n  status question_status NOT NULL DEFAULT 'draft',\n  difficulty difficulty_level,\n  difficulty_score SMALLINT CHECK (difficulty_score BETWEEN 1 AND 10),\n  correct_option_id UUID, -- FK thêm sau khi options được tạo (xem bên dưới)\n  answer_source answer_source NOT NULL DEFAULT 'unknown',\n  answer_confidence NUMERIC(4,3), -- 0.000 - 1.000, bắt buộc nếu answer_source='ai_solved'\n  explanation_html TEXT,\n  dedup_hash TEXT NOT NULL,   -- hash(stem_text chuẩn hóa + options) để chống trùng cứng\n  embedding vector(1536),     -- để chống trùng theo ngữ nghĩa + tìm kiếm thông minh\n  used_count INT NOT NULL DEFAULT 0,\n  last_used_at TIMESTAMPTZ,\n  created_by UUID NOT NULL REFERENCES users(id),\n  reviewed_by UUID REFERENCES users(id),\n  reviewed_at TIMESTAMPTZ,\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),\n  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);")
    op.execute('CREATE INDEX idx_q_workspace_status ON question_items(workspace_id, status);')
    op.execute('CREATE INDEX idx_q_type_diff ON question_items(question_type, difficulty);')
    op.execute('CREATE UNIQUE INDEX idx_q_dedup ON question_items(workspace_id, dedup_hash);')
    op.execute('CREATE TABLE options (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  question_id UUID NOT NULL REFERENCES question_items(id) ON DELETE CASCADE,\n  label TEXT NOT NULL,        -- A | B | C | D\n  content_html TEXT NOT NULL,\n  content_text TEXT NOT NULL,\n  position SMALLINT NOT NULL, -- 0..3\n  UNIQUE (question_id, label)\n);')
    op.execute('ALTER TABLE question_items\n  ADD CONSTRAINT fk_q_correct_option\n  FOREIGN KEY (correct_option_id) REFERENCES options(id) ON DELETE SET NULL;')
    op.execute('CREATE TABLE question_tags (\n  question_id UUID NOT NULL REFERENCES question_items(id) ON DELETE CASCADE,\n  tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,\n  is_ai_suggested BOOLEAN NOT NULL DEFAULT false,\n  PRIMARY KEY (question_id, tag_id)\n);')
    op.execute("CREATE TABLE ai_solutions (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  question_id UUID NOT NULL REFERENCES question_items(id) ON DELETE CASCADE,\n  model TEXT NOT NULL,\n  suggested_option_id UUID REFERENCES options(id),\n  explanation_html TEXT,\n  suggested_tags JSONB NOT NULL DEFAULT '[]',\n  suggested_difficulty difficulty_level,\n  confidence NUMERIC(4,3) NOT NULL,\n  raw_response JSONB,\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);")
    op.execute('CREATE TABLE exam_templates (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE, -- NULL = template hệ thống\n  name TEXT NOT NULL, -- VD: Tốt nghiệp THPT 2025 - 40 câu - 50 phút\n  grade SMALLINT, total_questions INT NOT NULL, duration_minutes INT NOT NULL,\n  is_system BOOLEAN NOT NULL DEFAULT false,\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);')
    op.execute('CREATE TABLE template_sections (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  template_id UUID NOT NULL REFERENCES exam_templates(id) ON DELETE CASCADE,\n  section_order SMALLINT NOT NULL,\n  name TEXT NOT NULL, -- VD: Đọc hiểu 2\n  question_type TEXT NOT NULL,\n  passage_type TEXT,  -- NULL nếu là câu độc lập\n  question_count INT NOT NULL,\n  difficulty_mix JSONB NOT NULL DEFAULT \'{}\', -- {"NB":0.4,"TH":0.3,"VD":0.2,"VDC":0.1}\n  tag_filter JSONB NOT NULL DEFAULT \'{}\'      -- {"unit_codes":["gs12_unit3"]}\n);')
    op.execute('CREATE TABLE exams (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,\n  template_id UUID REFERENCES exam_templates(id),\n  title TEXT NOT NULL,\n  grade SMALLINT, duration_minutes INT,\n  created_by UUID NOT NULL REFERENCES users(id),\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);')
    op.execute('CREATE TABLE exam_versions (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  exam_id UUID NOT NULL REFERENCES exams(id) ON DELETE CASCADE,\n  code TEXT NOT NULL, -- 101, 102, 103, 104\n  answer_balance JSONB NOT NULL DEFAULT \'{}\', -- {"A":10,"B":10,"C":10,"D":10} để kiểm tra cân bằng\n  UNIQUE (exam_id, code)\n);')
    op.execute('CREATE TABLE exam_items (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  exam_version_id UUID NOT NULL REFERENCES exam_versions(id) ON DELETE CASCADE,\n  question_id UUID NOT NULL REFERENCES question_items(id),\n  passage_id UUID REFERENCES passage_groups(id),\n  position SMALLINT NOT NULL,\n  shuffled_correct_label TEXT, -- đáp án đúng SAU khi hoán vị ở mã đề này\n  snapshot_json JSONB NOT NULL, -- nội dung đóng băng tại thời điểm xuất đề\n  UNIQUE (exam_version_id, position)\n);')


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS exam_items CASCADE")
    op.execute("DROP TABLE IF EXISTS exam_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS exams CASCADE")
    op.execute("DROP TABLE IF EXISTS template_sections CASCADE")
    op.execute("DROP TABLE IF EXISTS exam_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_solutions CASCADE")
    op.execute("DROP TABLE IF EXISTS question_tags CASCADE")
    op.execute("DROP TABLE IF EXISTS options CASCADE")
    op.execute("DROP TABLE IF EXISTS question_items CASCADE")
    op.execute("DROP TABLE IF EXISTS tags CASCADE")
    op.execute("DROP TABLE IF EXISTS passage_groups CASCADE")
    op.execute("DROP TABLE IF EXISTS import_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS source_exams CASCADE")
    op.execute("DROP TABLE IF EXISTS workspaces CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
    op.execute("DROP TYPE IF EXISTS question_status")
    op.execute("DROP TYPE IF EXISTS answer_source")
    op.execute("DROP TYPE IF EXISTS difficulty_level")
