import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_owned_workspace
from app.models import Difficulty, Option, QuestionItem, QuestionStatus, QuestionTag, Tag, User

router = APIRouter(prefix="/api/v1/question-items", tags=["question-items"])


def _out(q: QuestionItem, db: Session) -> dict:
    options = (db.query(Option).filter_by(question_id=q.id)
               .order_by(Option.position).all())
    tag_codes = [t.code for t in db.query(Tag).join(
        QuestionTag, QuestionTag.tag_id == Tag.id).filter(
        QuestionTag.question_id == q.id).all()]
    return {
        "id": str(q.id), "workspace_id": str(q.workspace_id),
        "source_exam_id": str(q.source_exam_id) if q.source_exam_id else None,
        "passage_id": str(q.passage_id) if q.passage_id else None,
        "question_type": q.question_type,
        "stem_html": q.stem_html, "stem_text": q.stem_text,
        "status": q.status.value if hasattr(q.status, "value") else q.status,
        "difficulty": q.difficulty.value if q.difficulty and hasattr(q.difficulty, "value") else q.difficulty,
        "correct_option_id": str(q.correct_option_id) if q.correct_option_id else None,
        "answer_source": q.answer_source.value if hasattr(q.answer_source, "value") else q.answer_source,
        "answer_confidence": q.answer_confidence,
        "options": [{"id": str(o.id), "label": o.label, "content_text": o.content_text}
                    for o in options],
        "tags": sorted(tag_codes),
        "used_count": q.used_count,
    }


def _has_tag(session, *codes_or_like):
    """Điều kiện: câu có ít nhất 1 tag khớp (code bằng hoặc theo tiền tố)."""
    conds = []
    for kind, value in codes_or_like:
        if kind == "eq":
            conds.append(Tag.code == value)
        else:
            conds.append(Tag.code.like(value))
    subq = (session.query(QuestionItem.id)
            .join(QuestionTag, QuestionTag.question_id == QuestionItem.id)
            .join(Tag, Tag.id == QuestionTag.tag_id)
            .filter(or_(*conds)))
    return QuestionItem.id.in_(subq)


@router.get("")
def list_question_items(
    workspace_id: uuid.UUID = Query(...),
    status_filter: QuestionStatus | None = Query(default=None, alias="status"),
    grade: int | None = Query(default=None, ge=10, le=12),
    unit: str | None = Query(default=None, description="Mã Unit, VD: gs12_unit3"),
    question_type: str | None = Query(default=None),
    difficulty: Difficulty | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lọc 4 trục cùng lúc: Khối (qua tag) x Unit (tag) x Dạng bài x Độ khó + search + phân trang."""
    get_owned_workspace(workspace_id, db, user)
    q = db.query(QuestionItem).filter(QuestionItem.workspace_id == workspace_id)
    if status_filter is not None:
        q = q.filter(QuestionItem.status == status_filter)
    if question_type:
        q = q.filter(QuestionItem.question_type == question_type)
    if difficulty is not None:
        q = q.filter(QuestionItem.difficulty == difficulty)
    if unit:
        q = q.filter(_has_tag(db, ("eq", unit)))
    if grade is not None:
        # Khối được suy từ tag grade_{n} hoặc từ Unit gs{n}_unit* của chính khối đó
        q = q.filter(_has_tag(db, ("eq", f"grade_{grade}"), ("like", f"gs{grade}_unit%")))
    if search:
        q = q.filter(QuestionItem.stem_text.ilike(f"%{search}%"))
    total = q.count()
    rows = (q.order_by(QuestionItem.created_at)
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"items": [_out(r, db) for r in rows], "total": total,
            "page": page, "page_size": page_size}


@router.get("/{question_id}")
def get_question_item(question_id: uuid.UUID, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    q = db.get(QuestionItem, question_id)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy câu hỏi")
    get_owned_workspace(q.workspace_id, db, user)
    return _out(q, db)
