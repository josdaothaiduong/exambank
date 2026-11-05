from app.db import Base
from app import models  # noqa: F401

EXPECTED = {
    # 15 bảng ExamBank gốc (EB-102)
    "users", "workspaces", "source_exams", "import_jobs", "passage_groups",
    "tags", "question_items", "options", "question_tags", "ai_solutions",
    "exam_templates", "template_sections", "exams", "exam_versions", "exam_items",
    # 20 bảng lõi ExamBank Learn (S1-F1, DB-API-SPEC mục 2)
    "student_profiles", "parent_profiles", "classes", "class_memberships",
    "parent_links", "consent_records", "assignments", "attempts", "attempt_items",
    "learning_atoms", "atom_sources", "atom_tags", "variant_items", "variant_options",
    "review_cards", "review_logs", "mastery_snapshots", "notifications",
    "audit_logs", "ai_generation_jobs",
    # 4 bảng phụ EL-007 (L4 quản trị + L5 tích hợp)
    "enrollment_requests", "student_admin_records", "lookup_cache", "api_usage_logs",
    # 3 bảng Sprint 2 (EL-201/EL-204): nội dung hậu-đề + tiến độ + lượt làm biến thể
    "post_test_contents", "post_test_progress", "variant_attempts",
}


def test_schema_has_exactly_42_tables():
    assert set(Base.metadata.tables.keys()) == EXPECTED


def test_question_status_lifecycle():
    assert models.QuestionStatus.approved.value == "approved"
    assert models.AnswerSource.red_text.value == "red_text"
