import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_owned_workspace
from app.models import (
    AnswerSource, Difficulty, ImportJob, Option, QuestionItem, QuestionStatus,
    QuestionTag, SourceExam, Tag, User,
)
from app.parsers.importer import docx_to_html, import_html
from app.routers.questions import _out as question_out

router = APIRouter(tags=["imports"])


def _owned_exam(db: Session, exam_id: uuid.UUID, user: User) -> SourceExam:
    exam = db.get(SourceExam, exam_id)
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đề gốc")
    get_owned_workspace(exam.workspace_id, db, user)
    return exam


class PasteIn(BaseModel):
    mode: str = "paste_html"
    html: str


@router.post("/api/v1/source-exams/{exam_id}/import", status_code=status.HTTP_201_CREATED)
def import_paste(exam_id: uuid.UUID, body: PasteIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    exam = _owned_exam(db, exam_id, user)
    job = import_html(db, exam, body.html, created_by=user.id)
    return {"import_job_id": str(job.id), "status": job.status, "stats": job.stats,
            "error_log": job.error_log}


@router.post("/api/v1/source-exams/{exam_id}/import-docx", status_code=status.HTTP_201_CREATED)
async def import_docx(exam_id: uuid.UUID, file: UploadFile = File(...),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exam = _owned_exam(db, exam_id, user)
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Chỉ nhận file .docx")
    try:
        html = docx_to_html(await file.read())
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File .docx không đọc được")
    job = import_html(db, exam, html, created_by=user.id)
    return {"import_job_id": str(job.id), "status": job.status, "stats": job.stats,
            "error_log": job.error_log}


@router.get("/api/v1/import-jobs/{job_id}")
def get_import_job(job_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy import job")
    _owned_exam(db, job.source_exam_id, user)
    return {"id": str(job.id), "status": job.status, "stats": job.stats, "error_log": job.error_log}


@router.get("/api/v1/source-exams/{exam_id}/review-queue")
def review_queue(exam_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    exam = _owned_exam(db, exam_id, user)
    rows = (db.query(QuestionItem).filter(
        QuestionItem.source_exam_id == exam.id,
        QuestionItem.status.in_([QuestionStatus.pending_review, QuestionStatus.needs_answer]))
        .order_by(QuestionItem.order_in_source).all())
    items = []
    for r in rows:
        out = question_out(r, db)
        if r.passage_id:
            from app.models import PassageGroup
            p = db.get(PassageGroup, r.passage_id)
            out["passage_text"] = p.content_text if p else None
            out["passage_html"] = p.content_html if p else None
        items.append(out)
    return {"items": items, "total": len(items)}


class ReviewIn(BaseModel):
    action: str  # approve | reject | edit_and_approve
    correct_label: str | None = None
    question_type: str | None = None
    difficulty: Difficulty | None = None
    explanation_html: str | None = None
    tag_codes: list[str] | None = None


@router.patch("/api/v1/question-items/{question_id}/review")
def review_question(question_id: uuid.UUID, body: ReviewIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    q = db.get(QuestionItem, question_id)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy câu hỏi")
    get_owned_workspace(q.workspace_id, db, user)
    if q.status not in (QuestionStatus.pending_review, QuestionStatus.needs_answer):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Câu đang ở trạng thái {q.status.value}, không duyệt lại được")

    if body.action == "reject":
        q.status = QuestionStatus.rejected
    elif body.action in ("approve", "edit_and_approve"):
        if body.correct_label:
            opt = db.query(Option).filter_by(question_id=q.id, label=body.correct_label).one_or_none()
            if opt is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "correct_label không khớp phương án nào")
            q.correct_option_id = opt.id
            q.answer_source = AnswerSource.teacher_manual
            q.answer_confidence = 1.0
        if not q.correct_option_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Không thể duyệt câu chưa có đáp án — hãy chọn đáp án trước")
        if body.question_type:
            q.question_type = body.question_type
        if body.difficulty:
            q.difficulty = body.difficulty
        if body.explanation_html is not None:
            q.explanation_html = body.explanation_html
        if body.tag_codes is not None:
            db.query(QuestionTag).filter_by(question_id=q.id).delete()
            for code in body.tag_codes:
                tag = db.query(Tag).filter_by(code=code).one_or_none()
                if tag:
                    db.add(QuestionTag(question_id=q.id, tag_id=tag.id))
        q.status = QuestionStatus.approved
        q.reviewed_by = user.id
        q.reviewed_at = datetime.now(timezone.utc)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "action không hợp lệ")
    db.commit()
    db.refresh(q)
    return question_out(q, db)
