"""EB-204/205/206 — Import pipeline + dedup + review queue (gọi trực tiếp router functions)."""
import io
import pathlib
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Difficulty, ImportJob, Option, PassageGroup, QuestionItem, QuestionStatus,
    QuestionTag, SourceExam, Tag, User, Workspace,
)
from app.parsers.importer import docx_to_html, import_html
from app.routers.imports import PasteIn, ReviewIn, import_paste, review_question, review_queue
from app.routers.questions import list_question_items
from app.routers.source_exams import SourceExamIn, create_source_exam
from app.seed import seed_taxonomy

GOLDEN = pathlib.Path(__file__).parent / "golden_files"
TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__,
          ImportJob.__table__]


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    ua = User(email="a@x.edu", full_name="A", password_hash="x", role="teacher")
    db.add(ua); db.flush()
    ws = Workspace(owner_id=ua.id, name="WS A")
    db.add(ws); db.commit()
    exam = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Đề đỏ", grade=12,
                                           exam_kind="final"), db=db, user=ua)
    return {"db": db, "ua": ua, "ws": ws, "exam_id": uuid.UUID(exam["id"])}


def test_import_red_stats_and_raw_html_saved(ctx):
    html = (GOLDEN / "exam1_red.html").read_text()
    out = import_paste(ctx["exam_id"], PasteIn(html=html), db=ctx["db"], user=ctx["ua"])
    assert out["status"] == "done"
    assert out["stats"] == {"total": 4, "with_answer": 4, "needs_answer": 0, "duplicates": 0, "overwritten": 0, "failed": 0, "near_duplicates": 0}
    exam = ctx["db"].get(SourceExam, ctx["exam_id"])
    assert exam.raw_html and "color" in exam.raw_html  # EB-201: raw_html đã sanitize vẫn giữ tín hiệu đỏ
    q = review_queue(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    assert q["total"] == 4
    assert all(i["status"] == "pending_review" for i in q["items"])
    first = q["items"][0]
    assert first["answer_source"] == "red_text"
    correct = [o for o in first["options"] if o["id"] == first["correct_option_id"]]
    assert correct and correct[0]["label"] == "B"


def test_import_dedup_second_time(ctx):
    html = (GOLDEN / "exam1_red.html").read_text()
    out = import_paste(ctx["exam_id"], PasteIn(html=html, on_conflict="keep_old"), db=ctx["db"], user=ctx["ua"])
    assert out["stats"]["duplicates"] == 4 and out["stats"]["with_answer"] == 0
    assert review_queue(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])["total"] == 4


def test_review_approve_with_metadata(ctx):
    q = review_queue(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    qid = uuid.UUID(q["items"][0]["id"])
    out = review_question(qid, ReviewIn(action="approve", difficulty=Difficulty.TH,
                                        tag_codes=["gs12_unit3"]), db=ctx["db"], user=ctx["ua"])
    assert out["status"] == "approved" and out["difficulty"] == "TH"
    res = list_question_items(status_filter=QuestionStatus.approved, grade=None, unit="gs12_unit3",
                              question_type=None, difficulty=None, search=None, page=1, page_size=20,
                              workspace_id=ctx["ws"].id, user=ctx["ua"], db=ctx["db"])
    assert res["total"] == 1


def test_review_reject(ctx):
    q = review_queue(ctx["exam_id"], db=ctx["db"], user=ctx["ua"])
    out = review_question(uuid.UUID(q["items"][0]["id"]), ReviewIn(action="reject"), db=ctx["db"], user=ctx["ua"])
    assert out["status"] == "rejected"


def _make_docx(paragraphs):
    """paragraphs: list of list of (text, color|None). Tạo .docx tối thiểu hợp lệ."""
    runs = []
    for para in paragraphs:
        rs = ""
        for text, color in para:
            c = f'<w:rPr><w:color w:val="{color}"/></w:rPr>' if color else ""
            rs += f"<w:r>{c}<w:t>{text}</w:t></w:r>"
        runs.append(f"<w:p>{rs}</w:p>")
    doc = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{''.join(runs)}</w:body></w:document>")
    ct = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def test_docx_pipeline_shares_parser(ctx):
    data = _make_docx([
        [("Question 1: They ______ football every Sunday. A. plays B. ", None), ("play", "FF0000"), (" C. playing D. played yesterday", None)],
        [("Question 2: He ______ to school every day. A. go B. ", None), ("goes", "FF0000"), (" C. going D. gone", None)],
    ])
    html = docx_to_html(data)
    exam = create_source_exam(SourceExamIn(workspace_id=ctx["ws"].id, title="Đề docx", grade=12,
                                           exam_kind="quiz"), db=ctx["db"], user=ctx["ua"])
    job = import_html(ctx["db"], ctx["db"].get(SourceExam, uuid.UUID(exam["id"])), html, created_by=ctx["ua"].id)
    assert job.stats["total"] == 2 and job.stats["with_answer"] == 2, job.stats


def test_import_quarantines_duplicate_option_labels(ctx):
    """EB-406 UAT: 1 câu có 2 dãy A-B-C-D (nhãn trùng) không được làm sập cả lượt import."""
    html = """
    <p>Question 1: Normal question ______ here. A. one B. two C. three D. four</p>
    <p>Question 2: Dear Sir, a. first part b. second part A. opt1 B. opt2 C. opt3 D. opt4 A. dup B. dup2 C. dup3</p>
    <p>Question 3: Another normal ______ one. A. x B. y C. z D. w</p>
    """
    out = import_paste(ctx["exam_id"], PasteIn(html=html), db=ctx["db"], user=ctx["ua"])
    assert out["status"] == "done"
    issues = {e["issue"] for e in out["error_log"]}
    assert "duplicate_option_labels" in issues
    assert out["stats"]["failed"] >= 1
