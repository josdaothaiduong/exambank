import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_owned_workspace
from app.examgen.export_docx import build_docx, _version_items
from app.examgen.export_html import build_print_html
from app.examgen.generator import GenerationError, generate_exam
from app.models import Exam, ExamItem, ExamTemplate, ExamVersion, TemplateSection, User

router = APIRouter(tags=["exams"])


def _template_out(db: Session, t: ExamTemplate) -> dict:
    sections = (db.query(TemplateSection).filter_by(template_id=t.id)
                .order_by(TemplateSection.section_order).all())
    return {"id": str(t.id), "name": t.name, "grade": t.grade,
            "total_questions": t.total_questions, "duration_minutes": t.duration_minutes,
            "is_system": t.is_system,
            "sections": [{"name": s.name, "question_type": s.question_type,
                          "passage_type": s.passage_type, "question_count": s.question_count,
                          "difficulty_mix": s.difficulty_mix} for s in sections]}


@router.get("/api/v1/exam-templates")
def list_templates(workspace_id: uuid.UUID | None = Query(default=None),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(ExamTemplate).filter(
        (ExamTemplate.is_system.is_(True)) | (ExamTemplate.workspace_id == workspace_id))
    return {"items": [_template_out(db, t) for t in q.order_by(ExamTemplate.name).all()]}


class GenerateIn(BaseModel):
    workspace_id: uuid.UUID
    template_id: uuid.UUID
    title: str | None = None
    n_versions: int = Field(default=4, ge=1, le=8)
    seed: int | None = None


def _exam_out(db: Session, exam: Exam, with_items: bool = False) -> dict:
    versions = (db.query(ExamVersion).filter_by(exam_id=exam.id)
                .order_by(ExamVersion.code).all())
    out = {"id": str(exam.id), "title": exam.title, "grade": exam.grade,
           "duration_minutes": exam.duration_minutes,
           "template_id": str(exam.template_id) if exam.template_id else None,
           "versions": []}
    for v in versions:
        vo = {"code": v.code, "answer_balance": v.answer_balance,
              "question_count": db.query(ExamItem).filter_by(exam_version_id=v.id).count()}
        if with_items:
            vo["items"] = _version_items(db, v)
        out["versions"].append(vo)
    return out


@router.post("/api/v1/exams/generate", status_code=status.HTTP_201_CREATED)
def generate(body: GenerateIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    get_owned_workspace(body.workspace_id, db, user)
    template = db.get(ExamTemplate, body.template_id)
    if template is None or (not template.is_system and template.workspace_id != body.workspace_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy template")
    title = body.title or template.name
    try:
        exam = generate_exam(db, workspace_id=body.workspace_id, template=template,
                             title=title, created_by=user.id,
                             n_versions=body.n_versions, seed=body.seed)
    except GenerationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"message": str(e), "shortfalls": e.shortfalls})
    return _exam_out(db, exam)


@router.get("/api/v1/exams")
def list_exams(workspace_id: uuid.UUID = Query(...), db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    get_owned_workspace(workspace_id, db, user)
    exams = (db.query(Exam).filter_by(workspace_id=workspace_id)
             .order_by(Exam.created_at.desc()).all())
    return {"items": [_exam_out(db, e) for e in exams]}


def _owned_exam(db: Session, exam_id: uuid.UUID, user: User) -> Exam:
    exam = db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đề")
    get_owned_workspace(exam.workspace_id, db, user)
    return exam


@router.get("/api/v1/exams/{exam_id}")
def exam_detail(exam_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return _exam_out(db, _owned_exam(db, exam_id, user), with_items=True)


@router.get("/api/v1/exams/{exam_id}/export/docx")
def export_docx(exam_id: uuid.UUID, kind: str = Query(default="student", pattern="^(student|teacher|matrix)$"),
                version: str | None = Query(default=None),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exam = _owned_exam(db, exam_id, user)
    data = build_docx(db, exam, kind=kind, version_code=version)
    fname = f"exambank_{kind}{('_' + version) if version else ''}.docx"
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/api/v1/exams/{exam_id}/versions/{code}/print", response_class=HTMLResponse)
def print_version(exam_id: uuid.UUID, code: str, teacher: bool = Query(default=False),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    exam = _owned_exam(db, exam_id, user)
    version = db.query(ExamVersion).filter_by(exam_id=exam.id, code=code).one_or_none()
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy mã đề")
    return build_print_html(db, exam, version, teacher)


# ---------------------------------------------------------------------------
# Mẫu đề TỰ CHẾ (post-MVP theo yêu cầu Ha 2026-10-29): giáo viên tạo mẫu riêng
# theo đúng hình dạng kho của mình. Mẫu hệ thống chỉ đọc; mẫu của workspace
# khác trả 404 (quy tắc cách ly dữ liệu như mọi nơi trong hệ thống).
# ---------------------------------------------------------------------------
from app.models import QuestionItem, QuestionStatus, Tag  # noqa: E402


class SectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    question_type: str
    question_count: int = Field(ge=1, le=100)
    with_passage: bool = False
    difficulty_mix: dict[str, float] = Field(default_factory=dict)


class TemplateIn(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    grade: int | None = Field(default=None, ge=10, le=12)
    duration_minutes: int = Field(ge=1, le=600)
    sections: list[SectionIn] = Field(min_length=1, max_length=20)


def _validate_sections(db: Session, sections: list[SectionIn]) -> list[dict]:
    valid_types = {t.code for t in db.query(Tag).filter_by(kind="question_type").all()}
    out = []
    for s in sections:
        if s.question_type not in valid_types:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Dạng bài không hợp lệ: {s.question_type}")
        mix = {}
        for k, v in (s.difficulty_mix or {}).items():
            if k not in ("NB", "TH", "VD", "VDC") or v < 0:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Tỉ lệ độ khó không hợp lệ: {k}={v}")
            if v > 0:
                mix[k] = float(v)
        total = sum(mix.values())
        if total > 0:
            mix = {k: round(v / total, 4) for k, v in mix.items()}
        out.append({"name": s.name, "question_type": s.question_type,
                    "question_count": s.question_count,
                    "passage_type": s.question_type if s.with_passage else None,
                    "difficulty_mix": mix})
    return out


def _apply_template(db: Session, tpl: ExamTemplate, body: TemplateIn, sections: list[dict]):
    tpl.name = body.name
    tpl.grade = body.grade
    tpl.duration_minutes = body.duration_minutes
    tpl.total_questions = sum(s["question_count"] for s in sections)
    db.query(TemplateSection).filter_by(template_id=tpl.id).delete()
    for order, s in enumerate(sections, 1):
        db.add(TemplateSection(template_id=tpl.id, section_order=order, name=s["name"],
                               question_type=s["question_type"],
                               passage_type=s["passage_type"],
                               question_count=s["question_count"],
                               difficulty_mix=s["difficulty_mix"], tag_filter={}))
    db.commit()
    db.refresh(tpl)


@router.get("/api/v1/exam-templates/availability")
def template_availability(workspace_id: uuid.UUID = Query(...),
                          db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    """Sức kho hiện tại cho việc dựng mẫu: số câu approved + có đáp án theo dạng bài,
    tách câu độc lập / câu gắn đoạn văn."""
    get_owned_workspace(workspace_id, db, user)
    from collections import Counter
    rows = (db.query(QuestionItem)
            .filter(QuestionItem.workspace_id == workspace_id,
                    QuestionItem.status == QuestionStatus.approved,
                    QuestionItem.correct_option_id.isnot(None)).all())
    agg: dict[str, dict] = {}
    for q in rows:
        a = agg.setdefault(q.question_type, {"question_type": q.question_type,
                                             "standalone": 0, "with_passage": 0, "total": 0})
        a["with_passage" if q.passage_id else "standalone"] += 1
        a["total"] += 1
    return {"items": sorted(agg.values(), key=lambda x: -x["total"])}


@router.post("/api/v1/exam-templates", status_code=status.HTTP_201_CREATED)
def create_template(body: TemplateIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    get_owned_workspace(body.workspace_id, db, user)
    sections = _validate_sections(db, body.sections)
    tpl = ExamTemplate(workspace_id=body.workspace_id, name=body.name, grade=body.grade,
                       total_questions=0, duration_minutes=body.duration_minutes,
                       is_system=False)
    db.add(tpl); db.flush()
    _apply_template(db, tpl, body, sections)
    return _template_out(db, tpl)


def _owned_custom_template(db: Session, template_id: uuid.UUID, user: User) -> ExamTemplate:
    tpl = db.get(ExamTemplate, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy mẫu đề")
    if tpl.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Mẫu hệ thống chỉ đọc, không sửa/xoá được")
    get_owned_workspace(tpl.workspace_id, db, user)  # workspace người khác -> 404
    return tpl


@router.put("/api/v1/exam-templates/{template_id}")
def update_template(template_id: uuid.UUID, body: TemplateIn,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tpl = _owned_custom_template(db, template_id, user)
    if body.workspace_id != tpl.workspace_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Không chuyển mẫu sang workspace khác được")
    sections = _validate_sections(db, body.sections)
    _apply_template(db, tpl, body, sections)
    return _template_out(db, tpl)


@router.delete("/api/v1/exam-templates/{template_id}")
def delete_template(template_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    tpl = _owned_custom_template(db, template_id, user)
    used = db.query(Exam).filter_by(template_id=tpl.id).count()
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Đã có {used} đề sinh từ mẫu này — không xoá được (hãy để lưu trữ)")
    db.query(TemplateSection).filter_by(template_id=tpl.id).delete()
    db.delete(tpl)
    db.commit()
    return {"deleted": True, "id": str(template_id)}
