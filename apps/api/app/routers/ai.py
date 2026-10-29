import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.pipeline import solve_batch, solve_question
from app.ai.provider import get_provider
from app.config import settings
from app.db import get_db
from app.deps import get_current_user, get_owned_workspace
from app.models import QuestionItem, QuestionStatus, SourceExam, User
from app.routers.imports import _owned_exam

router = APIRouter(tags=["ai"])


@router.post("/api/v1/source-exams/{exam_id}/solve-ai")
def solve_exam_ai(exam_id: uuid.UUID, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Giải mọi câu needs_answer của đề bằng AI (đồng bộ ở dev; Celery khi AI_ASYNC=1)."""
    exam = _owned_exam(db, exam_id, user)
    questions = (db.query(QuestionItem)
                 .filter(QuestionItem.source_exam_id == exam.id,
                         QuestionItem.status == QuestionStatus.needs_answer)
                 .order_by(QuestionItem.order_in_source).all())
    if settings.ai_async:
        from app.worker import ai_solve_batch
        task = ai_solve_batch.delay([str(q.id) for q in questions])
        return {"mode": "async", "task_id": task.id, "total": len(questions),
                "provider": settings.ai_provider, "model": settings.ai_model or "demo-rule-solver"}
    provider = get_provider(settings)
    stats = solve_batch(db, questions, provider)
    stats.pop("results", None)
    return {"mode": "sync", "provider": provider.name, "model": provider.model, **stats}


@router.post("/api/v1/question-items/{question_id}/solve-ai")
def solve_one_ai(question_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    q = db.get(QuestionItem, question_id)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy câu hỏi")
    get_owned_workspace(q.workspace_id, db, user)
    if q.status != QuestionStatus.needs_answer:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Câu đang ở trạng thái {q.status.value}, chỉ giải câu needs_answer")
    provider = get_provider(settings)
    result = solve_question(db, q, provider)
    db.commit()
    return {"provider": provider.name, "model": provider.model, **result}
