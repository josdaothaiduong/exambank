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
