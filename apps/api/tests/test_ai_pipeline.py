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


def _html2(variant):
    """Nội dung riêng cho từng đề test (tránh chạm dedup + cổng trùng >=40%)."""
    return f"""
<p>Question 1: She ______ to school every day ({variant}). A. goes B. go C. going D. gone</p>
<p>Question 2: The museum ______ in the center of the city ({variant}). A. stands B. standing C. stand D. are stand</p>
<p>Question 3: This book is ______ than that one ({variant}). A. more interesting B. interesting C. most interesting D. interest</p>
"""


def _fresh_exam(ctx, title):
    """Đề mới với nội dung khác hẳn (tránh dedup theo hash trong cùng workspace)."""
    exam = create_source_exam(SourceExamIn(workspace_id=ctx["ws"].id, title=title,
                                           grade=12, exam_kind="quiz"),
                              db=ctx["db"], user=ctx["ua"])
    exam_id = uuid.UUID(exam["id"])
    out = import_paste(exam_id, PasteIn(html=_html2(title)), db=ctx["db"], user=ctx["ua"])
    assert out["stats"]["needs_answer"] == 3
    return exam_id


def test_review_queue_exposes_order_in_source(ctx):
    """Câu phải mang theo số thứ tự trong đề gốc để GV đối chiếu với bản giấy."""
    exam_id = _fresh_exam(ctx, "Đề kiểm tra số câu gốc")
    queue = review_queue(exam_id, db=ctx["db"], user=ctx["ua"])
    orders = sorted(i["order_in_source"] for i in queue["items"])
    assert orders == [1, 2, 3]


class _BadDifficultyProvider:
    """Provider stub: riêng câu 'museum' trả difficulty không hợp lệ -> lỗi lạ
    nằm NGOÀI ProviderError (ValueError khi ép kiểu Difficulty)."""
    name = "stub"
    model = "stub-1"

    def solve(self, system, user, valid_labels):
        difficulty = "SAI" if "museum" in user else "NB"
        return {"solution": {"answer_label": "A", "confidence": 0.9,
                             "explanation_vi": "stub", "difficulty": difficulty,
                             "tags": []},
                "usage": {"input_tokens": 1, "output_tokens": 1}, "raw": {}}

    def cost_usd(self, usage):
        return 0.0


def test_solve_batch_isolates_one_bad_question(ctx):
    """1 câu lỗi lạ không được làm sập cả mẻ: 2 câu còn lại vẫn giải xong,
    câu lỗi ở nguyên trạng thái needs_answer chờ xử lý lại."""
    from app.ai.pipeline import solve_batch
    db = ctx["db"]
    exam_id = _fresh_exam(ctx, "Đề cách ly lỗi")
    questions = (db.query(QuestionItem)
                 .filter(QuestionItem.source_exam_id == exam_id,
                         QuestionItem.status == QuestionStatus.needs_answer)
                 .order_by(QuestionItem.order_in_source).all())
    assert len(questions) == 3
    stats = solve_batch(db, questions, _BadDifficultyProvider())
    assert stats["total"] == 3 and stats["solved"] == 2 and stats["failed"] == 1
    db.expire_all()
    by_stem = {q.stem_text: q for q in db.query(QuestionItem)
               .filter(QuestionItem.source_exam_id == exam_id).all()}
    bad = next(q for s, q in by_stem.items() if "museum" in s)
    assert bad.status == QuestionStatus.needs_answer
    good = [q for s, q in by_stem.items() if "museum" not in s]
    assert all(q.status == QuestionStatus.pending_review for q in good)
