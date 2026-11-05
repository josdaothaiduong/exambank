"""EB-102 — SQLAlchemy models khớp 100% schema ở Bước 1 (docs/01, mục 5).

Đếm lại chính xác: schema gốc có 15 bảng (không phải 11 như đã ghi nhầm ở Bước 3):
users, workspaces, source_exams, import_jobs, passage_groups, tags,
question_items, options, question_tags, ai_solutions, exam_templates,
template_sections, exams, exam_versions, exam_items.

Phần cuối file là ExamBank Learn Sprint 1 (S1-F1): +24 bảng (20 lõi theo
DB-API-SPEC + 4 phụ L4/L5 theo Addendum EL-007) = tổng 39 bảng.
"""
import enum
import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON as _JSON
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey,
    Index, Integer, JSON, Numeric, SmallInteger, String, Text,
    UniqueConstraint, func, text,
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


# =====================================================================
# ExamBank Learn — Sprint 1 foundation (S1-F1)
# Đặc tả nguồn: exambank-learn/specs/DB-API-SPEC.md mục 2 (20 bảng lõi)
# + plan/ADDENDUM-EL007-EXPANSION.md (4 bảng phụ L4/L5, tách section riêng
# ở cuối file). 15 bảng cũ ở trên KHÔNG đổi schema.
# Quy ước (spec mục 1.1): PK UUID, timestamptz UTC, JSONB variant sqlite,
# phân loại mở dùng Text + CheckConstraint, cột FSRS luôn tiền tố fsrs_.
# =====================================================================

def _jsonb():
    return JSONB().with_variant(_JSON(), 'sqlite')


# ---------- Nhóm A — Con người & tổ chức lớp (spec 2.1-2.6) ----------

class StudentProfile(Base):
    __tablename__ = "student_profiles"
    __table_args__ = (
        CheckConstraint("birth_year > 1900 AND birth_year <= 2100", name="ck_student_profiles_birth_year"),
        CheckConstraint("status IN ('pending_consent','active','disabled','graduated')",
                        name="ck_student_profiles_status"),
        Index("ix_student_profiles_workspace_status", "workspace_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    birth_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # chỉ năm sinh (NĐ 13/2023)
    school_class_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_consent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ParentProfile(Base):
    __tablename__ = "parent_profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(Text)  # SĐT của PH (người lớn), không thu SĐT của HS
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LearnClass(Base):
    __tablename__ = "classes"
    __table_args__ = (
        CheckConstraint("grade IN (10,11,12)", name="ck_classes_grade"),
        CheckConstraint("desired_retention BETWEEN 0.85 AND 0.95", name="ck_classes_desired_retention"),
        UniqueConstraint("workspace_id", "name", "school_year", name="uq_classes_ws_name_year"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    owner_teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    school_year: Mapped[str] = mapped_column(Text, nullable=False)
    join_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    desired_retention: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0.90)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ClassMembership(Base):
    __tablename__ = "class_memberships"
    __table_args__ = (
        CheckConstraint("source IN ('teacher_added','join_code')", name="ck_class_memberships_source"),
        Index("ix_class_memberships_student_left", "student_user_id", "left_at"),
    )
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True)
    student_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # rời lớp = đặt left_at, không xoá
    source: Mapped[str] = mapped_column(Text, nullable=False, default="teacher_added")


class ParentLink(Base):
    __tablename__ = "parent_links"
    __table_args__ = (
        CheckConstraint("relation IN ('father','mother','guardian','other')", name="ck_parent_links_relation"),
        CheckConstraint("status IN ('pending','active','revoked')", name="ck_parent_links_status"),
        CheckConstraint("status <> 'revoked' OR revoked_at IS NOT NULL", name="ck_parent_links_revoked_at"),
        UniqueConstraint("parent_user_id", "student_user_id", name="uq_parent_links_pair"),
        Index("ix_parent_links_parent_status", "parent_user_id", "status"),
        Index("ix_parent_links_student_status", "student_user_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    parent_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    student_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")  # chỉ active mới xem được dữ liệu HS
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        CheckConstraint("consent_type IN ('student_self','parent_guardian')", name="ck_consent_records_type"),
        CheckConstraint("method IN ('in_app','paper_form')", name="ck_consent_records_method"),
        Index("ix_consent_records_student_type", "student_user_id", "consent_type", "withdrawn_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    student_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    consenter_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))  # NULL khi paper_form chưa có TK PH
    consent_type: Mapped[str] = mapped_column(Text, nullable=False)  # đồng ý kép: student_self + parent_guardian
    consent_scope: Mapped[dict] = mapped_column(_jsonb(), nullable=False, default=dict)
    policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------- Nhóm B — Giao bài & làm bài (spec 2.7-2.9) ----------

class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint("(exam_version_id IS NOT NULL) <> (source_exam_id IS NOT NULL)",
                        name="ck_assignments_one_source"),
        CheckConstraint("assignment_kind IN ('regular','probe')", name="ck_assignments_kind"),
        CheckConstraint("mode IN ('online','paper_quick_entry')", name="ck_assignments_mode"),
        CheckConstraint("due_at > opens_at", name="ck_assignments_due_after_opens"),
        CheckConstraint("status IN ('draft','published','closed')", name="ck_assignments_status"),
        CheckConstraint("desired_retention_override IS NULL OR desired_retention_override BETWEEN 0.85 AND 0.95",
                        name="ck_assignments_retention_override"),
        Index("ix_assignments_class_status_due", "class_id", "status", "due_at"),
        Index("ix_assignments_workspace_status", "workspace_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    exam_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exam_versions.id"))
    source_exam_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_exams.id"))
    assignment_kind: Mapped[str] = mapped_column(Text, nullable=False, default="regular")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answer_release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # trái tim quy tắc R2
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    shuffle_options: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_score_immediately: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # spec 3.2 S3
    attempt_limit: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    desired_retention_override: Mapped[float | None] = mapped_column(Numeric(3, 2))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    student_snapshot_json: Mapped[dict | None] = mapped_column(_jsonb())  # bản chụp ĐÃ LỌC đáp án (R2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint("status IN ('in_progress','submitted','graded','expired')", name="ck_attempts_status"),
        CheckConstraint("entry_method IN ('online','quick_entry','teacher_entry')", name="ck_attempts_entry_method"),
        Index("ix_attempts_student_submitted", "student_user_id", "submitted_at"),
        Index("ix_attempts_assignment_status", "assignment_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)
    student_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="in_progress")
    entry_method: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score_raw: Mapped[float | None] = mapped_column(Numeric)  # chỉ server ghi khi chấm
    score_max: Mapped[float | None] = mapped_column(Numeric)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)  # idempotency
    shuffle_seed: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AttemptItem(Base):
    __tablename__ = "attempt_items"
    __table_args__ = (
        CheckConstraint("confidence_level IS NULL OR confidence_level IN (1,2,3)",
                        name="ck_attempt_items_confidence"),
        Index("ix_attempt_items_question_correct", "question_id", "is_correct"),
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_items.id"), primary_key=True)
    exam_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exam_items.id"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("variant_items.id"))
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("options.id"))  # NULL = bỏ trống, hợp lệ
    selected_variant_option_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("variant_options.id"))
    is_correct: Mapped[bool | None] = mapped_column(Boolean)  # chỉ server ghi; NULL = chưa chấm
    confidence_level: Mapped[int | None] = mapped_column(SmallInteger)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)
    marked_for_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ---------- Nhóm C — Học tập & spaced repetition (spec 2.10-2.17) ----------

_ATOM_STATUS_CK = "status IN ('pending_review','approved','rejected','archived')"
_PROVENANCE_CK = ("answer_provenance IN ('teacher_manual','answer_key_table','red_text',"
                  "'highlight','ai_inferred')")


class LearningAtom(Base):
    __tablename__ = "learning_atoms"
    __table_args__ = (
        CheckConstraint("atom_type IN ('vocab','collocation','phrasal_verb','grammar_point',"
                        "'reading_skill','distractor_trap','discourse','paraphrase')",
                        name="ck_learning_atoms_type"),
        CheckConstraint(_ATOM_STATUS_CK, name="ck_learning_atoms_status"),
        CheckConstraint("origin IN ('ai_generated','teacher_created','rule_based')",
                        name="ck_learning_atoms_origin"),
        CheckConstraint(_PROVENANCE_CK, name="ck_learning_atoms_provenance"),
        CheckConstraint("priority IN ('P1','P2','P3')", name="ck_learning_atoms_priority"),
        CheckConstraint("common_error_code IS NULL OR common_error_code IN "
                        "('LEX','COL','L1','GRA','ABS','LOG','SPD')", name="ck_learning_atoms_error_code"),
        CheckConstraint("cefr_level IS NULL OR cefr_level IN ('A2','B1','B2')",
                        name="ck_learning_atoms_cefr"),
        UniqueConstraint("workspace_id", "dedup_hash", name="uq_learning_atoms_ws_dedup"),
        Index("ix_learning_atoms_workspace_status", "workspace_id", "status"),
        Index("ix_learning_atoms_source_question", "source_question_id"),
        Index("ix_learning_atoms_ws_priority_status", "workspace_id", "priority", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    headword: Mapped[str] = mapped_column(Text, nullable=False)
    atom_type: Mapped[str] = mapped_column(Text, nullable=False)
    front_html: Mapped[str] = mapped_column(Text, nullable=False)  # mặt hỏi — không chứa đáp án (R2)
    front_text: Mapped[str] = mapped_column(Text, nullable=False)
    back_html: Mapped[str] = mapped_column(Text, nullable=False)
    back_text: Mapped[str] = mapped_column(Text, nullable=False)
    meaning_vi: Mapped[str] = mapped_column(Text, nullable=False)
    meaning_en: Mapped[str | None] = mapped_column(Text)
    pronunciation_ipa: Mapped[str | None] = mapped_column(Text)
    example_sentence: Mapped[str] = mapped_column(Text, nullable=False)
    source_sentence: Mapped[str | None] = mapped_column(Text)
    contrast_with: Mapped[list] = mapped_column(_jsonb(), nullable=False, default=list)  # UUID các atom dễ nhầm
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # giá trị nhóm logic, chưa tách bảng
    priority: Mapped[str] = mapped_column(Text, nullable=False, default="P2")
    common_error_code: Mapped[str | None] = mapped_column(Text)
    cefr_level: Mapped[str | None] = mapped_column(Text)
    source_question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_items.id"), nullable=False)
    source_passage_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("passage_groups.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_review")
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    answer_provenance: Mapped[str] = mapped_column(Text, nullable=False)
    ai_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))  # cổng 0.70 khi duyệt
    needs_teacher_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dedup_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AtomSource(Base):
    __tablename__ = "atom_sources"
    __table_args__ = (
        CheckConstraint("source_role IN ('correct_answer','distractor','passage_text','stem',"
                        "'paraphrase_target')", name="ck_atom_sources_role"),
        Index("ix_atom_sources_question", "question_id"),
    )
    atom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning_atoms.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_items.id", ondelete="CASCADE"), primary_key=True)
    source_exam_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_exams.id"))
    source_role: Mapped[str] = mapped_column(Text, nullable=False)


class AtomTag(Base):
    __tablename__ = "atom_tags"
    atom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning_atoms.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    is_ai_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class VariantItem(Base):
    __tablename__ = "variant_items"
    __table_args__ = (
        CheckConstraint("(parent_question_id IS NOT NULL) <> (parent_atom_id IS NOT NULL)",
                        name="ck_variant_items_one_parent"),
        CheckConstraint("variant_tier IN ('T0','T1','T2')", name="ck_variant_items_tier"),  # không có T3 ở MVP
        CheckConstraint(_ATOM_STATUS_CK, name="ck_variant_items_status"),
        CheckConstraint("origin IN ('ai_generated','teacher_created','rule_based')",
                        name="ck_variant_items_origin"),
        CheckConstraint(_PROVENANCE_CK, name="ck_variant_items_provenance"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    parent_question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("question_items.id"))
    parent_atom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("learning_atoms.id"))
    variant_tier: Mapped[str] = mapped_column(Text, nullable=False)
    stem_html: Mapped[str] = mapped_column(Text, nullable=False)
    stem_text: Mapped[str] = mapped_column(Text, nullable=False)
    correct_option_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("variant_options.id", ondelete="SET NULL", use_alter=True,
                   name="fk_variant_correct_option"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_review")
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    ai_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    answer_provenance: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VariantOption(Base):
    __tablename__ = "variant_options"
    __table_args__ = (UniqueConstraint("variant_id", "label", name="uq_variant_options_variant_label"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant_items.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class ReviewCard(Base):
    __tablename__ = "review_cards"
    __table_args__ = (
        CheckConstraint("first_result IS NULL OR first_result IN ('correct_confident','correct_unsure',"
                        "'correct_guessed','wrong','skipped')", name="ck_review_cards_first_result"),
        CheckConstraint("(created_from_attempt_id IS NULL AND created_from_question_id IS NULL) OR "
                        "(created_from_attempt_id IS NOT NULL AND created_from_question_id IS NOT NULL)",
                        name="ck_review_cards_created_from_pair"),
        UniqueConstraint("student_user_id", "atom_id", name="uq_review_cards_student_atom"),
        Index("ix_review_cards_student_due_active", "student_user_id", "due_at",
              postgresql_where=text("suspended_at IS NULL"),
              sqlite_where=text("suspended_at IS NULL")),
        Index("ix_review_cards_student_state_due", "student_user_id", "fsrs_state", "due_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    student_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    atom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning_atoms.id", ondelete="CASCADE"), nullable=False)
    fsrs_card_id: Mapped[int | None] = mapped_column(BigInteger)  # card_id nội bộ py-fsrs, không dùng làm PK
    fsrs_state: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)  # 1 Learning, 2 Review, 3 Relearning
    fsrs_step: Mapped[int | None] = mapped_column(SmallInteger)  # NULL khi Review
    stability: Mapped[float | None] = mapped_column(Float)  # ngày; NULL trước lần ôn đầu
    fsrs_difficulty: Mapped[float | None] = mapped_column(Float)  # thang 1-10 của FSRS, khác enum NB/TH/VD/VDC
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # >= 4 -> cờ leech báo GV
    first_result: Mapped[str | None] = mapped_column(Text)
    created_from_attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attempts.id"))
    created_from_question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("question_items.id"))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(Text)
    fsrs_params_version: Mapped[str] = mapped_column(Text, nullable=False, default="fsrs-default-v6")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReviewLog(Base):
    __tablename__ = "review_logs"  # append-only (quy tắc R3): sửa sai bằng bản ghi mới có corrects_log_id
    __table_args__ = (
        CheckConstraint("activity_type IN ('flashcard','contrast_card','cloze_variant','quiz_retry',"
                        "'dictation','paraphrase_match','sentence_build','error_spot','probe')",
                        name="ck_review_logs_activity_type"),
        CheckConstraint("rating BETWEEN 1 AND 4", name="ck_review_logs_rating"),  # 1 Again..4 Easy
        CheckConstraint("result IS NULL OR result IN ('correct','incorrect')", name="ck_review_logs_result"),
        CheckConstraint("variant_tier IS NULL OR variant_tier IN ('T0','T1','T2')",
                        name="ck_review_logs_variant_tier"),
        CheckConstraint("confidence_level IS NULL OR confidence_level IN (1,2,3)",
                        name="ck_review_logs_confidence"),
        CheckConstraint("device_kind IS NULL OR device_kind IN ('mobile','desktop','unknown')",
                        name="ck_review_logs_device_kind"),
        Index("ix_review_logs_student_reviewed", "student_user_id", "reviewed_at"),
        Index("ix_review_logs_card_reviewed", "review_card_id", "reviewed_at"),
        Index("ix_review_logs_atom", "atom_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    review_card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_cards.id"), nullable=False)
    student_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    atom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning_atoms.id"), nullable=False)
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("variant_items.id"))
    variant_tier: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    result: Mapped[str | None] = mapped_column(Text)
    is_probe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hint_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanation_viewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence_level: Mapped[int | None] = mapped_column(SmallInteger)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_due_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    position_in_session: Mapped[int | None] = mapped_column(SmallInteger)
    state_before: Mapped[dict] = mapped_column(_jsonb(), nullable=False)
    state_after: Mapped[dict] = mapped_column(_jsonb(), nullable=False)
    fsrs_params_version: Mapped[str] = mapped_column(Text, nullable=False, default="fsrs-default-v6")
    device_kind: Mapped[str | None] = mapped_column(Text)
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    corrects_log_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_logs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MasterySnapshot(Base):
    __tablename__ = "mastery_snapshots"
    __table_args__ = (
        UniqueConstraint("student_user_id", "tag_id", "period_start", name="uq_mastery_student_tag_period"),
        Index("ix_mastery_workspace_period", "workspace_id", "period_start"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    student_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)  # thứ Hai của tuần
    atoms_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    atoms_due: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    atoms_reviewed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    atoms_mature: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    probe_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # luôn lưu số thô
    probe_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retention_estimate: Mapped[float | None] = mapped_column(Numeric(4, 3))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------- Nhóm D — Báo cáo, vận hành, an toàn (spec 2.17-2.20) ----------

class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("kind IN ('assignment_new','review_due','weekly_report_ready','leech_alert',"
                        "'consent_request')", name="ck_notifications_kind"),
        Index("ix_notifications_user_read_sched", "user_id", "read_at", "scheduled_for"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(_jsonb(), nullable=False, default=dict)  # không chứa đáp án
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="in_app")  # MVP chỉ in_app
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"  # append-only như review_logs
    __table_args__ = (
        Index("ix_audit_logs_workspace_created", "workspace_id", "created_at"),
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # tên thuộc tính tránh 'metadata' (từ khoá dành riêng của DeclarativeBase); tên cột vẫn là metadata
    event_metadata: Mapped[dict] = mapped_column("metadata", _jsonb(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIGenerationJob(Base):
    __tablename__ = "ai_generation_jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('atom_extract','variant_gen','explain','solve')",
                        name="ck_ai_generation_jobs_kind"),
        CheckConstraint("status IN ('queued','running','succeeded','failed')",
                        name="ck_ai_generation_jobs_status"),
        Index("ix_ai_jobs_workspace_created", "workspace_id", "created_at"),
        Index("ix_ai_jobs_source_question_kind", "source_question_id", "kind"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("question_items.id"))
    source_atom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("learning_atoms.id"))
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd_estimate: Mapped[float | None] = mapped_column(Numeric(10, 6))  # mọi lần gọi AI đều ghi sổ
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    error_log: Mapped[list] = mapped_column(_jsonb(), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# =====================================================================
# Bảng phụ EL-007 — L4 Quản trị (Addendum EL-007 mục 2)
# Additive: gắn qua class_id / student_user_id có sẵn, 0 sửa bảng lõi L1.
# =====================================================================

class EnrollmentRequest(Base):
    """L4 — hàng chờ duyệt khi HS/PH tự đăng ký bằng join_code (mô hình lai M3)."""
    __tablename__ = "enrollment_requests"
    __table_args__ = (
        CheckConstraint("requester_role IN ('student','parent')", name="ck_enrollment_requests_role"),
        CheckConstraint("status IN ('pending','approved','rejected')", name="ck_enrollment_requests_status"),
        Index("ix_enrollment_requests_class_status", "class_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    requester_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    requester_role: Mapped[str] = mapped_column(Text, nullable=False, default="student")
    requester_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    requester_birth_year: Mapped[int | None] = mapped_column(SmallInteger)  # chỉ năm sinh như student_profiles
    join_code_used: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StudentAdminRecord(Base):
    """L4 — trạng thái quản trị của HS trong lớp (tạm dừng/ghi chú), không nhét vào bảng L1."""
    __tablename__ = "student_admin_records"
    __table_args__ = (
        CheckConstraint("admin_status IN ('active','paused')", name="ck_student_admin_records_status"),
        UniqueConstraint("class_id", "student_user_id", name="uq_student_admin_class_student"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    student_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    admin_status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    note: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# =====================================================================
# Bảng phụ EL-007 — L5 Tích hợp ngoài (Addendum EL-007 mục 1)
# Cache/log của lớp tích hợp: xoá đi tra lại được, không phải nguồn sự thật.
# =====================================================================

class LookupCache(Base):
    """L5 — cache tra cứu từ điển/nghĩa VN/từ liên quan (key chỉ ở server, cache trước gọi sau)."""
    __tablename__ = "lookup_cache"
    __table_args__ = (
        CheckConstraint("kind IN ('dictionary','vi_meaning','related')", name="ck_lookup_cache_kind"),
        CheckConstraint("source IN ('freedict','datamuse','gemini')", name="ck_lookup_cache_source"),
        UniqueConstraint("kind", "lookup_key", name="uq_lookup_cache_kind_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))  # NULL = dùng chung toàn hệ
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    lookup_key: Mapped[str] = mapped_column(Text, nullable=False)  # từ đã chuẩn hoá + mã ngữ cảnh
    payload_json: Mapped[dict] = mapped_column(_jsonb(), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_license: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ApiUsageLog(Base):
    """L5 — sổ gọi API ngoài có key/trả phí (hạn mức + đối soát chi phí)."""
    __tablename__ = "api_usage_logs"
    __table_args__ = (
        Index("ix_api_usage_workspace_created", "workspace_id", "created_at"),
        Index("ix_api_usage_provider_created", "provider", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_kind: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    class_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("classes.id"))
    units: Mapped[int | None] = mapped_column(Integer)
    est_cost: Mapped[float | None] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
