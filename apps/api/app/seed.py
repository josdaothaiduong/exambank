"""EB-103 — Seed taxonomy, idempotent: chạy bao nhiêu lần cũng không tạo trùng.

Chạy:  python -m app.seed
Cơ chế: tra theo khóa duy nhất (kind, code) của bảng tags; có rồi thì cập nhật label/parent.
"""
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Tag
from app.taxonomy import build_tag_specs


def seed_taxonomy(db: Session) -> dict:
    specs = build_tag_specs()
    created, updated = 0, 0
    by_code = {}
    # Pass 1: tạo/cập nhật mọi tag (chưa gán parent)
    for spec in specs:
        tag = db.query(Tag).filter_by(kind=spec["kind"], code=spec["code"]).one_or_none()
        if tag is None:
            tag = Tag(kind=spec["kind"], code=spec["code"], label=spec["label"])
            db.add(tag)
            created += 1
        elif tag.label != spec["label"]:
            tag.label = spec["label"]
            updated += 1
        db.flush()
        by_code[spec["code"]] = tag
    # Pass 2: gán parent (Unit -> Grade)
    for spec in specs:
        if spec["parent_code"]:
            tag = by_code[spec["code"]]
            parent = by_code.get(spec["parent_code"]) or db.query(Tag).filter_by(code=spec["parent_code"]).one()
            if tag.parent_id != parent.id:
                tag.parent_id = parent.id
    db.commit()
    return {"total_specs": len(specs), "created": created, "updated": updated,
            "total_in_db": db.query(Tag).count()}


if __name__ == "__main__":
    with SessionLocal() as session:
        result = seed_taxonomy(session)
        tpl_result = seed_templates(session)
    print("Seed taxonomy:", result)
    print("Seed templates:", tpl_result)


# ---------------------------------------------------------------------------
# EB-401 — 3 template đề hệ thống (is_system=True), idempotent theo tên.
# difficulty_mix là TỈ LỆ theo từng phần; tag_filter để trống = toàn kho của workspace.
# ---------------------------------------------------------------------------
SYSTEM_TEMPLATES = [
    {
        "name": "Đề thi thử TN THPT — Tiếng Anh (50 câu)",
        "grade": 12, "total_questions": 50, "duration_minutes": 60,
        "sections": [
            ("Phát âm", "pronunciation", None, 2, {"NB": 0.5, "TH": 0.5}),
            ("Trọng âm", "stress", None, 2, {"NB": 0.5, "TH": 0.5}),
            ("Ngữ pháp", "grammar_mc", None, 8, {"NB": 0.25, "TH": 0.5, "VD": 0.25}),
            ("Từ vựng", "vocabulary_mc", None, 6, {"NB": 0.33, "TH": 0.34, "VD": 0.33}),
            ("Đồng nghĩa", "synonym", None, 2, {"TH": 0.5, "VD": 0.5}),
            ("Trái nghĩa", "antonym", None, 2, {"TH": 0.5, "VD": 0.5}),
            ("Điền khuyết đoạn văn", "cloze", "cloze", 5, {"NB": 0.2, "TH": 0.4, "VD": 0.4}),
            ("Đọc hiểu", "reading_comprehension", "reading", 13, {"NB": 0.23, "TH": 0.31, "VD": 0.31, "VDC": 0.15}),
            ("Sắp xếp câu", "sentence_arrangement", None, 5, {"TH": 0.6, "VD": 0.4}),
            ("Viết lại câu", "sentence_transformation", None, 3, {"TH": 0.67, "VD": 0.33}),
            ("Tìm lỗi sai", "error_identification", None, 2, {"TH": 0.5, "VD": 0.5}),
        ],
    },
    {
        "name": "Kiểm tra 45 phút — Tiếng Anh (40 câu)",
        "grade": None, "total_questions": 40, "duration_minutes": 45,
        "sections": [
            ("Phát âm", "pronunciation", None, 2, {"NB": 0.5, "TH": 0.5}),
            ("Trọng âm", "stress", None, 2, {"NB": 0.5, "TH": 0.5}),
            ("Ngữ pháp", "grammar_mc", None, 8, {"NB": 0.375, "TH": 0.375, "VD": 0.25}),
            ("Từ vựng", "vocabulary_mc", None, 8, {"NB": 0.375, "TH": 0.375, "VD": 0.25}),
            ("Đồng nghĩa", "synonym", None, 2, {"TH": 0.5, "VD": 0.5}),
            ("Trái nghĩa", "antonym", None, 2, {"TH": 0.5, "VD": 0.5}),
            ("Điền khuyết đoạn văn", "cloze", "cloze", 5, {"NB": 0.2, "TH": 0.6, "VD": 0.2}),
            ("Đọc hiểu", "reading_comprehension", "reading", 8, {"NB": 0.25, "TH": 0.375, "VD": 0.375}),
            ("Sắp xếp câu", "sentence_arrangement", None, 3, {"TH": 0.67, "VD": 0.33}),
        ],
    },
    {
        "name": "Kiểm tra 15 phút — Tiếng Anh (10 câu)",
        "grade": None, "total_questions": 10, "duration_minutes": 15,
        "sections": [
            ("Ngữ pháp", "grammar_mc", None, 5, {"NB": 0.4, "TH": 0.6}),
            ("Từ vựng", "vocabulary_mc", None, 5, {"NB": 0.4, "TH": 0.6}),
        ],
    },
]


def seed_templates(db: Session) -> dict:
    from app.models import ExamTemplate, TemplateSection
    created = 0
    for spec in SYSTEM_TEMPLATES:
        tpl = (db.query(ExamTemplate)
               .filter_by(name=spec["name"], is_system=True).one_or_none())
        if tpl is None:
            tpl = ExamTemplate(workspace_id=None, name=spec["name"], grade=spec["grade"],
                               total_questions=spec["total_questions"],
                               duration_minutes=spec["duration_minutes"], is_system=True)
            db.add(tpl); db.flush()
            for order, (name, qtype, ptype, count, mix) in enumerate(spec["sections"], 1):
                db.add(TemplateSection(template_id=tpl.id, section_order=order, name=name,
                                       question_type=qtype, passage_type=ptype,
                                       question_count=count, difficulty_mix=mix, tag_filter={}))
            created += 1
    db.commit()
    return {"created": created, "total_system": db.query(ExamTemplate).filter_by(is_system=True).count()}
