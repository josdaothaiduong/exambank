from fastapi import Depends, FastAPI, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tag

app = FastAPI(title="ExamBank AI API", version="0.1.0")

# EB-106: web (localhost:3000) gọi API (localhost:8000) là cross-origin — thiếu CORS là web không gọi được API.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.config import settings as _settings  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import auth as auth_router  # noqa: E402
from app.routers import workspaces as workspaces_router  # noqa: E402

app.include_router(auth_router.router)
app.include_router(workspaces_router.router)

from app.routers import questions as questions_router  # noqa: E402
from app.routers import source_exams as source_exams_router  # noqa: E402

app.include_router(source_exams_router.router)
app.include_router(questions_router.router)

from app.routers import imports as imports_router  # noqa: E402

app.include_router(imports_router.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "exambank-api", "milestone": "EB-206"}


@app.get("/api/v1/tags")
def list_tags(
    kind: str | None = Query(default=None),
    grade: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """EB-103 acceptance: GET /tags?kind=unit&grade=12 -> đúng 10 Unit lớp 12."""
    q = db.query(Tag)
    if kind:
        q = q.filter(Tag.kind == kind)
    if grade is not None:
        # Unit Global Success mã hóa khối ngay trong code: gs{grade}_unit{n}
        q = q.filter(Tag.code.like(f"gs{grade}_unit%"))
    # Sắp theo độ dài code trước để unit10 đứng sau unit9 (không bị thứ tự chuỗi unit1, unit10, unit2...)
    tags = q.order_by(Tag.kind, func.length(Tag.code), Tag.code).all()
    return [
        {"id": str(t.id), "kind": t.kind, "code": t.code, "label": t.label,
         "parent_id": str(t.parent_id) if t.parent_id else None}
        for t in tags
    ]
