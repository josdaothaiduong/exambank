"""EB-305 — Kho 1000 câu: lọc đồng thời 4 trục phải đúng tập và nhanh (< 1 giây)."""
import time
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    AISolution, Difficulty, ImportJob, Option, PassageGroup, QuestionItem,
    QuestionStatus, QuestionTag, SourceExam, Tag, User, Workspace,
)
from app.routers.questions import list_question_items
from app.seed import seed_taxonomy

TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__,
          ImportJob.__table__, AISolution.__table__]


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    user = User(email="scale@x.edu", full_name="Scale", password_hash="x", role="teacher")
    db.add(user); db.flush()
    ws = Workspace(owner_id=user.id, name="WS 1000")
    db.add(ws); db.flush()
    exam = SourceExam(workspace_id=ws.id, created_by=user.id, title="Kho lớn", grade=12, exam_kind="bank")
    db.add(exam); db.flush()
    tags = {t.code: t for t in db.query(Tag).all()}
    types = ["grammar_mc", "vocabulary_mc", "cloze", "reading_comprehension"]
    diffs = list(Difficulty)
    units = ["gs10_unit1", "gs11_unit2", "gs12_unit3"]
    for i in range(1000):
        q = QuestionItem(workspace_id=ws.id, source_exam_id=exam.id, created_by=user.id,
                         order_in_source=i + 1, question_type=types[i % 4],
                         stem_text=f"Scale question {i} about topic number {i % 50}", stem_html=f"Scale question {i}",
                         difficulty=diffs[i % 4], status=QuestionStatus.approved,
                         dedup_hash=f"scale-{i}", answer_source="teacher_manual")
        db.add(q); db.flush()
        db.add_all([Option(question_id=q.id, label=l, position=j + 1,
                           content_text=f"Option {l} of {i}", content_html=f"Option {l}") for j, l in enumerate("ABCD")])
        db.add(QuestionTag(question_id=q.id, tag_id=tags[units[i % 3]].id))
    db.commit()
    return {"db": db, "user": user, "ws": ws}


def test_four_axis_filter_correct_and_fast(ctx):
    db, user, ws = ctx["db"], ctx["user"], ctx["ws"]
    # 1000 câu: unit gs12_unit3 là i%3==2 (333 câu); grammar i%4==0; NB i%4==0 -> giao nhau i%12==... đếm kỳ vọng bằng vòng lặp
    expected = sum(1 for i in range(1000) if i % 3 == 2 and i % 4 == 0)
    t0 = time.perf_counter()
    out = list_question_items(workspace_id=ws.id, status_filter=None, grade=None, unit="gs12_unit3",
                              question_type="grammar_mc", difficulty=Difficulty.NB, search=None,
                              page=1, page_size=100, db=db, user=user)
    elapsed = time.perf_counter() - t0
    assert out["total"] == expected
    assert elapsed < 1.0, f"Lọc 4 trục mất {elapsed:.2f}s"
    # Tìm kiếm từ khoá + phân trang
    t0 = time.perf_counter()
    out2 = list_question_items(workspace_id=ws.id, status_filter=None, grade=None, unit=None,
                               question_type=None, difficulty=None, search="topic number 7",
                               page=2, page_size=10, db=db, user=user)
    elapsed2 = time.perf_counter() - t0
    assert out2["total"] == 20 and len(out2["items"]) == 10 and elapsed2 < 1.0
