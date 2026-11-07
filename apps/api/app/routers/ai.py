import logging
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
log = logging.getLogger(__name__)


@router.post("/api/v1/source-exams/{exam_id}/solve-ai")
def solve_exam_ai(exam_id: uuid.UUID, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Giải mọi câu needs_answer của đề bằng AI (đồng bộ ở dev; Celery khi AI_ASYNC=1).

    Lớp dự phòng cho bản dùng cá nhân trên 1 máy: nếu gửi việc vào hàng đợi
    nền thất bại (Redis/worker chưa sẵn sàng) thì giải ĐỒNG BỘ ngay trong
    request và báo rõ qua cờ fallback — chỉ khi đường đồng bộ cũng lỗi
    mới trả 503 như cũ.
    """
    exam = _owned_exam(db, exam_id, user)
    questions = (db.query(QuestionItem)
                 .filter(QuestionItem.source_exam_id == exam.id,
                         QuestionItem.status == QuestionStatus.needs_answer)
                 .order_by(QuestionItem.order_in_source).all())
    fallback = False
    if settings.ai_async:
        from app.worker import ai_solve_batch
        try:
            task = ai_solve_batch.delay([str(q.id) for q in questions])
        except Exception:
            # Ghi lại exception thật vào log máy chủ để chẩn đoán tận gốc
            # (trước đây except nuốt lỗi nên không biết vì sao delay() văng).
            log.exception("Không gửi được việc AI giải vào hàng đợi nền; "
                          "chuyển sang giải đồng bộ (fallback)")
            fallback = True
        else:
            return {"mode": "async", "task_id": task.id, "total": len(questions),
                    "provider": settings.ai_provider, "model": settings.ai_model or "demo-rule-solver"}
    provider = get_provider(settings)
    try:
        stats = solve_batch(db, questions, provider)
    except Exception:
        log.exception("Giải đồng bộ cũng thất bại")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Không gửi được việc cho AI giải — hàng đợi nền (Redis/worker) chưa sẵn sàng. "
            "Kiểm tra Docker Desktop rồi thử lại.")
    stats.pop("results", None)
    out = {"mode": "sync", "provider": provider.name, "model": provider.model, **stats}
    if fallback:
        out["fallback"] = True
        out["note"] = ("Hàng đợi nền chưa sẵn sàng nên hệ thống đã giải trực tiếp "
                       "ngay trong lần bấm này (kết quả vẫn đầy đủ).")
    return out


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
