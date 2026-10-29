"""EB-306 — Cảnh báo trùng ngữ nghĩa: câu diễn đạt khác đôi chút (hash khác) nhưng cùng nội dung
phải bị cảnh báo khi import; câu khác hẳn thì không."""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.similarity import similarity
from app.db import Base
from app.models import (
    AISolution, ImportJob, Option, PassageGroup, QuestionItem, QuestionTag,
    SourceExam, Tag, User, Workspace,
)
from app.routers.imports import PasteIn, import_paste
from app.routers.source_exams import SourceExamIn, create_source_exam
from app.seed import seed_taxonomy

TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__, QuestionTag.__table__,
          ImportJob.__table__, AISolution.__table__]

V1 = """
<p>Question 1: She ______ to school by bus every day. A. goes B. go C. going D. gone</p>
<p>Question 2: My father ______ in a big factory near the city center. A. works B. work C. working D. worked</p>
"""
# Câu 1 diễn đạt lại (thêm "usually", đổi "by bus"->"by bicycle" KHÔNG có trong options, giữ nguyên options+ý)
V2 = """
<p>Question 1: She usually ______ to school by bus every day in the morning. A. goes B. go C. going D. gone</p>
<p>Question 2: Photosynthesis is the process by which green plants ______ sunlight into energy. A. convert B. converts C. converting D. conversion</p>
"""


def test_similarity_function():
    s = similarity("She goes to school by bus every day", ["goes", "go", "going", "gone"],
                   "She usually goes to school by bus every day in the morning",
                   ["goes", "go", "going", "gone"])
    assert s >= 0.85
    s2 = similarity("She goes to school by bus every day", ["goes", "go", "going", "gone"],
                    "Photosynthesis converts sunlight into energy in plants",
                    ["convert", "converts", "converting", "conversion"])
    assert s2 < 0.5


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    seed_taxonomy(db)
    ua = User(email="sem@x.edu", full_name="Sem", password_hash="x", role="teacher")
    db.add(ua); db.flush()
    ws = Workspace(owner_id=ua.id, name="WS Sem")
    db.add(ws); db.commit()
    e1 = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Bản gốc", grade=10, exam_kind="quiz"), db=db, user=ua)
    import_paste(uuid.UUID(e1["id"]), PasteIn(html=V1), db=db, user=ua)
    e2 = create_source_exam(SourceExamIn(workspace_id=ws.id, title="Bản diễn đạt lại", grade=10, exam_kind="quiz"), db=db, user=ua)
    return {"db": db, "ua": ua, "e2": uuid.UUID(e2["id"])}


def test_import_warns_near_duplicate(ctx):
    out = import_paste(ctx["e2"], PasteIn(html=V2), db=ctx["db"], user=ctx["ua"])
    assert out["status"] == "done"
    assert out["stats"]["near_duplicates"] == 1
    hit = out["near_duplicates"][0]
    assert hit["number"] == 1 and hit["similarity"] >= 0.85
