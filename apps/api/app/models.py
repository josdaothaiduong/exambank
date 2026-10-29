"""EB-102 — SQLAlchemy models khớp 100% schema ở Bước 1 (docs/01, mục 5).

Đếm lại chính xác: schema có 15 bảng (không phải 11 như đã ghi nhầm ở Bước 3):
users, workspaces, source_exams, import_jobs, passage_groups, tags,
question_items, options, question_tags, ai_solutions, exam_templates,
template_sections, exams, exam_versions, exam_items.
"""
import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON as _JSON
from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, Numeric,
    SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Enum as SAEnum

from app.db import Base


class QuestionStatus(str, enum.Enum):
    draft = "draft"
    parsed = "parsed"
    needs_answer = "needs_answer"
    ai_solving = "ai_solving"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    archived = "archived"


class AnswerSource(str, enum.Enum):
    red_text = "red_text"
    highlight = "highlight"
    bold_underline = "bold_underline"
    marker_star = "marker_star"
    answer_key_table = "answer_key_table"
    ai_solved = "ai_solved"
    teacher_manual = "teacher_manual"
    unknown = "unknown"


class Difficulty(str, enum.Enum):
    NB = "NB"
    TH = "TH"
    VD = "VD"
    VDC = "VDC"


def _uuid():
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")  # thêm ở EB-104 (migration 0002)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="teacher")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    school_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SourceExam(Base):
    __tablename__ = "source_exams"
    __table_args__ = (CheckConstraint("grade IN (10,11,12)", name="ck_source_exams_grade"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    exam_kind: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    school_year: Mapped[str | None] = mapped_column(Text)
    original_file_url: Mapped[str | None] = mapped_column(Text)
    raw_html: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ImportJob(Base):
    __tablename__ = "import_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_exams.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    stats: Mapped[dict] = mapped_column(JSONB().with_variant(_JSON(), 'sqlite'), nullable=False, default=dict)
    error_log: Mapped[list] = mapped_column(JSONB().with_variant(_JSON(), 'sqlite'), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PassageGroup(Base):
    __tablename__ = "passage_groups"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_exam_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_exams.id", ondelete="SET NULL"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    passage_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("kind", "code", name="uq_tags_kind_code"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tags.id"))


class QuestionItem(Base):
    __tablename__ = "question_items"
    __table_args__ = (
        CheckConstraint("difficulty_score BETWEEN 1 AND 10", name="ck_q_difficulty_score"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    source_exam_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_exams.id", ondelete="SET NULL"))
    passage_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("passage_groups.id", ondelete="SET NULL"))
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    order_in_source: Mapped[int | None] = mapped_column(Integer)
    stem_html: Mapped[str] = mapped_column(Text, nullable=False)
    stem_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QuestionStatus] = mapped_column(
        SAEnum(QuestionStatus, name="question_status"), nullable=False, default=QuestionStatus.draft)
    difficulty: Mapped[Difficulty | None] = mapped_column(SAEnum(Difficulty, name="difficulty_level"))
    difficulty_score: Mapped[int | None] = mapped_column(SmallInteger)
    correct_option_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("options.id", ondelete="SET NULL", use_alter=True, name="fk_q_correct_option"))
    answer_source: Mapped[AnswerSource] = mapped_column(
        SAEnum(AnswerSource, name="answer_source"), nullable=False, default=AnswerSource.unknown)
    answer_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    explanation_html: Mapped[str | None] = mapped_column(Text)
    dedup_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536))
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    options: Mapped[list["Option"]] = relationship(
        back_populates="question", cascade="all, delete-orphan",
        foreign_keys="Option.question_id")


class Option(Base):
    __tablename__ = "options"
    __table_args__ = (UniqueConstraint("question_id", "label", name="uq_options_q_label"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_items.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question: Mapped["QuestionItem"] = relationship(back_populates="options", foreign_keys=[question_id])


class QuestionTag(Base):
    __tablename__ = "question_tags"
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_items.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    is_ai_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AISolution(Base):
    __tablename__ = "ai_solutions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_items.id", ondelete="CASCADE"), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_option_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("options.id"))
    explanation_html: Mapped[str | None] = mapped_column(Text)
    suggested_tags: Mapped[list] = mapped_column(JSONB().with_variant(_JSON(), 'sqlite'), nullable=False, default=list)
    suggested_difficulty: Mapped[Difficulty | None] = mapped_column(
        SAEnum(Difficulty, name="difficulty_level", create_type=False))
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    raw_response: Mapped[dict | None] = mapped_column(JSONB().with_variant(_JSON(), 'sqlite'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExamTemplate(Base):
    __tablename__ = "exam_templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TemplateSection(Base):
    __tablename__ = "template_sections"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exam_templates.id", ondelete="CASCADE"), nullable=False)
    section_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    passage_type: Mapped[str | None] = mapped_column(Text)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty_mix: Mapped[dict] = mapped_column(JSONB().with_variant(_JSON(), 'sqlite'), nullable=False, default=dict)
    tag_filter: Mapped[dict] = mapped_column(JSONB().with_variant(_JSON(), 'sqlite'), nullable=False, default=dict)


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exam_templates.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExamVersion(Base):
    __tablename__ = "exam_versions"
    __table_args__ = (UniqueConstraint("exam_id", "code", name="uq_exam_versions_exam_code"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    answer_balance: Mapped[dict] = mapped_column(JSONB().with_variant(_JSON(), 'sqlite'), nullable=False, default=dict)


class ExamItem(Base):
    __tablename__ = "exam_items"
    __table_args__ = (UniqueConstraint("exam_version_id", "position", name="uq_exam_items_version_pos"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    exam_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exam_versions.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_items.id"), nullable=False)
    passage_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("passage_groups.id"))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    shuffled_correct_label: Mapped[str | None] = mapped_column(Text)
    snapshot_json: Mapped[dict] = mapped_column(JSONB().with_variant(_JSON(), 'sqlite'), nullable=False)
