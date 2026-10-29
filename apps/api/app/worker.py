from celery import Celery

from app.config import settings

celery_app = Celery("exambank", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_routes = {
    "app.worker.parse_job": {"queue": "parse"},
    "app.worker.ai_solve_batch": {"queue": "ai"},
}


@celery_app.task(name="app.worker.parse_job")
def parse_job(import_job_id: str):
    # Luồng import chạy đồng bộ theo quyết định Tuần 2 (đủ nhanh với đề vài trăm câu);
    # task này giữ cho tương lai khi cần parse nền các file rất lớn.
    return {"import_job_id": import_job_id, "status": "not_implemented_yet"}


@celery_app.task(name="app.worker.ai_solve_batch")
def ai_solve_batch(question_ids: list[str]):
    """EB-303: chạy cùng pipeline với đường đồng bộ (app/ai/pipeline.py)."""
    import uuid as _uuid

    from app.ai.pipeline import solve_batch
    from app.ai.provider import get_provider
    from app.config import settings as _settings
    from app.db import SessionLocal
    from app.models import QuestionItem

    db = SessionLocal()
    try:
        questions = [db.get(QuestionItem, _uuid.UUID(qid)) for qid in question_ids]
        questions = [q for q in questions if q is not None]
        stats = solve_batch(db, questions, get_provider(_settings))
        stats.pop("results", None)
        return stats
    finally:
        db.close()
