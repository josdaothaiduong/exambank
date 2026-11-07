"""Hai tính năng màn Duyệt (đợt sau v4):

1. AI GIẢI LẠI (resolve-ai): chỉ giải lại câu answer_source == ai_solved chưa
   duyệt; ghi ai_solution MỚI + ghi đè đáp án demo bằng kết quả provider mới;
   KHÔNG đụng câu đã duyệt và câu có đáp án tô đỏ.
2. DUYỆT HÀNG LOẠT (approve-ready): server tự tính tập câu đủ tin cậy —
   duyệt câu red_text + câu AI conf >= 0.70; bỏ qua câu AI conf thấp (kèm
   lý do) và câu chưa có đáp án; use_ai_difficulty gán độ khó từ gợi ý AI;
   unit_tag_id không tồn tại -> 422.
"""
import re
import types
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.routers.ai as ai_router
import app.worker as worker_module
from app.ai.provider import validate_solution
from app.config import settings
from app.db import Base
from app.models import (
    AISolution, AnswerSource, Difficulty, ImportJob, Option, PassageGroup,
    QuestionItem, QuestionStatus, QuestionTag, SourceExam, Tag, User, Workspace,
)
from app.routers.ai import resolve_exam_ai, solve_exam_ai
from app.routers.imports import (
    ApproveReadyIn, PasteIn, ReviewIn, approve_ready, import_paste,
    review_question, review_queue,
)
from app.routers.source_exams import SourceExamIn, create_source_exam
from app.seed import seed_taxonomy

TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__,
          ImportJob.__table__, AISolution.__table__]

# 3 câu chưa đáp án + 1 câu đáp án tô đỏ (red_text) trong cùng 1 đề.
HTML = """
<p>Question 1: She ______ here since 2010. A. has lived B. live C. lives D. living</p>
<p>Question 2: The museum ______ near the station in the old quarter. A. stands B. standing C. stand D. are stand</p>
<p>Question 3: This exercise is ______ than the previous one. A. more difficult B. difficult C. most difficult D. difficulty</p>
<p>Question 4: He ______ in Ha Noi now. A. live B. <span style="color:#ff0000">lives</span> C. living D. lived</p>
"""


@pytest.fixture()
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    ua = User(email="rb@x.edu", full_name="RB", password_hash="x", role="teacher")
    db.add(ua)
    db.flush()
    ws = Workspace(owner_id=ua.id, name="WS RB")
    db.add(ws)
    db.commit()
    exam = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Đề resolve/bulk",
                                           grade=12, exam_kind="quiz"), db=db, user=ua)
    exam_id = uuid.UUID(exam["id"])
    out = import_paste(exam_id, PasteIn(html=HTML), db=db, user=ua)
    assert out["stats"]["needs_answer"] == 3 and out["stats"]["with_answer"] == 1
    return {"db": db, "ua": ua, "ws": ws, "exam_id": exam_id}


def _q(db, exam_id, stem_part: str) -> QuestionItem:
    return (db.query(QuestionItem)
            .filter(QuestionItem.source_exam_id == exam_id,
                    QuestionItem.stem_text.ilike(f"%{stem_part}%")).one())


def _correct_text(db, q: QuestionItem) -> str | None:
    if not q.correct_option_id:
        return None
    opt = db.get(Option, q.correct_option_id)
    return opt.content_text if opt else None


def _solutions(db, q: QuestionItem) -> list[AISolution]:
    return (db.query(AISolution).filter_by(question_id=q.id)
            .order_by(AISolution.created_at).all())


class _StubProvider:
    """Provider stub conf cao: chọn đáp án theo NỘI DUNG (khớp chính xác text
    phương án) nên tự kiểm chứng chéo (xáo trộn nhãn) vẫn nhất quán -> conf 0.99.
    Ánh xạ theo từ khoá trong thân câu: {từ khoá: text đáp án muốn chọn}.
    """

    name = "stub"
    model = "stub-high-conf"

    def __init__(self, picks: dict[str, str]):
        self.picks = picks

    def solve(self, *, system: str, user: str, valid_labels: set[str]) -> dict:
        options = {}
        for line in user.splitlines():
            m = re.match(r"^([A-D])\. (.*)$", line.strip())
            if m:
                options[m.group(1)] = m.group(2).strip()
        label = None
        for keyword, target in self.picks.items():
            if keyword in user:
                label = next((lb for lb, text in options.items() if text == target), None)
                if label:
                    break
        if label is None:
            label = sorted(options)[0]
        sol = {"answer_label": label, "explanation_vi": "Đáp án của provider stub.",
               "confidence": 0.95, "difficulty": "VD", "tags": []}
        return {"solution": validate_solution(sol, valid_labels),
                "raw": {"provider": "stub"},
                "usage": {"input_tokens": 10, "output_tokens": 5}}

    def cost_usd(self, usage: dict) -> float:
        return 0.0


# ---------------------------------------------------------------- resolve-ai

def test_resolve_overwrites_demo_answers_and_skips_red_and_approved(ctx, monkeypatch):
    db, ua, exam_id = ctx["db"], ctx["ua"], ctx["exam_id"]
    monkeypatch.setattr(settings, "ai_async", False)

    # Lượt 1: bộ giải demo giải 3 câu chưa đáp án (như trên máy Ha).
    res = solve_exam_ai(exam_id, db=db, user=ua)
    assert res["mode"] == "sync" and res["solved"] == 3
    assert db.query(AISolution).count() == 3

    q1 = _q(db, exam_id, "since 2010")
    q2 = _q(db, exam_id, "museum")
    q3 = _q(db, exam_id, "previous one")
    q4 = _q(db, exam_id, "Ha Noi")
    assert q4.answer_source == AnswerSource.red_text and not _solutions(db, q4)
    q4_option_before = q4.correct_option_id
    assert _correct_text(db, q3) == "more difficult"  # đáp án của demo

    # Giáo viên duyệt tay 1 câu AI (conf cao của demo) -> resolve không được đụng.
    out = review_question(q1.id, ReviewIn(action="approve"), db=db, user=ua)
    assert out["status"] == "approved"

    # Lượt 2: "cắm key thật" — stub conf cao, chọn đáp án KHÁC demo ở câu 3.
    stub = _StubProvider({"museum": "stands", "previous one": "difficult"})
    monkeypatch.setattr(ai_router, "get_provider", lambda _settings: stub)
    res2 = resolve_exam_ai(exam_id, db=db, user=ua)
    assert res2["mode"] == "sync" and res2["total"] == 2 and res2["solved"] == 2

    # Câu đã duyệt: nguyên trạng, không thêm ai_solution.
    db.expire_all()
    q1 = _q(db, exam_id, "since 2010")
    assert q1.status == QuestionStatus.approved and len(_solutions(db, q1)) == 1

    # Câu được giải lại: ai_solution MỚI của stub + đáp án bị ghi đè theo stub.
    q2 = _q(db, exam_id, "museum")
    q3 = _q(db, exam_id, "previous one")
    assert len(_solutions(db, q2)) == 2 and len(_solutions(db, q3)) == 2
    assert _solutions(db, q3)[-1].model == "stub-high-conf"
    assert _correct_text(db, q3) == "difficult"  # đã thay đáp án demo "more difficult"
    assert _correct_text(db, q2) == "stands"
    assert q3.answer_confidence >= 0.9 and q2.answer_confidence >= 0.9
    assert q3.status == QuestionStatus.pending_review

    # Câu tô đỏ: tuyệt đối không đụng — không solution, đáp án/nguồn/trạng thái nguyên.
    q4 = _q(db, exam_id, "Ha Noi")
    assert not _solutions(db, q4)
    assert q4.correct_option_id == q4_option_before
    assert q4.answer_source == AnswerSource.red_text
    assert q4.status == QuestionStatus.pending_review


def test_resolve_async_dispatch_shared_with_solve(ctx, monkeypatch):
    """resolve dùng chung cơ chế async: delay() OK -> mode=async, không giải đồng bộ."""
    db, ua, exam_id = ctx["db"], ctx["ua"], ctx["exam_id"]
    monkeypatch.setattr(settings, "ai_async", False)
    solve_exam_ai(exam_id, db=db, user=ua)
    assert db.query(AISolution).count() == 3

    seen = {}

    def _delay(ids):
        seen["ids"] = ids
        return types.SimpleNamespace(id="fake-task-1")

    monkeypatch.setattr(worker_module, "ai_solve_batch",
                        types.SimpleNamespace(delay=_delay))
    monkeypatch.setattr(settings, "ai_async", True)
    res = resolve_exam_ai(exam_id, db=db, user=ua)
    assert res["mode"] == "async" and res["task_id"] == "fake-task-1"
    assert res["total"] == 3 and len(seen["ids"]) == 3  # chỉ 3 câu ai_solved, không có câu tô đỏ
    assert db.query(AISolution).count() == 3  # chưa giải đồng bộ


# ------------------------------------------------------------- approve-ready

def _make_ai(db, q: QuestionItem, label: str, conf: float,
             difficulty: str | None = None) -> None:
    """Gắn cho câu một đáp án AI + ai_solution với confidence cho trước
    (mô phỏng trạng thái sau khi AI giải ở các mức tin cậy khác nhau)."""
    opt = db.query(Option).filter_by(question_id=q.id, label=label).one()
    q.correct_option_id = opt.id
    q.answer_source = AnswerSource.ai_solved
    q.answer_confidence = conf
    q.status = QuestionStatus.pending_review
    db.add(AISolution(
        question_id=q.id, model="stub", suggested_option_id=opt.id,
        explanation_html="<p>stub</p>", suggested_tags=[],
        difficulty=difficulty,
        suggested_difficulty=Difficulty(difficulty) if difficulty else None,
        confidence=conf, raw_response={}))
    db.commit()


def test_bulk_approve_only_trusted_questions(ctx):
    db, ua, exam_id = ctx["db"], ctx["ua"], ctx["exam_id"]
    q1 = _q(db, exam_id, "since 2010")      # giữ nguyên: chưa có đáp án
    q2 = _q(db, exam_id, "museum")          # AI conf 0.85 + gợi ý độ khó VD
    q3 = _q(db, exam_id, "previous one")    # AI conf 0.15 -> cổng chặn
    q4 = _q(db, exam_id, "Ha Noi")          # red_text
    _make_ai(db, q2, "A", 0.85, difficulty="VD")
    _make_ai(db, q3, "A", 0.15)
    unit = db.query(Tag).filter_by(kind="unit", code="gs12_unit1").one()

    res = approve_ready(exam_id, ApproveReadyIn(unit_tag_id=str(unit.id),
                                                use_ai_difficulty=True),
                        db=db, user=ua)
    assert res["approved_count"] == 2
    assert set(res["approved_ids"]) == {str(q2.id), str(q4.id)}
    skipped = {s["question_id"]: s["reason"] for s in res["skipped"]}
    assert set(skipped) == {str(q1.id), str(q3.id)}
    assert "Chưa có đáp án" in skipped[str(q1.id)]
    assert "độ tin cậy" in skipped[str(q3.id)]  # lý do cổng AI 0.70

    db.expire_all()
    q2 = _q(db, exam_id, "museum")
    q4 = _q(db, exam_id, "Ha Noi")
    assert q2.status == QuestionStatus.approved and q4.status == QuestionStatus.approved
    # use_ai_difficulty=True: độ khó lấy từ gợi ý của ai_solution mới nhất.
    assert q2.difficulty == Difficulty.VD
    # Unit chung được gán cho cả hai câu đã duyệt.
    for q in (q2, q4):
        codes = [t.code for t in db.query(Tag).join(
            QuestionTag, QuestionTag.tag_id == Tag.id).filter(
            QuestionTag.question_id == q.id).all()]
        assert "gs12_unit1" in codes
    # Hai câu bị bỏ qua vẫn nằm trong hàng chờ, nguyên trạng thái.
    queue = review_queue(exam_id, db=db, user=ua)
    assert queue["total"] == 2
    assert {i["id"] for i in queue["items"]} == {str(q1.id), str(q3.id)}


def test_bulk_approve_without_ai_difficulty_keeps_difficulty_empty(ctx):
    db, ua, exam_id = ctx["db"], ctx["ua"], ctx["exam_id"]
    q2 = _q(db, exam_id, "museum")
    _make_ai(db, q2, "A", 0.85, difficulty="VD")

    res = approve_ready(exam_id, ApproveReadyIn(use_ai_difficulty=False),
                        db=db, user=ua)
    assert str(q2.id) in res["approved_ids"]
    db.expire_all()
    q2 = _q(db, exam_id, "museum")
    assert q2.status == QuestionStatus.approved
    assert q2.difficulty is None  # không dùng gợi ý AI -> để trống như duyệt đơn


def test_bulk_approve_invalid_unit_tag_422(ctx):
    db, ua, exam_id = ctx["db"], ctx["ua"], ctx["exam_id"]
    with pytest.raises(HTTPException) as exc:
        approve_ready(exam_id, ApproveReadyIn(
            unit_tag_id="00000000-0000-0000-0000-000000000000"), db=db, user=ua)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc2:
        approve_ready(exam_id, ApproveReadyIn(unit_tag_id="khong-phai-uuid"),
                      db=db, user=ua)
    assert exc2.value.status_code == 422
    # Không câu nào bị duyệt khi unit sai.
    assert review_queue(exam_id, db=db, user=ua)["total"] == 4
