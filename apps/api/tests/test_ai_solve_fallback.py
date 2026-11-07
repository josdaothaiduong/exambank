"""Lớp dự phòng của solve-ai: khi hàng đợi nền (Celery/Redis) không gửi được
việc — delay() văng exception — endpoint giải ĐỒNG BỘ ngay trong request,
trả mode=sync kèm fallback=True + note tiếng Việt, thay vì 503 như trước.
Khi delay() gửi được bình thường thì vẫn trả mode=async và không giải đồng bộ.
"""
import types
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.worker as worker_module
from app.config import settings
from app.db import Base
from app.models import (
    AISolution, ImportJob, Option, PassageGroup, QuestionItem, QuestionTag,
    SourceExam, Tag, User, Workspace,
)
from app.routers.ai import solve_exam_ai
from app.routers.imports import PasteIn, import_paste
from app.routers.source_exams import SourceExamIn, create_source_exam
from app.seed import seed_taxonomy

TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__,
          ImportJob.__table__, AISolution.__table__]

HTML = """
<p>Question 1: She ______ here since 2010. A. has lived B. live C. lives D. living</p>
<p>Question 2: The museum ______ near the station in the old quarter. A. stands B. standing C. stand D. are stand</p>
<p>Question 3: This exercise is ______ than the previous one. A. more difficult B. difficult C. most difficult D. difficulty</p>
"""


@pytest.fixture()
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    ua = User(email="fb@x.edu", full_name="FB", password_hash="x", role="teacher")
    db.add(ua)
    db.flush()
    ws = Workspace(owner_id=ua.id, name="WS FB")
    db.add(ws)
    db.commit()
    exam = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Đề fallback", grade=12,
                                           exam_kind="quiz"), db=db, user=ua)
    exam_id = uuid.UUID(exam["id"])
    out = import_paste(exam_id, PasteIn(html=HTML), db=db, user=ua)
    assert out["stats"]["needs_answer"] == 3
    return {"db": db, "ua": ua, "exam_id": exam_id}


def test_fallback_to_sync_when_delay_raises(ctx, monkeypatch):
    """delay() văng lỗi (hàng đợi nền chết) -> 200, giải đồng bộ, fallback=True."""

    def _boom(ids):
        raise RuntimeError("broker unreachable (giả lập Redis chết)")

    fake_task = types.SimpleNamespace(delay=_boom)
    monkeypatch.setattr(worker_module, "ai_solve_batch", fake_task)
    monkeypatch.setattr(settings, "ai_async", True)

    res = solve_exam_ai(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    assert res["mode"] == "sync"
    assert res["fallback"] is True
    assert res["note"]  # có giải thích tiếng Việt cho giáo viên
    assert res["total"] == 3 and res["solved"] == 3 and res["failed"] == 0
    # Câu đã thật sự được giải trong cùng request
    assert ctx["db"].query(AISolution).count() == 3
    remaining = (ctx["db"].query(QuestionItem)
                 .filter(QuestionItem.status == "needs_answer").count())
    assert remaining == 0


def test_async_path_unchanged_when_delay_ok(ctx, monkeypatch):
    """delay() gửi được -> mode=async như cũ, KHÔNG giải đồng bộ, không fallback."""
    fake_task = types.SimpleNamespace(
        delay=lambda ids: types.SimpleNamespace(id="fake-task-123"))
    monkeypatch.setattr(worker_module, "ai_solve_batch", fake_task)
    monkeypatch.setattr(settings, "ai_async", True)

    res = solve_exam_ai(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    assert res["mode"] == "async"
    assert res["task_id"] == "fake-task-123"
    assert res["total"] == 3
    assert "fallback" not in res
    # Chưa câu nào được giải — việc nằm ở hàng đợi cho worker xử lý
    assert ctx["db"].query(AISolution).count() == 0
