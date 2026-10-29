"""Hồi quy theo góp ý của Ha (2026-10-29): in đậm/gạch chân trong đề là NỘI DUNG câu hỏi
(từ cần tìm đồng nghĩa, câu được gạch chân trong đoạn văn...) — sanitize/parser KHÔNG được
làm mất, và marker nội bộ không được lọt vào dữ liệu lưu trữ."""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    ImportJob, Option, PassageGroup, QuestionItem, QuestionTag, SourceExam, Tag, User, Workspace,
)
from app.parsers.parser import parse_exam_html
from app.parsers.sanitize import sanitize_html
from app.routers.imports import PasteIn, import_paste, review_queue
from app.routers.source_exams import SourceExamIn, create_source_exam
from app.seed import seed_taxonomy

EMPHASIS_HTML = """
<p>Pollution is a serious problem. The word <b>crucial</b> matters here. <u>People must act now to save the planet.</u> Everyone agrees.</p>
<p>Question 1: The word <b>crucial</b> in the passage is closest in meaning to ______. A. unimportant B. <span style="color:#ff0000">essential</span> C. optional D. rare</p>
<p>Question 2: The underlined sentence mainly ______. A. gives an example B. states a fact C. <span style="font-weight: bold">calls for action</span> D. asks a question</p>
<p>Question 3: The word <b>serious</b> is closest in meaning to ______. A. light B. minor C. grave D. easy</p>
"""


def test_sanitize_keeps_emphasis_styles_drops_junk_attrs():
    dirty = ('<p class="x" id="y">Word <span style="font-weight: bold; color: #333" onclick="hack()">crucial</span> '
             'and <span style="text-decoration: underline">underlined part</span> and <b>bold</b> <u>under</u></p>')
    clean = sanitize_html(dirty)
    assert "font-weight: bold" in clean and "text-decoration: underline" in clean
    assert "<b>bold</b>" in clean and "<u>under</u>" in clean
    assert "onclick" not in clean and 'class=' not in clean and 'id=' not in clean


def test_passage_and_stem_preserve_emphasis_no_marker_leak():
    out = parse_exam_html(EMPHASIS_HTML)
    p = out["passages"][0]
    assert "<b>crucial</b>" in p["content_html"]
    assert "<u>People must act now to save the planet.</u>" in p["content_html"]
    assert "[[" not in p["content_text"] and "[[" not in p["content_html"]
    q1 = out["questions"][0]
    assert q1["stem_html"].startswith("The word <b>crucial</b>")
    assert "[[" not in q1["stem"] and "<b>" not in q1["stem"]


def test_span_style_bold_answer_detected():
    out = parse_exam_html(EMPHASIS_HTML)
    det = out["questions"][1]["detected_answer"]
    assert det == {"label": "C", "source": "bold_underline", "confidence": 0.8}


def test_bold_only_in_stem_does_not_fabricate_answer():
    out = parse_exam_html(EMPHASIS_HTML)
    # Câu 3: chỉ có từ trong stem in đậm, phương án hoàn toàn thường -> không được bịa đáp án
    assert out["questions"][2]["detected_answer"] is None


TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__,
          ImportJob.__table__]


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    ua = User(email="e@x.edu", full_name="E", password_hash="x", role="teacher")
    db.add(ua); db.flush()
    ws = Workspace(owner_id=ua.id, name="WS E")
    db.add(ws); db.commit()
    exam = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Đề nhấn mạnh", grade=12,
                                           exam_kind="final"), db=db, user=ua)
    return {"db": db, "ua": ua, "ws": ws, "exam_id": uuid.UUID(exam["id"])}


def test_import_preserves_emphasis_into_db_and_review_queue(ctx):
    out = import_paste(ctx["exam_id"], PasteIn(html=EMPHASIS_HTML), db=ctx["db"], user=ctx["ua"])
    assert out["stats"]["total"] == 3
    q = review_queue(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    first = q["items"][0]
    assert "<b>crucial</b>" in (first["passage_html"] or "")
    assert "<u>People must act now" in (first["passage_html"] or "")
    assert "[[" not in first["stem_text"]
    assert first["stem_html"].startswith("The word <b>crucial</b>")
    passage = ctx["db"].query(PassageGroup).one()
    assert "<b>crucial</b>" in passage.content_html and "[[" not in passage.content_text
