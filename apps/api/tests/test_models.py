from app.db import Base
from app import models  # noqa: F401

EXPECTED = {
    "users", "workspaces", "source_exams", "import_jobs", "passage_groups",
    "tags", "question_items", "options", "question_tags", "ai_solutions",
    "exam_templates", "template_sections", "exams", "exam_versions", "exam_items",
}


def test_schema_has_exactly_15_tables():
    assert set(Base.metadata.tables.keys()) == EXPECTED


def test_question_status_lifecycle():
    assert models.QuestionStatus.approved.value == "approved"
    assert models.AnswerSource.red_text.value == "red_text"
