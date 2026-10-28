"""EB-105 — Test gọi trực tiếp router functions (lớp JWT đã được EB-104 kiểm chứng riêng).

Kiểm: tạo/list đề gốc, lọc câu theo từng trục và kết hợp 4 trục, search, phân trang, cách ly.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Difficulty, Option, PassageGroup, QuestionItem, QuestionStatus, QuestionTag,
    SourceExam, Tag, User, Workspace,
)
from app.routers.questions import list_question_items
from app.routers.source_exams import SourceExamIn, create_source_exam, list_source_exams
from app.seed import seed_taxonomy

TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__]


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    ua = User(email="a@x.edu", full_name="A", password_hash="x", role="teacher")
    ub = User(email="b@x.edu", full_name="B", password_hash="x", role="teacher")
    db.add_all([ua, ub]); db.flush()
    wsa = Workspace(owner_id=ua.id, name="WS A")
    wsb = Workspace(owner_id=ub.id, name="WS B")
    db.add_all([wsa, wsb]); db.commit()
    return {"db": db, "ua": ua, "ub": ub, "wsa": wsa, "wsb": wsb}


def _add_question(db, ws, creator, stem, qtype, diff, tag_codes, status=QuestionStatus.approved):
    q = QuestionItem(workspace_id=ws.id, question_type=qtype, stem_html=stem, stem_text=stem,
                     status=status, difficulty=diff, dedup_hash=stem.lower(), created_by=creator.id)
    db.add(q); db.flush()
    for i, label in enumerate("ABCD"):
        db.add(Option(question_id=q.id, label=label, content_html=f"opt{label}", content_text=f"opt{label}", position=i))
    for code in tag_codes:
        tag = db.query(Tag).filter_by(code=code).one()
        db.add(QuestionTag(question_id=q.id, tag_id=tag.id))
    db.commit()
    return q


@pytest.fixture(scope="module")
def seeded(ctx):
    db, ws, ua = ctx["db"], ctx["wsa"], ctx["ua"]
    _add_question(db, ws, ua, "Grammar since question about environment", "grammar_mc",
                  Difficulty.TH, ["gs12_unit3"])
    _add_question(db, ws, ua, "Reading about green living", "reading_comprehension",
                  Difficulty.VD, ["gs12_unit3"])
    _add_question(db, ws, ua, "Vocabulary family life question", "vocabulary_mc",
                  Difficulty.NB, ["gs10_unit1"])
    _add_question(db, ws, ua, "Grammar pending question", "grammar_mc",
                  Difficulty.TH, ["gs12_unit3"], status=QuestionStatus.pending_review)
    return ctx


def _list(ctx, **kw):
    # Gọi trực tiếp function (bỏ qua FastAPI) nên phải truyền tường minh mọi tham số,
    # vì default của chúng là đối tượng Query(...) chứ không phải giá trị thật.
    base = dict(status_filter=None, grade=None, unit=None, question_type=None,
                difficulty=None, search=None, page=1, page_size=20,
                workspace_id=ctx["wsa"].id, user=ctx["ua"], db=ctx["db"])
    base.update(kw)
    return list_question_items(**base)


def test_source_exam_create_and_list(ctx):
    db, ua, ws = ctx["db"], ctx["ua"], ctx["wsa"]
    out = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Giữa kỳ 1", grade=12,
                                          exam_kind="mid_term"), db=db, user=ua)
    assert out["title"] == "Giữa kỳ 1" and out["grade"] == 12
    rows = list_source_exams(workspace_id=ws.id, db=db, user=ua)
    assert len(rows) == 1
    # Tạo đề vào workspace của người khác -> 404
    with pytest.raises(HTTPException) as e:
        create_source_exam(SourceExamIn(workspace_id=ctx["wsb"].id, title="Xâm nhập"), db=db, user=ua)
    assert e.value.status_code == 404


def test_filter_by_status_and_no_filter(seeded):
    assert _list(seeded)["total"] == 4
    r = _list(seeded, status_filter=QuestionStatus.approved)
    assert r["total"] == 3
    r = _list(seeded, status_filter=QuestionStatus.pending_review)
    assert r["total"] == 1


def test_filter_each_axis(seeded):
    assert _list(seeded, grade=12)["total"] == 3          # 3 câu gắn gs12_unit*
    assert _list(seeded, grade=10)["total"] == 1
    assert _list(seeded, unit="gs12_unit3")["total"] == 3
    assert _list(seeded, question_type="grammar_mc")["total"] == 2
    assert _list(seeded, difficulty=Difficulty.VD)["total"] == 1


def test_filter_combined_4_axes_and_search(seeded):
    r = _list(seeded, grade=12, unit="gs12_unit3", question_type="grammar_mc",
              difficulty=Difficulty.TH, status_filter=QuestionStatus.approved)
    assert r["total"] == 1 and "since" in r["items"][0]["stem_text"]
    assert r["items"][0]["tags"] == ["gs12_unit3"]
    assert len(r["items"][0]["options"]) == 4
    r = _list(seeded, search="green living")
    assert r["total"] == 1
    r = _list(seeded, search="khong-ton-tai")
    assert r["total"] == 0


def test_pagination(seeded):
    r1 = _list(seeded, page=1, page_size=3)
    r2 = _list(seeded, page=2, page_size=3)
    assert r1["total"] == 4 and len(r1["items"]) == 3 and len(r2["items"]) == 1
    assert r1["items"][0]["id"] != r2["items"][0]["id"]


def test_isolation_other_workspace_404(seeded):
    with pytest.raises(HTTPException) as e:
        _list(seeded, workspace_id=seeded["wsa"].id, user=seeded["ub"])
    assert e.value.status_code == 404
