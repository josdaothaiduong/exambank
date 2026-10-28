import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_owned_workspace
from app.models import SourceExam, User

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
