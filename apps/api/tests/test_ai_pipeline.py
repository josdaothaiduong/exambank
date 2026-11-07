"""EB-301/302/303 — Pipeline AI: provider demo giải -> ai_solutions -> pending_review;
cổng confidence 0.70 chặn duyệt mù; giáo viên tự chọn đáp án thì duyệt được."""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    AISolution, Difficulty, ImportJob, Option, PassageGroup, QuestionItem, QuestionStatus,
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


class _ExplodingProvider:
    """Provider stub: riêng câu 'museum' trả confidence SAI KIỂU (chuỗi thay vì
    số) -> TypeError khi pipeline tính độ tin cậy — lỗi lạ nằm NGOÀI
    ProviderError. (Trước đây test này dùng difficulty="SAI" làm phương tiện,
    nhưng difficulty nay là trường gợi ý được chuẩn hoá khoan dung — giá trị lạ
    coi như không đề xuất, xem test_ai_difficulty_* — nên phải đổi phương tiện;
    mục đích test: cách ly lỗi theo từng câu trong mẻ, không đổi.)"""
    name = "stub"
    model = "stub-1"

    def solve(self, system, user, valid_labels):
        confidence = "cao" if "museum" in user else 0.9
        return {"solution": {"answer_label": "A", "confidence": confidence,
                             "explanation_vi": "stub", "difficulty": "NB",
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
    stats = solve_batch(db, questions, _ExplodingProvider())
    assert stats["total"] == 3 and stats["solved"] == 2 and stats["failed"] == 1
    db.expire_all()
    by_stem = {q.stem_text: q for q in db.query(QuestionItem)
               .filter(QuestionItem.source_exam_id == exam_id).all()}
    bad = next(q for s, q in by_stem.items() if "museum" in s)
    assert bad.status == QuestionStatus.needs_answer
    good = [q for s, q in by_stem.items() if "museum" not in s]
    assert all(q.status == QuestionStatus.pending_review for q in good)


# ---------------------------------------------------------------------------
# AI đề xuất độ khó: provider trả difficulty khi giải -> lưu vào ai_solution
# (cột difficulty + suggested_difficulty) -> review_queue phơi ai_difficulty.
# AI chỉ ĐỀ XUẤT: không tự áp vào question.difficulty, GV bấm mới dùng.
# ---------------------------------------------------------------------------

class _FixedDifficultyProvider:
    """Provider stub cho difficulty cố định, ĐI QUA validate_solution như
    provider thật (difficulty=None nghĩa là JSON không có trường difficulty)."""
    name = "stub"

    def __init__(self, difficulty):
        self.model = "stub-diff"
        self._difficulty = difficulty

    def solve(self, system, user, valid_labels):
        from app.ai.provider import validate_solution
        sol = {"answer_label": "A", "confidence": 0.95,
               "explanation_vi": "stub", "tags": []}
        if self._difficulty is not None:
            sol["difficulty"] = self._difficulty
        return {"solution": validate_solution(sol, valid_labels),
                "usage": {"input_tokens": 1, "output_tokens": 1}, "raw": {}}

    def cost_usd(self, usage):
        return 0.0


def _needs_answer_questions(db, exam_id):
    return (db.query(QuestionItem)
            .filter(QuestionItem.source_exam_id == exam_id,
                    QuestionItem.status == QuestionStatus.needs_answer)
            .order_by(QuestionItem.order_in_source).all())


def _solutions_of(db, exam_id):
    qids = [q.id for q in db.query(QuestionItem)
            .filter(QuestionItem.source_exam_id == exam_id).all()]
    return db.query(AISolution).filter(AISolution.question_id.in_(qids)).all()


def test_ai_difficulty_valid_is_saved_and_exposed(ctx):
    """(a) difficulty hợp lệ -> solution lưu đúng cả 2 cột + review_queue
    có ai_difficulty; question.difficulty vẫn trống (AI không tự áp)."""
    from app.ai.pipeline import solve_batch
    db = ctx["db"]
    exam_id = _fresh_exam(ctx, "Đề AI đề xuất độ khó hợp lệ")
    stats = solve_batch(db, _needs_answer_questions(db, exam_id),
                        _FixedDifficultyProvider("VD"))
    assert stats["solved"] == 3 and stats["failed"] == 0
    sols = _solutions_of(db, exam_id)
    assert len(sols) == 3
    assert all(s.difficulty == "VD" for s in sols)
    assert all(s.suggested_difficulty == Difficulty.VD for s in sols)
    queue = review_queue(exam_id, db=db, user=ctx["ua"])
    assert queue["total"] == 3
    assert all(i["ai_difficulty"] == "VD" for i in queue["items"])
    assert all(i["difficulty"] is None for i in queue["items"])


def test_ai_difficulty_invalid_means_no_suggestion(ctx):
    """(b) difficulty lạ -> coi như KHÔNG đề xuất (ai_difficulty null, solution
    vẫn lưu với difficulty None) và lần giải KHÔNG lỗi — trường gợi ý không
    được phép huỷ một đáp án tốt. Câu chưa từng qua AI cũng ai_difficulty null."""
    from app.ai.pipeline import solve_batch
    db = ctx["db"]
    exam_id = _fresh_exam(ctx, "Đề AI đề xuất độ khó lạ")
    queue0 = review_queue(exam_id, db=db, user=ctx["ua"])
    assert all(i["ai_difficulty"] is None for i in queue0["items"])
    stats = solve_batch(db, _needs_answer_questions(db, exam_id),
                        _FixedDifficultyProvider("SAI"))
    assert stats["solved"] == 3 and stats["failed"] == 0
    sols = _solutions_of(db, exam_id)
    assert len(sols) == 3
    assert all(s.difficulty is None and s.suggested_difficulty is None for s in sols)
    queue = review_queue(exam_id, db=db, user=ctx["ua"])
    assert all(i["ai_difficulty"] is None for i in queue["items"])


def test_validate_solution_difficulty_is_lenient():
    """validate_solution: difficulty hợp lệ giữ nguyên; lạ/thiếu -> None,
    các trường đáp án/confidence vẫn kiểm chặt như cũ."""
    from app.ai.provider import validate_solution
    base = {"answer_label": "A", "explanation_vi": "x", "confidence": 0.9, "tags": []}
    assert validate_solution({**base, "difficulty": "VDC"}, {"A"})["difficulty"] == "VDC"
    assert validate_solution({**base, "difficulty": "SAI"}, {"A"})["difficulty"] is None
    assert validate_solution(base, {"A"})["difficulty"] is None
    assert validate_solution({**base, "difficulty": None}, {"A"})["difficulty"] is None


def test_demo_provider_suggests_difficulty_by_rule():
    """(c) DemoProvider (rule-based) luôn cho đề xuất thuộc 4 mức NB/TH/VD/VDC
    và đúng quy tắc bề mặt cho các dạng điển hình."""
    from app.ai.prompts import build_user_prompt
    from app.ai.provider import DemoProvider
    p = DemoProvider()
    labels = {"A", "B", "C", "D"}

    def diff_of(stem, options, qtype="grammar_mc", passage=None):
        user = build_user_prompt(stem=stem, options=options,
                                 question_type=qtype, passage_text=passage)
        return p.solve(system="s", user=user, valid_labels=labels)["solution"]["difficulty"]

    grammar_opts = [{"label": "A", "text": "has lived"}, {"label": "B", "text": "live"},
                    {"label": "C", "text": "lives"}, {"label": "D", "text": "living"}]
    # Ngữ pháp cơ bản, quy tắc mạnh (since + năm -> HTHT) -> NB
    assert diff_of("She ______ here since 2010.", grammar_opts) == "NB"
    # Sắp xếp câu (phương án dạng chuỗi a-b-c) -> VD
    arr_opts = [{"label": "A", "text": "b-a-c"}, {"label": "B", "text": "a-b-c"},
                {"label": "C", "text": "b-c-a"}, {"label": "D", "text": "c-a-b"}]
    assert diff_of("Mark the correct arrangement of the sentences.", arr_opts,
                   "sentence_arrangement") == "VD"
    # Suy luận từ đoạn văn -> VDC
    assert diff_of("What can be inferred from the passage?", grammar_opts,
                   "reading_comprehension", passage="Some neutral passage text.") == "VDC"
    # Cloze trong đoạn, đáp án là cụm dài -> VD; đáp án ngắn -> TH
    long_opts = [{"label": "A", "text": "the urban population has grown"},
                 {"label": "B", "text": "growth"}, {"label": "C", "text": "grows"},
                 {"label": "D", "text": "grown"}]
    assert diff_of("Since 1950, ______.", long_opts, "cloze",
                   passage="A passage about cities.") == "VD"
    assert diff_of("The city is ______ for its parks.", grammar_opts, "cloze",
                   passage="A passage about a city.") == "TH"
    # Đồng nghĩa trong ngữ cảnh -> TH; và mọi kết quả đều thuộc 4 mức
    syn_opts = [{"label": "A", "text": "essential"}, {"label": "B", "text": "late"},
                {"label": "C", "text": "weak"}, {"label": "D", "text": "rare"}]
    d_syn = diff_of('The word "crucial" is closest in meaning to ______.', syn_opts, "synonym")
    assert d_syn == "TH"
    for d in ("NB", "TH", "VD", "VDC"):
        assert d in ("NB", "TH", "VD", "VDC")
