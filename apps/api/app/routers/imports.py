import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.pipeline import CONFIDENCE_GATE
from app.db import get_db
from app.deps import get_current_user, get_owned_workspace
from app.models import (
    AISolution, AnswerSource, Difficulty, ImportJob, Option, QuestionItem,
    QuestionStatus, QuestionTag, SourceExam, Tag, User,
)
from app.parsers.importer import docx_to_html, run_import
from app.parsers.option_repair import repair_glued_options
from app.routers.questions import _out as question_out

router = APIRouter(tags=["imports"])


def _owned_exam(db: Session, exam_id: uuid.UUID, user: User) -> SourceExam:
    exam = db.get(SourceExam, exam_id)
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đề gốc")
    get_owned_workspace(exam.workspace_id, db, user)
    return exam


def _latest_ai_solution(db: Session, question_id: uuid.UUID) -> AISolution | None:
    """ai_solution MỚI NHẤT của câu (None nếu câu chưa từng được AI giải)."""
    return (db.query(AISolution).filter_by(question_id=question_id)
            .order_by(AISolution.created_at.desc()).first())


def _solution_difficulty(sol: AISolution | None) -> str | None:
    """Độ khó AI đề xuất từ 1 ai_solution: ưu tiên cột difficulty (migration
    0005); bản ghi cũ chỉ có suggested_difficulty (enum) thì đọc bù từ đó."""
    if sol is None:
        return None
    return sol.difficulty or (
        sol.suggested_difficulty.value if sol.suggested_difficulty else None)


class PasteIn(BaseModel):
    mode: str = "paste_html"
    html: str
    # Xử lý trùng kiểu Windows: ask (dừng hỏi khi trùng >= 40%) | keep_old | overwrite | decide
    on_conflict: str = "ask"
    decisions: dict | None = None  # {dedup_hash: "overwrite"|"keep"} cho on_conflict="decide"


@router.post("/api/v1/source-exams/{exam_id}/import", status_code=status.HTTP_201_CREATED)
def import_paste(exam_id: uuid.UUID, body: PasteIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    exam = _owned_exam(db, exam_id, user)
    result = run_import(db, exam, body.html, created_by=user.id,
                        on_conflict=body.on_conflict, decisions=body.decisions)
    if result["status"] == "conflict":
        return JSONResponse(status_code=200, content=result)
    return {"import_job_id": result["job_id"], "status": "done", "stats": result["stats"],
            "error_log": result["error_log"],
            "near_duplicates": result.get("near_duplicates", [])}


@router.post("/api/v1/source-exams/{exam_id}/import-docx", status_code=status.HTTP_201_CREATED)
async def import_docx(exam_id: uuid.UUID, file: UploadFile = File(...),
                      on_conflict: str = Form("ask"), decisions_json: str | None = Form(None),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exam = _owned_exam(db, exam_id, user)
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Chỉ nhận file .docx")
    try:
        html = docx_to_html(await file.read())
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File .docx không đọc được")
    decisions = None
    if decisions_json:
        try:
            import json as _json
            decisions = _json.loads(decisions_json)
        except Exception:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "decisions_json không hợp lệ")
    result = run_import(db, exam, html, created_by=user.id,
                        on_conflict=on_conflict, decisions=decisions)
    if result["status"] == "conflict":
        return JSONResponse(status_code=200, content=result)
    return {"import_job_id": result["job_id"], "status": "done", "stats": result["stats"],
            "error_log": result["error_log"], "near_duplicates": result.get("near_duplicates", [])}


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
        # Dữ liệu cũ nạp trước khi parser xử lý được nhãn dính: tự lành tại chỗ
        # để GV thấy đủ 4 phương án và chọn được đáp án B/D.
        if repair_glued_options(db, r):
            db.commit()
        out = question_out(r, db)
        if r.passage_id:
            from app.models import PassageGroup
            p = db.get(PassageGroup, r.passage_id)
            out["passage_text"] = p.content_text if p else None
            out["passage_html"] = p.content_html if p else None
        # Đề xuất độ khó của AI: lấy từ ai_solution MỚI NHẤT của câu (bất kể
        # answer_source hiện tại là gì), null nếu câu chưa từng được AI giải
        # hoặc AI không đề xuất.
        sol = _latest_ai_solution(db, r.id)
        out["ai_difficulty"] = _solution_difficulty(sol)
        if r.answer_source == AnswerSource.ai_solved and sol:
            out["ai_solution"] = {
                "model": sol.model, "confidence": float(sol.confidence),
                "explanation_html": sol.explanation_html,
                "suggested_difficulty": sol.suggested_difficulty.value if sol.suggested_difficulty else None,
                "suggested_tags": sol.suggested_tags,
            }
        items.append(out)
    return {"items": items, "total": len(items)}


class ReviewIn(BaseModel):
    action: str  # approve | reject | edit_and_approve
    correct_label: str | None = None
    question_type: str | None = None
    difficulty: Difficulty | None = None
    explanation_html: str | None = None
    tag_codes: list[str] | None = None


def _apply_approve(db: Session, q: QuestionItem, user: User, *,
                   correct_label: str | None = None,
                   question_type: str | None = None,
                   difficulty: Difficulty | None = None,
                   explanation_html: str | None = None,
                   tag_codes: list[str] | None = None,
                   allow_low_confidence_ai: bool = False) -> None:
    """Lõi DUYỆT dùng chung cho duyệt đơn (review_question) và duyệt hàng loạt
    (approve_ready) — MỌI validate nằm ở đây để hai đường không bao giờ lệch
    nhau; vi phạm thì raise HTTPException như duyệt đơn. Không commit —
    bên gọi chịu trách nhiệm commit/rollback.

    `allow_low_confidence_ai`: NGOẠI LỆ duy nhất của cổng 0.70 — CHỈ
    approve_ready mới được truyền True, và chỉ khi giáo viên chủ động bật
    tuỳ chọn "chấp nhận đáp án AI tin cậy thấp" trong panel duyệt hàng loạt
    (yêu cầu của GV, 2026-11-07). Đường duyệt ĐƠN không bao giờ truyền
    tham số này nên cổng vẫn khoá cứng như cũ. Khi duyệt qua ngoại lệ,
    answer_source/confidence của câu giữ nguyên (dấu vết kiểm toán không đổi).
    """
    # Cổng EB-303: đáp án do AI đề xuất với confidence < 0.70 không được duyệt "mù" —
    # giáo viên phải tự tay chọn đáp án (correct_label) thì mới duyệt được.
    if (q.answer_source == AnswerSource.ai_solved
            and (q.answer_confidence or 0) < CONFIDENCE_GATE and not correct_label
            and not allow_low_confidence_ai):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "AI chưa chắc chắn về đáp án này (độ tin cậy < 70%). "
            "Hãy tự chọn đáp án đúng trước khi duyệt.")
    if correct_label:
        opt = db.query(Option).filter_by(question_id=q.id, label=correct_label).one_or_none()
        if opt is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "correct_label không khớp phương án nào")
        q.correct_option_id = opt.id
        q.answer_source = AnswerSource.teacher_manual
        q.answer_confidence = 1.0
    if not q.correct_option_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Không thể duyệt câu chưa có đáp án — hãy chọn đáp án trước")
    if question_type:
        q.question_type = question_type
    if difficulty:
        q.difficulty = difficulty
    if explanation_html is not None:
        q.explanation_html = explanation_html
    if tag_codes is not None:
        db.query(QuestionTag).filter_by(question_id=q.id).delete()
        for code in tag_codes:
            tag = db.query(Tag).filter_by(code=code).one_or_none()
            if tag:
                db.add(QuestionTag(question_id=q.id, tag_id=tag.id))
    q.status = QuestionStatus.approved
    q.reviewed_by = user.id
    q.reviewed_at = datetime.now(timezone.utc)
    db.flush()


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
        _apply_approve(db, q, user, correct_label=body.correct_label,
                       question_type=body.question_type, difficulty=body.difficulty,
                       explanation_html=body.explanation_html, tag_codes=body.tag_codes)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "action không hợp lệ")
    db.commit()
    db.refresh(q)
    return question_out(q, db)


# Nguồn đáp án "đáng tin cậy" cho duyệt hàng loạt: đáp án do hệ thống NHẬN DIỆN
# từ định dạng đề (tô đỏ/highlight/in đậm-gạch chân/dấu sao/bảng đáp án) hoặc do
# chính giáo viên chọn tay. Đáp án AI (ai_solved) KHÔNG nằm ở đây — nó chỉ được
# duyệt hàng loạt khi ai_solution mới nhất đạt cổng tin cậy 0.70 (xem dưới).
TRUSTED_ANSWER_SOURCES = frozenset({
    AnswerSource.red_text, AnswerSource.highlight, AnswerSource.bold_underline,
    AnswerSource.marker_star, AnswerSource.answer_key_table,
    AnswerSource.teacher_manual,
})


def _bulk_skip_reason(db: Session, q: QuestionItem, *,
                      accept_low_confidence_ai: bool = False) -> str | None:
    """None = câu đủ điều kiện duyệt hàng loạt; ngược lại trả lý do bỏ qua
    (tiếng Việt ngắn). Tiêu chí KHỚP cổng duyệt đơn: có đáp án đã đặt VÀ
    (nguồn nhận diện/giáo viên, HOẶC AI với confidence mới nhất >= 0.70).
    Câu AI confidence thấp chỉ lọt khi giáo viên chủ động bật
    `accept_low_confidence_ai` trong panel (mặc định tắt).
    """
    if not q.correct_option_id:
        return "Chưa có đáp án"
    if q.answer_source == AnswerSource.ai_solved:
        sol = _latest_ai_solution(db, q.id)
        conf = (float(sol.confidence) if sol is not None and sol.confidence is not None
                else (q.answer_confidence or 0))
        if conf < CONFIDENCE_GATE:
            if accept_low_confidence_ai:
                return None
            return (f"AI chưa chắc chắn (độ tin cậy {round(conf * 100)}% < 70%)"
                    " — hãy tự chọn đáp án rồi duyệt từng câu")
        return None
    if q.answer_source in TRUSTED_ANSWER_SOURCES:
        return None
    return "Chưa rõ nguồn đáp án — cần duyệt từng câu"


class ApproveReadyIn(BaseModel):
    unit_tag_id: str | None = None
    use_ai_difficulty: bool = False
    # Mặc định False: câu AI tin cậy < 70% bị bỏ qua. Chỉ khi giáo viên chủ
    # động bật trong panel duyệt hàng loạt (kèm câu chữ chịu trách nhiệm)
    # thì các câu đó mới được duyệt — thay cho việc click tay từng câu.
    accept_low_confidence_ai: bool = False


@router.post("/api/v1/source-exams/{exam_id}/approve-ready")
def approve_ready(exam_id: uuid.UUID, body: ApproveReadyIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Duyệt HÀNG LOẠT các câu ĐỦ TIN CẬY trong hàng chờ của đề.

    Server tự tính tập câu đủ điều kiện (client không gửi danh sách id):
    câu có đáp án đã đặt và nguồn thuộc nhóm nhận diện/giáo viên, hoặc đáp án
    AI với confidence của ai_solution mới nhất >= 0.70. Từng câu được duyệt
    bằng đúng lõi _apply_approve của duyệt đơn — không nới lỏng validate nào,
    NGOẠI TRỪ cổng 0.70 khi giáo viên bật accept_low_confidence_ai (xem
    _apply_approve). Câu không đủ điều kiện bị bỏ qua kèm lý do, không chặn cả mẻ.
    """
    exam = _owned_exam(db, exam_id, user)
    unit_tag: Tag | None = None
    if body.unit_tag_id:
        try:
            unit_tag_id = uuid.UUID(body.unit_tag_id)
        except (ValueError, AttributeError, TypeError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "unit_tag_id không hợp lệ")
        unit_tag = db.get(Tag, unit_tag_id)
        if unit_tag is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Không tìm thấy Unit đã chọn")
    rows = (db.query(QuestionItem).filter(
        QuestionItem.source_exam_id == exam.id,
        QuestionItem.status.in_([QuestionStatus.pending_review, QuestionStatus.needs_answer]))
        .order_by(QuestionItem.order_in_source).all())
    approved_ids: list[str] = []
    skipped: list[dict] = []
    for q in rows:
        reason = _bulk_skip_reason(
            db, q, accept_low_confidence_ai=body.accept_low_confidence_ai)
        if reason is not None:
            skipped.append({"question_id": str(q.id), "reason": reason})
            continue
        difficulty: Difficulty | None = None
        if body.use_ai_difficulty:
            diff_str = _solution_difficulty(_latest_ai_solution(db, q.id))
            if diff_str:
                try:
                    difficulty = Difficulty(diff_str)
                except ValueError:
                    difficulty = None
        try:
            # SAVEPOINT từng câu: 1 câu lỗi chỉ bị bỏ qua, không cuốn cả mẻ.
            with db.begin_nested():
                _apply_approve(db, q, user, difficulty=difficulty,
                               tag_codes=[unit_tag.code] if unit_tag else None,
                               allow_low_confidence_ai=body.accept_low_confidence_ai)
        except HTTPException as e:
            skipped.append({"question_id": str(q.id), "reason": str(e.detail)})
            continue
        approved_ids.append(str(q.id))
    db.commit()
    return {"approved_count": len(approved_ids), "approved_ids": approved_ids,
            "skipped": skipped}
