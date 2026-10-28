import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_owned_workspace
from app.models import User, Workspace

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1)
    school_name: str | None = None


def _out(ws: Workspace) -> dict:
    return {"id": str(ws.id), "name": ws.name, "school_name": ws.school_name,
            "owner_id": str(ws.owner_id)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_workspace(body: WorkspaceIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    ws = Workspace(owner_id=user.id, name=body.name, school_name=body.school_name)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return _out(ws)


@router.get("")
def list_workspaces(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Chỉ trả workspace của chính người dùng đang đăng nhập — không có ngoại lệ."""
    rows = db.query(Workspace).filter_by(owner_id=user.id).order_by(Workspace.created_at).all()
    return [_out(ws) for ws in rows]


@router.get("/{workspace_id}")
def get_workspace(workspace_id: uuid.UUID, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return _out(get_owned_workspace(workspace_id, db, user))
