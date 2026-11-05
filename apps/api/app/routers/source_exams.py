import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_owned_workspace
from app.models import (
    Option, PassageGroup, QuestionItem, QuestionStatus, QuestionTag,
    SourceExam, Tag, User,
)

router = APIRouter(prefix="/api/v1/source-exams", tags=["source-exams"])


class SourceExamIn(BaseModel):
    workspace_id: uuid.UUID
    title: str = Field(min_length=1)
    grade: int | None = Field(default=None, ge=10, le=12)
    exam_kind: str | None = None  # 15min | 45min | mid_term | final | graduation | mock
    source_name: str | None = None
    school_year: str | None = None


def _out(e: SourceExam) -> dict:
    return {
        "id": str(e.id), "workspace_id": str(e.workspace_id), "title": e.title,
        "grade": e.grade, "exam_kind": e.exam_kind, "source_name": e.source_name,
        "school_year": e.school_year, "created_by": str(e.created_by),
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_source_exam(body: SourceExamIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    # Tạo vào workspace của người khác -> 404 qua chốt quyền EB-104
    get_owned_workspace(body.workspace_id, db, user)
    exam = SourceExam(
        workspace_id=body.workspace_id, title=body.title, grade=body.grade,
        exam_kind=body.exam_kind, source_name=body.source_name,
        school_year=body.school_year, created_by=user.id,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return _out(exam)


@router.get("")
def list_source_exams(workspace_id: uuid.UUID = Query(...), db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    get_owned_workspace(workspace_id, db, user)
    rows = (db.query(SourceExam).filter_by(workspace_id=workspace_id)
            .order_by(SourceExam.created_at).all())
    return [_out(e) for e in rows]


@router.get("/{exam_id}")
def get_source_exam(exam_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    exam = db.get(SourceExam, exam_id)
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đề gốc")
    get_owned_workspace(exam.workspace_id, db, user)  # 404 nếu không phải của mình
    return _out(exam)


@router.get("/{exam_id}/export-package")
def export_package(exam_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """EL-008 Deliverable 2 — Xuất gói đề (cầu nối một chiều ExamBank -> web học tập).

    Chỉ xuất câu approved VÀ có đáp án đúng (correct_option_id != null).
    Mọi câu còn lại đều được liệt kê minh bạch trong `skipped` kèm lý do,
    không lặng lẽ bỏ câu nào: len(questions) + len(skipped) == tổng số câu.
    - source_label: dùng `title` của đề gốc (SourceExam không có trường mô tả
      riêng; `source_name` là tên nguồn gốc file, không phải nhãn gói).
    - tags: dùng cột `code` của Tag (Tag có kind/code/label, không có slug).
    """
    exam = db.get(SourceExam, exam_id)
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đề gốc")
    get_owned_workspace(exam.workspace_id, db, user)  # 404 nếu không phải của mình

    rows = (db.query(QuestionItem)
            .filter(QuestionItem.source_exam_id == exam.id)
            .all())
    rows.sort(key=lambda q: (q.order_in_source is None, q.order_in_source or 0))

    questions: list[dict] = []
    skipped: list[dict] = []
    for q in rows:
        status_value = q.status.value if hasattr(q.status, "value") else q.status
        if status_value != QuestionStatus.approved.value:
            skipped.append({
                "external_id": str(q.id),
                "order": q.order_in_source,
                "reason": "not_approved",
            })
            continue
        if q.correct_option_id is None:
            skipped.append({
                "external_id": str(q.id),
                "order": q.order_in_source,
                "reason": "missing_correct_answer",
            })
            continue

        options = (db.query(Option).filter_by(question_id=q.id)
                   .order_by(Option.position).all())
        correct_label = None
        for o in options:
            if o.id == q.correct_option_id:
                correct_label = o.label
                break

        passage_text = None
        if q.passage_id:
            passage = db.get(PassageGroup, q.passage_id)
            if passage is not None:
                passage_text = passage.content_text

        tag_codes = [t.code for t in db.query(Tag).join(
            QuestionTag, QuestionTag.tag_id == Tag.id).filter(
            QuestionTag.question_id == q.id).all()]

        questions.append({
            "external_id": str(q.id),
            "order": q.order_in_source,
            "stem_html": q.stem_html,
            "stem_text": q.stem_text,
            "question_type": q.question_type,
            "passage_text": passage_text,
            "options": [{"label": o.label, "text": o.content_text} for o in options],
            "correct_label": correct_label,
            "answer_source": (q.answer_source.value
                              if hasattr(q.answer_source, "value") else q.answer_source),
            "confidence": float(q.answer_confidence) if q.answer_confidence is not None else None,
            "tags": sorted(tag_codes),
        })

    body = {
        "package_version": 1,
        "external_id": str(exam.id),
        "title": exam.title,
        "source_label": exam.title,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "questions": questions,
        "skipped": skipped,
    }
    return JSONResponse(
        content=body,
        headers={
            "Content-Disposition": f'attachment; filename="exam-package-{exam.id}.json"',
        },
    )
