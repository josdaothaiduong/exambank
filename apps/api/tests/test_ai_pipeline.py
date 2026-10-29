"""EB-301/302/303 — Pipeline AI: provider demo giải -> ai_solutions -> pending_review;
cổng confidence 0.70 chặn duyệt mù; giáo viên tự chọn đáp án thì duyệt được."""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    AISolution, ImportJob, Option, PassageGroup, QuestionItem, QuestionStatus,
    QuestionTag, SourceExam, Tag, User, Workspace,
)
from app.routers.ai import solve_exam_ai
from app.routers.imports import PasteIn, ReviewIn, import_paste, review_question, review_queue
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


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    ua = User(email="ai@x.edu", full_name="AI", password_hash="x", role="teacher")
    db.add(ua); db.flush()
    ws = Workspace(owner_id=ua.id, name="WS AI")
    db.add(ws); db.commit()
    exam = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Đề chờ AI", grade=12,
                                           exam_kind="quiz"), db=db, user=ua)
    exam_id = uuid.UUID(exam["id"])
    out = import_paste(exam_id, PasteIn(html=HTML), db=db, user=ua)
    assert out["stats"]["needs_answer"] == 3
    return {"db": db, "ua": ua, "ws": ws, "exam_id": exam_id}


def test_solve_batch_with_demo_provider(ctx):
    res = solve_exam_ai(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    assert res["mode"] == "sync" and res["provider"] == "demo"
    assert res["total"] == 3 and res["solved"] == 3 and res["failed"] == 0
    assert res["low_confidence"] == 1  # câu 2 không có quy tắc chắc chắn -> 0.40
    assert ctx["db"].query(AISolution).count() == 3
    queue = review_queue(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    assert queue["total"] == 3
    by_stem = {i["stem_text"]: i for i in queue["items"]}
    q1 = next(i for s, i in by_stem.items() if "since 2010" in s)
    assert q1["answer_source"] == "ai_solved" and q1["answer_confidence"] >= 0.70
    correct = [o for o in q1["options"] if o["id"] == q1["correct_option_id"]]
    assert correct and correct[0]["content_text"] == "has lived"
    assert q1["ai_solution"]["model"] == "demo-rule-solver"
    q3 = next(i for s, i in by_stem.items() if "than the previous" in s)
    correct3 = [o for o in q3["options"] if o["id"] == q3["correct_option_id"]]
    assert correct3 and correct3[0]["content_text"] == "more difficult"


def test_confidence_gate_blocks_blind_approve(ctx):
    queue = review_queue(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    low = next(i for i in queue["items"] if "museum" in i["stem_text"])
    assert low["answer_confidence"] < 0.70
    with pytest.raises(HTTPException) as exc:
        review_question(uuid.UUID(low["id"]), ReviewIn(action="approve"), db=ctx["db"], user=ctx["ua"])
    assert exc.value.status_code == 422
    # Giáo viên tự chọn đáp án -> duyệt được, nguồn thành teacher_manual
    out = review_question(uuid.UUID(low["id"]), ReviewIn(action="approve", correct_label="A"),
                          db=ctx["db"], user=ctx["ua"])
    assert out["status"] == "approved" and out["answer_source"] == "teacher_manual"


def test_high_confidence_approve_without_label_ok(ctx):
    queue = review_queue(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    rest = [i for i in queue["items"] if "museum" not in i["stem_text"]]
    assert rest and all(i["answer_confidence"] >= 0.70 for i in rest)
    out = review_question(uuid.UUID(rest[0]["id"]), ReviewIn(action="approve"), db=ctx["db"], user=ctx["ua"])
    assert out["status"] == "approved" and out["answer_source"] == "ai_solved"
