"""Xử lý trùng kiểu Windows Explorer (Ha yêu cầu 2026-10-29):
trùng >= 40% -> dừng, trả trích lục so sánh, KHÔNG nạp gì; giáo viên chọn
ghi đè tất cả / giữ cũ chỉ lấy phần mới / quyết định từng câu. Dưới 40% nạp thẳng."""
import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    ImportJob, Option, PassageGroup, QuestionItem, QuestionStatus, QuestionTag,
    SourceExam, Tag, User, Workspace,
)
from app.routers.imports import PasteIn, ReviewIn, import_paste, review_question
from app.routers.source_exams import SourceExamIn, create_source_exam
from app.seed import seed_taxonomy

TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__,
          ImportJob.__table__]

RED = '<span style="color:#ff0000">{}</span>'
PLAIN_Q = [
    ("She has lived here ______ 2010.", ["for", "since", "in", "at"], "B"),
    ("The room ______ every day.", ["cleans", "is cleaned", "cleaned", "cleaning"], "B"),
    ("He ______ to school by bus.", ["go", "goes", "going", "gone"], "B"),
    ("They ______ football on Sundays.", ["plays", "play", "playing", "played"], "B"),
]
NEW_Q = [
    ("I ______ my homework already.", ["have done", "do yesterday", "does", "doing"], "A"),
    ("This book is ______ than that one.", ["more interesting", "interestinger", "most interesting", "interest"], "A"),
]


def _html(questions, with_color):
    parts = []
    for i, (stem, opts, ans) in enumerate(questions, 1):
        rendered = []
        for o in opts:
            label = "ABCD"[opts.index(o)]
            rendered.append(f"{label}. " + (RED.format(o) if with_color and label == ans else o))
        parts.append(f"<p>Question {i}: {stem} " + " ".join(rendered) + "</p>")
    return "".join(parts)


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    ua = User(email="c@x.edu", full_name="C", password_hash="x", role="teacher")
    db.add(ua); db.flush()
    ws = Workspace(owner_id=ua.id, name="WS C")
    db.add(ws); db.commit()
    exam = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Đề gốc", grade=12,
                                           exam_kind="final"), db=db, user=ua)
    return {"db": db, "ua": ua, "ws": ws, "exam_id": uuid.UUID(exam["id"])}


def _count(ctx):
    return ctx["db"].query(QuestionItem).count()


def _paste(ctx, html, **kw):
    out = import_paste(ctx["exam_id"], PasteIn(html=html, **kw), db=ctx["db"], user=ctx["ua"])
    if hasattr(out, "body"):  # JSONResponse khi conflict
        return json.loads(out.body)
    return out


def test_setup_import_plain_no_answers(ctx):
    out = _paste(ctx, _html(PLAIN_Q, with_color=False))
    assert out["status"] == "done" and out["stats"]["needs_answer"] == 4
    assert _count(ctx) == 4


def test_conflict_at_100_percent_stops_and_imports_nothing(ctx):
    payload = _paste(ctx, _html(PLAIN_Q, with_color=True))  # cùng nội dung, lần này CÓ đáp án đỏ
    assert payload["status"] == "conflict"
    assert payload["overlap_ratio"] == 1.0 and payload["duplicate_count"] == 4 and payload["new_count"] == 0
    assert len(payload["duplicates"]) == 4
    d0 = payload["duplicates"][0]
    assert d0["existing"]["status"] == "needs_answer" and d0["existing"]["correct_label"] is None
    assert d0["new"]["detected_answer"]["label"] == "B"
    assert _count(ctx) == 4  # chưa nạp gì thêm


def test_overwrite_all_brings_answers(ctx):
    out = _paste(ctx, _html(PLAIN_Q, with_color=True), on_conflict="overwrite")
    assert out["status"] == "done" and out["stats"]["overwritten"] == 4
    assert _count(ctx) == 4
    q = ctx["db"].query(QuestionItem).first()
    assert q.correct_option_id is not None and q.status == QuestionStatus.pending_review


def test_overwrite_resets_approved_back_to_pending(ctx):
    q = ctx["db"].query(QuestionItem).first()
    review_question(q.id, ReviewIn(action="approve"), db=ctx["db"], user=ctx["ua"])
    assert ctx["db"].get(QuestionItem, q.id).status == QuestionStatus.approved
    _paste(ctx, _html(PLAIN_Q, with_color=True), on_conflict="overwrite")
    assert ctx["db"].get(QuestionItem, q.id).status == QuestionStatus.pending_review


def test_below_threshold_imports_directly_and_decide_per_item(ctx):
    # Đề mới: 2 câu trùng (đã có) + 2 câu mới -> trùng 50% vẫn phải hỏi trước
    mixed = _html(PLAIN_Q[:2] + NEW_Q, with_color=True)
    payload = _paste(ctx, mixed)
    assert payload["status"] == "conflict" and payload["duplicate_count"] == 2 and payload["new_count"] == 2
    hashes = {d["number"]: d["dedup_hash"] for d in payload["duplicates"]}
    # Chọn từng câu: câu 1 ghi đè, câu 2 giữ cũ (mặc định) -> quyết định chỉ ghi câu 1
    out = _paste(ctx, mixed, on_conflict="decide", decisions={hashes[1]: "overwrite"})
    assert out["status"] == "done"
    assert out["stats"]["overwritten"] == 1 and out["stats"]["duplicates"] == 1
    assert _count(ctx) == 6  # +2 câu mới
    # Đề chỉ trùng 1/4 = 25% < 40% -> nạp thẳng không hỏi
    small = _html([NEW_Q[0], ("Unique stem one ______.", ["aa", "bb", "cc", "dd"], "A"),
                   ("Unique stem two ______.", ["ee", "ff", "gg", "hh"], "A"),
                   ("Unique stem three ______.", ["ii", "jj", "kk", "ll"], "A")], with_color=True)
    out2 = _paste(ctx, small)
    assert out2["status"] == "done" and out2["stats"]["duplicates"] == 1
