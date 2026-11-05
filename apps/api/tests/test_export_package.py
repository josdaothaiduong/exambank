"""EL-008 Deliverable 2 — Xuất gói đề (GET /source-exams/{id}/export-package).

Mẫu fixture theo test_learn_sprint1.py: TestClient + sqlite + override get_db.
Bao phủ: chủ sở hữu xuất được + cấu trúc + correct_label + tags; phân loại
skipped (not_approved / missing_correct_answer); tổng questions+skipped =
tổng câu; user khác -> 404; đề không tồn tại -> 404; chưa đăng nhập -> 401.
"""
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    AnswerSource, Option, PassageGroup, QuestionItem, QuestionStatus,
    QuestionTag, SourceExam, Tag, User, Workspace,
)
from app.security import create_access_token, hash_password

TABLES = [t.__table__ for t in (
    User, Workspace, SourceExam, PassageGroup, Tag, QuestionItem, Option,
    QuestionTag)]


def _make_question(db, ws, exam, creator, *, order, status, correct_label=None,
                   answer_source=AnswerSource.red_text, confidence=None,
                   passage=None, tag_codes=()):
    q = QuestionItem(
        workspace_id=ws.id, source_exam_id=exam.id,
        passage_id=passage.id if passage else None,
        question_type="grammar_mc", order_in_source=order,
        stem_html=f"<p>Stem {order}</p>", stem_text=f"Stem {order}",
        status=status, answer_source=answer_source,
        answer_confidence=confidence,
        dedup_hash=f"export-pkg-{order}-{uuid.uuid4().hex[:8]}",
        created_by=creator.id)
    db.add(q)
    db.flush()
    opts = {}
    # Chèn không theo thứ tự position để khẳng định export sắp theo position.
    for label, pos in (("C", 2), ("A", 0), ("D", 3), ("B", 1)):
        o = Option(question_id=q.id, label=label,
                   content_html=f"opt {label} q{order}",
                   content_text=f"opt {label} q{order}", position=pos)
        db.add(o)
        opts[label] = o
    db.flush()
    if correct_label is not None:
        q.correct_option_id = opts[correct_label].id
    for code in tag_codes:
        tag = db.query(Tag).filter_by(code=code).one()
        db.add(QuestionTag(question_id=q.id, tag_id=tag.id))
    db.flush()
    return q, opts


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    Session = sessionmaker(bind=engine)
    db = Session()

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    client = TestClient(app)

    owner = User(email="owner@truong.edu", full_name="GV Chủ Đề",
                 password_hash=hash_password("owner-pass"), role="teacher")
    other = User(email="other@truong.edu", full_name="GV Khác",
                 password_hash=hash_password("other-pass"), role="teacher")
    db.add_all([owner, other])
    db.flush()
    ws = Workspace(owner_id=owner.id, name="WS Chủ Đề")
    ws_other = Workspace(owner_id=other.id, name="WS Khác")
    db.add_all([ws, ws_other])
    db.flush()

    db.add_all([
        Tag(kind="unit", code="gs10_unit1", label="GS10 Unit 1"),
        Tag(kind="skill", code="grammar", label="Ngữ pháp"),
    ])
    db.flush()

    exam = SourceExam(workspace_id=ws.id, title="DEMO ENG 10 — Unit 1",
                      grade=10, exam_kind="45min", created_by=owner.id)
    db.add(exam)
    db.flush()

    passage = PassageGroup(
        source_exam_id=exam.id, workspace_id=ws.id, passage_type="reading",
        title="Passage 1", content_html="<p>Passage text here</p>",
        content_text="Passage text here")
    db.add(passage)
    db.flush()

    # Câu 1 (order 2): approved, đáp án B, có tags, không đoạn văn.
    q1, opts1 = _make_question(
        db, ws, exam, owner, order=2, status=QuestionStatus.approved,
        correct_label="B", confidence=0.99,
        tag_codes=["gs10_unit1", "grammar"])
    # Câu 2 (order 1): approved, đáp án A, thuộc đoạn văn, confidence None.
    q2, opts2 = _make_question(
        db, ws, exam, owner, order=1, status=QuestionStatus.approved,
        correct_label="A", passage=passage, tag_codes=["gs10_unit1"])
    # Câu 3 (order 3): draft (đồng thời chưa có đáp án) -> not_approved.
    q3, _ = _make_question(
        db, ws, exam, owner, order=3, status=QuestionStatus.draft)
    # Câu 4 (order 4): needs_answer -> not_approved.
    q4, _ = _make_question(
        db, ws, exam, owner, order=4, status=QuestionStatus.needs_answer,
        answer_source=AnswerSource.unknown)
    # Câu 5 (order 5): approved nhưng thiếu đáp án -> missing_correct_answer.
    q5, _ = _make_question(
        db, ws, exam, owner, order=5, status=QuestionStatus.approved,
        answer_source=AnswerSource.unknown)
    db.commit()

    def tok(u):
        return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}

    out = {
        "client": client, "db": db, "owner": owner, "other": other,
        "exam": exam, "tok_owner": tok(owner), "tok_other": tok(other),
        "q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5,
        "q1_correct_id": str(opts1["B"].id),
        "q2_correct_id": str(opts2["A"].id),
    }
    yield out
    app.dependency_overrides.pop(get_db, None)


def _export(ctx, headers=None):
    return ctx["client"].get(
        f"/api/v1/source-exams/{ctx['exam'].id}/export-package",
        headers=headers if headers is not None else ctx["tok_owner"])


def test_owner_exports_package_structure(ctx):
    r = _export(ctx)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"] == (
        f'attachment; filename="exam-package-{ctx["exam"].id}.json"')

    body = r.json()
    assert body["package_version"] == 1
    assert body["external_id"] == str(ctx["exam"].id)
    assert body["title"] == "DEMO ENG 10 — Unit 1"
    assert body["source_label"] == "DEMO ENG 10 — Unit 1"
    # exported_at là ISO parse được và có timezone (UTC)
    exported_at = datetime.fromisoformat(body["exported_at"])
    assert exported_at.tzinfo is not None

    questions = body["questions"]
    # Thứ tự theo order_in_source tăng dần
    assert [q["order"] for q in questions] == [1, 2]

    by_id = {q["external_id"]: q for q in questions}
    q1 = by_id[str(ctx["q1"].id)]
    assert q1["stem_text"] == "Stem 2"
    assert q1["stem_html"] == "<p>Stem 2</p>"
    assert q1["question_type"] == "grammar_mc"
    assert q1["passage_text"] is None
    # options theo position A,B,C,D dù thứ tự chèn khác
    assert [o["label"] for o in q1["options"]] == ["A", "B", "C", "D"]
    assert q1["options"][1]["text"] == "opt B q2"
    # correct_label khớp đúng option mà correct_option_id trỏ tới
    db = ctx["db"]
    correct_opt = db.get(Option, uuid.UUID(ctx["q1_correct_id"]))
    assert q1["correct_label"] == correct_opt.label == "B"
    assert q1["answer_source"] == "red_text"
    assert q1["confidence"] == pytest.approx(0.99)
    assert q1["tags"] == ["grammar", "gs10_unit1"]

    q2 = by_id[str(ctx["q2"].id)]
    assert q2["passage_text"] == "Passage text here"
    assert q2["correct_label"] == "A"
    assert q2["confidence"] is None
    assert q2["tags"] == ["gs10_unit1"]


def test_skipped_reasons_and_total(ctx):
    body = _export(ctx).json()
    skipped = body["skipped"]
    assert [s["order"] for s in skipped] == [3, 4, 5]
    reasons = {s["external_id"]: s["reason"] for s in skipped}
    # draft vừa chưa approved vừa thiếu đáp án -> ưu tiên not_approved
    assert reasons[str(ctx["q3"].id)] == "not_approved"
    assert reasons[str(ctx["q4"].id)] == "not_approved"
    assert reasons[str(ctx["q5"].id)] == "missing_correct_answer"
    # Minh bạch: không lặng lẽ bỏ câu nào
    assert len(body["questions"]) + len(skipped) == 5


def test_other_user_gets_404(ctx):
    r = _export(ctx, headers=ctx["tok_other"])
    assert r.status_code == 404


def test_nonexistent_exam_gets_404(ctx):
    r = ctx["client"].get(
        f"/api/v1/source-exams/{uuid.uuid4()}/export-package",
        headers=ctx["tok_owner"])
    assert r.status_code == 404


def test_unauthenticated_gets_401(ctx):
    r = ctx["client"].get(
        f"/api/v1/source-exams/{ctx['exam'].id}/export-package")
    assert r.status_code == 401
