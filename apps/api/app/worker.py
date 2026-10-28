from celery import Celery

from app.config import settings

celery_app = Celery("exambank", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_routes = {
    "app.worker.parse_job": {"queue": "parse"},
    "app.worker.ai_solve_batch": {"queue": "ai"},
}


@celery_app.task(name="app.worker.parse_job")
def parse_job(import_job_id: str):
    # EB-202 (Tuần 2) sẽ cài parser thật ở đây.
    return {"import_job_id": import_job_id, "status": "not_implemented_yet"}


@celery_app.task(name="app.worker.ai_solve_batch")
def ai_solve_batch(question_ids: list[str]):
    # EB-303 (Tuần 3) sẽ cài AI solver thật ở đây.
    return {"count": len(question_ids), "status": "not_implemented_yet"}
