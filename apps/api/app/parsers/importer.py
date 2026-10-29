"""EB-201→205 — Dịch vụ nhập đề: sanitize -> parse -> lưu DB + ImportJob stats.

Dùng chung 1 đường duy nhất cho cả paste HTML (EB-202) và upload docx (EB-204,
file .docx được docx_reader chuyển thành HTML trước khi vào đây) để kết quả không lệch nhau.
"""
from sqlalchemy.orm import Session

from app.models import (
    AnswerSource, ImportJob, Option, PassageGroup, QuestionItem, QuestionStatus, SourceExam,
)
from app.parsers.docx_reader import docx_to_html  # noqa: F401  (re-export cho router/test)
from app.parsers.dedup import dedup_hash
from app.parsers.parser import parse_exam_html
from app.parsers.sanitize import sanitize_html


def import_html(db: Session, exam: SourceExam, html: str, created_by) -> ImportJob:
    clean_html = sanitize_html(html)
    exam.raw_html = clean_html  # EB-201: luôn giữ bản gốc đã làm sạch để đối chiếu/debug parser

    job = ImportJob(source_exam_id=exam.id, status="parsing", stats={}, error_log=[])
    db.add(job)
    db.flush()

    parsed = parse_exam_html(clean_html)

    passage = None
    if parsed["passages"]:
        p = parsed["passages"][0]
        passage = PassageGroup(
            source_exam_id=exam.id, workspace_id=exam.workspace_id,
            passage_type=p["passage_type"], content_html=p.get("content_html") or p["content_text"],
            content_text=p["content_text"],
        )
        db.add(passage)
        db.flush()

    stats = {"total": 0, "with_answer": 0, "needs_answer": 0, "duplicates": 0, "failed": 0}
    errors = []
    existing_hashes = {
        h for (h,) in db.query(QuestionItem.dedup_hash)
        .filter(QuestionItem.workspace_id == exam.workspace_id).all()
    }
    for q in parsed["questions"]:
        stats["total"] += 1
        if not q["options"]:
            stats["failed"] += 1
            errors.append({"question": q["number"], "issue": "no_options_parsed"})
            continue
        h = dedup_hash(q["stem"], [o["text"] for o in q["options"]])
        if h in existing_hashes:
            stats["duplicates"] += 1
            continue
        existing_hashes.add(h)
        det = q["detected_answer"]
        item = QuestionItem(
            workspace_id=exam.workspace_id, source_exam_id=exam.id,
            passage_id=passage.id if passage else None,
            question_type=q["question_type"], order_in_source=q["number"],
            stem_html=q.get("stem_html") or q["stem"], stem_text=q["stem"],
            status=QuestionStatus.pending_review if det else QuestionStatus.needs_answer,
            answer_source=AnswerSource(det["source"]) if det else AnswerSource.unknown,
            answer_confidence=det["confidence"] if det else None,
            dedup_hash=h, created_by=created_by,
        )
        db.add(item)
        db.flush()
        correct_id = None
        for i, o in enumerate(q["options"]):
            opt = Option(question_id=item.id, label=o["label"],
                         content_html=o.get("html") or o["text"], content_text=o["text"], position=i)
            db.add(opt)
            db.flush()
            if det and o["label"] == det["label"]:
                correct_id = opt.id
        item.correct_option_id = correct_id
        if det:
            stats["with_answer"] += 1
        else:
            stats["needs_answer"] += 1

    job.stats = stats
    job.error_log = errors
    job.status = "done"
    db.commit()
    db.refresh(job)
    return job
