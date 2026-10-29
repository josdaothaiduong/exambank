"""Mẫu đề tự chế (post-MVP): tạo/sửa/xoá + quyền sở hữu + validate + sinh đề từ mẫu tự chế
+ availability phản ánh đúng sức kho."""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    AISolution, Exam, ExamItem, ExamTemplate, ExamVersion, ImportJob, Option,
    PassageGroup, QuestionItem, QuestionStatus, QuestionTag, SourceExam, Tag,
    TemplateSection, User, Workspace,
)
from app.routers.exams import (
    GenerateIn, SectionIn, TemplateIn, create_template, delete_template, generate,
    template_availability, update_template,
)
from app.seed import seed_taxonomy, seed_templates

TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__,
          ImportJob.__table__, AISolution.__table__, ExamTemplate.__table__,
          TemplateSection.__table__, Exam.__table__, ExamVersion.__table__, ExamItem.__table__]


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    seed_templates(db)
    ua = User(email="ct@x.edu", full_name="CT", password_hash="x", role="teacher")
    ub = User(email="ct2@x.edu", full_name="CT2", password_hash="x", role="teacher")
    db.add_all([ua, ub]); db.flush()
    ws = Workspace(owner_id=ua.id, name="WS CT")
    ws2 = Workspace(owner_id=ub.id, name="WS CT2")
    db.add_all([ws, ws2]); db.flush()
    src = SourceExam(workspace_id=ws.id, created_by=ua.id, title="Nguồn", grade=12, exam_kind="bank")
    db.add(src); db.flush()
    # Kho nhỏ: 6 câu ngữ pháp độc lập đã duyệt + 1 đoạn cloze 5 câu
    for i in range(6):
        q = QuestionItem(workspace_id=ws.id, source_exam_id=src.id, created_by=ua.id,
                         order_in_source=i + 1, question_type="grammar_mc",
                         stem_text=f"Grammar {i} ______.", stem_html=f"Grammar {i} ______.",
                         difficulty="TH", status=QuestionStatus.approved,
                         dedup_hash=f"ct-g{i}", answer_source="teacher_manual")
        db.add(q); db.flush()
        opts = []
        for j, l in enumerate("ABCD"):
            o = Option(question_id=q.id, label=l, position=j + 1,
                       content_text=f"opt {l} {i}", content_html=f"opt {l} {i}")
            db.add(o); opts.append(o)
        db.flush()
        q.correct_option_id = opts[0].id
    pg = PassageGroup(source_exam_id=src.id, workspace_id=ws.id, passage_type="cloze",
                      content_text="Đoạn cloze.", content_html="<p>Đoạn cloze.</p>")
    db.add(pg); db.flush()
    for i in range(5):
        q = QuestionItem(workspace_id=ws.id, source_exam_id=src.id, created_by=ua.id,
                         order_in_source=10 + i, question_type="cloze",
                         stem_text=f"Chỗ trống số {i + 1}", stem_html=f"Chỗ trống số {i + 1}",
                         difficulty="TH", status=QuestionStatus.approved,
                         dedup_hash=f"ct-c{i}", answer_source="teacher_manual", passage_id=pg.id)
        db.add(q); db.flush()
        opts = []
        for j, l in enumerate("ABCD"):
            o = Option(question_id=q.id, label=l, position=j + 1,
                       content_text=f"copt {l} {i}", content_html=f"copt {l} {i}")
            db.add(o); opts.append(o)
        db.flush()
        q.correct_option_id = opts[1].id
    db.commit()
    return {"db": db, "ua": ua, "ub": ub, "ws": ws, "ws2": ws2}


def _body(ws_id, **kw):
    base = dict(workspace_id=ws_id, name="Mẫu của tôi", grade=12, duration_minutes=20,
                sections=[SectionIn(name="Ngữ pháp", question_type="grammar_mc", question_count=4),
                          SectionIn(name="Điền khuyết", question_type="cloze", question_count=5,
                                    with_passage=True)])
    base.update(kw)
    return TemplateIn(**base)


def test_create_and_availability(ctx):
    db = ctx["db"]
    out = create_template(_body(ctx["ws"].id), db=db, user=ctx["ua"])
    assert out["is_system"] is False and out["total_questions"] == 9
    assert [s["question_count"] for s in out["sections"]] == [4, 5]
    av = template_availability(workspace_id=ctx["ws"].id, db=db, user=ctx["ua"])
    by_type = {a["question_type"]: a for a in av["items"]}
    assert by_type["grammar_mc"] == {"question_type": "grammar_mc", "standalone": 6, "with_passage": 0, "total": 6}
    assert by_type["cloze"]["with_passage"] == 5
    ctx["tpl_id"] = uuid.UUID(out["id"])


def test_generate_from_custom_template(ctx):
    res = generate(GenerateIn(workspace_id=ctx["ws"].id, template_id=ctx["tpl_id"],
                              n_versions=2, seed=3),
                   db=ctx["db"], user=ctx["ua"])
    assert res["versions"][0]["question_count"] == 9


def test_update_and_validation(ctx):
    db = ctx["db"]
    out = update_template(ctx["tpl_id"],
                          _body(ctx["ws"].id, name="Mẫu đã sửa",
                                sections=[SectionIn(name="Ngữ pháp", question_type="grammar_mc",
                                                    question_count=6)]),
                          db=db, user=ctx["ua"])
    assert out["name"] == "Mẫu đã sửa" and out["total_questions"] == 6
    with pytest.raises(HTTPException) as e1:
        create_template(_body(ctx["ws"].id,
                              sections=[SectionIn(name="X", question_type="khong_ton_tai", question_count=1)]),
                        db=db, user=ctx["ua"])
    assert e1.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        create_template(_body(ctx["ws"].id,
                              sections=[SectionIn(name="X", question_type="grammar_mc", question_count=1,
                                                  difficulty_mix={"SAI": 0.5})]),
                        db=db, user=ctx["ua"])
    assert e2.value.status_code == 422


def test_permissions(ctx):
    db = ctx["db"]
    # Người khác sửa -> 404 (cách ly dữ liệu)
    with pytest.raises(HTTPException) as e1:
        update_template(ctx["tpl_id"], _body(ctx["ws"].id), db=db, user=ctx["ub"])
    assert e1.value.status_code == 404
    # Mẫu hệ thống -> 403
    sys_tpl = db.query(ExamTemplate).filter_by(is_system=True).first()
    with pytest.raises(HTTPException) as e2:
        delete_template(sys_tpl.id, db=db, user=ctx["ua"])
    assert e2.value.status_code == 403
    # Mẫu đã có đề sinh ra -> 409 không xoá được
    with pytest.raises(HTTPException) as e3:
        delete_template(ctx["tpl_id"], db=db, user=ctx["ua"])
    assert e3.value.status_code == 409


def test_delete_unused_template(ctx):
    db = ctx["db"]
    out = create_template(_body(ctx["ws"].id, name="Mẫu tạm"), db=db, user=ctx["ua"])
    res = delete_template(uuid.UUID(out["id"]), db=db, user=ctx["ua"])
    assert res["deleted"] is True
    assert db.get(ExamTemplate, uuid.UUID(out["id"])) is None
