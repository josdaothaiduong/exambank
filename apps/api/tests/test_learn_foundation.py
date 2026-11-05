"""Sprint 1 foundation (S1-F1 + S1-F2) — bảng Learn trên SQLite + hồi quy FSRS.

FSRS: số kỳ vọng lấy nguyên văn từ spike EL-006 (py-fsrs 6.3.2,
exambank-learn/spikes/fsrs/SPIKE-RESULT.md), mốc D0 = 2026-11-05 02:00 UTC:
Again -> due sau 1 phut, Good -> 10 phut, Easy -> 8 ngay; chuoi Good lien tiep
gian 1 -> 2 -> 7 -> 19 -> 48 ngay; retention 0.85 cho khoang dau 4 ngay,
0.90 cho 2 ngay.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.learn import fsrs_engine as fe
from app.models import (
    Assignment, Attempt, AttemptItem, ClassMembership, LearningAtom, LearnClass,
    Option, PassageGroup, QuestionItem, QuestionStatus, ReviewCard, ReviewLog,
    SourceExam, StudentProfile, Tag, User, Workspace,
)

D0 = datetime(2026, 11, 5, 2, 0, tzinfo=timezone.utc)

TABLES = [User.__table__, Workspace.__table__, SourceExam.__table__, PassageGroup.__table__,
          Tag.__table__, QuestionItem.__table__, Option.__table__,
          StudentProfile.__table__, LearnClass.__table__, ClassMembership.__table__,
          Assignment.__table__, Attempt.__table__, AttemptItem.__table__,
          LearningAtom.__table__, ReviewCard.__table__, ReviewLog.__table__]


@pytest.fixture(scope="module")
def ctx():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    teacher = User(email="gv@x.edu", full_name="GV", password_hash="x", role="teacher")
    student = User(email="hs@x.edu", full_name="HS", password_hash="x", role="student")
    db.add_all([teacher, student]); db.flush()
    ws = Workspace(owner_id=teacher.id, name="WS Learn")
    db.add(ws); db.flush()
    exam = SourceExam(workspace_id=ws.id, created_by=teacher.id,
                      title="UNIT 1 TEST 1", grade=11, exam_kind="45min")
    db.add(exam); db.flush()
    q = QuestionItem(workspace_id=ws.id, source_exam_id=exam.id, created_by=teacher.id,
                     question_type="cloze", order_in_source=5,
                     stem_text="Many families are grateful ___ the opportunity",
                     stem_html="Many families are grateful ___ the opportunity",
                     status=QuestionStatus.approved, dedup_hash="learn-q5",
                     answer_source="teacher_manual")
    db.add(q); db.flush()
    opt = Option(question_id=q.id, label="C", position=3,
                 content_text="for", content_html="for")
    db.add(opt); db.flush()
    q.correct_option_id = opt.id
    return {"db": db, "teacher": teacher, "student": student, "ws": ws,
            "exam": exam, "q": q, "opt": opt}


def test_learn_fk_chain_insert_and_select(ctx):
    db, teacher, student, ws = ctx["db"], ctx["teacher"], ctx["student"], ctx["ws"]
    exam, q, opt = ctx["exam"], ctx["q"], ctx["opt"]

    cls = LearnClass(workspace_id=ws.id, owner_teacher_id=teacher.id, name="11A2",
                     grade=11, school_year="2026-2027", join_code="JOIN11A2")
    db.add(cls); db.flush()
    assert float(cls.desired_retention) == pytest.approx(0.90)

    db.add(StudentProfile(user_id=student.id, workspace_id=ws.id,
                          display_name="Minh Anh", birth_year=2009, status="active"))
    db.add(ClassMembership(class_id=cls.id, student_user_id=student.id,
                           source="teacher_added"))
    db.flush()

    asg = Assignment(workspace_id=ws.id, class_id=cls.id, created_by=teacher.id,
                     source_exam_id=exam.id, title="UNIT 1 TEST 1", mode="paper_quick_entry",
                     opens_at=D0, due_at=D0 + timedelta(days=1),
                     answer_release_at=D0 + timedelta(days=1), status="published")
    db.add(asg); db.flush()

    att = Attempt(workspace_id=ws.id, assignment_id=asg.id, student_user_id=student.id,
                  status="graded", entry_method="quick_entry", client_uuid=uuid.uuid4(),
                  shuffle_seed="seed-1", score_raw=1, score_max=1, submitted_at=D0)
    db.add(att); db.flush()
    db.add(AttemptItem(attempt_id=att.id, question_id=q.id, selected_option_id=opt.id,
                       is_correct=True, confidence_level=3))

    atom = LearningAtom(workspace_id=ws.id, headword="be grateful for", atom_type="collocation",
                        front_html="be grateful ___ the opportunity",
                        front_text="be grateful ___ the opportunity",
                        back_html="for", back_text="for",
                        meaning_vi="biet on vi dieu gi",
                        example_sentence="I am grateful for your help.",
                        source_question_id=q.id, status="approved",
                        origin="teacher_created", answer_provenance="teacher_manual",
                        dedup_hash="atom-grateful-for", created_by=teacher.id)
    db.add(atom); db.flush()

    state, log = fe.apply_rating(None, 1, D0)  # cau sai o D0 -> Again
    card = ReviewCard(workspace_id=ws.id, student_user_id=student.id, atom_id=atom.id,
                      fsrs_card_id=state["card_id"], fsrs_state=state["state"],
                      fsrs_step=state["step"], stability=state["stability"],
                      fsrs_difficulty=state["difficulty"],
                      due_at=fe._parse_dt(state["due"]),
                      created_from_attempt_id=att.id, created_from_question_id=q.id,
                      first_result="wrong")
    db.add(card); db.flush()
    db.add(ReviewLog(review_card_id=card.id, student_user_id=student.id, atom_id=atom.id,
                     activity_type="flashcard", rating=log["rating"], reviewed_at=D0,
                     state_before=log["state_before"], state_after=log["state_after"],
                     client_uuid=uuid.uuid4()))
    db.commit()

    # Doc lai theo dung chuoi quan he class -> membership -> attempt -> card -> log
    members = db.query(ClassMembership).filter_by(class_id=cls.id).all()
    assert [m.student_user_id for m in members] == [student.id]
    attempts = db.query(Attempt).filter_by(assignment_id=asg.id,
                                           student_user_id=student.id).all()
    assert len(attempts) == 1 and attempts[0].score_raw == 1
    items = db.query(AttemptItem).filter_by(attempt_id=att.id).all()
    assert len(items) == 1 and items[0].is_correct is True
    cards = db.query(ReviewCard).filter_by(student_user_id=student.id,
                                           atom_id=atom.id).all()
    assert len(cards) == 1 and cards[0].created_from_attempt_id == att.id
    logs = db.query(ReviewLog).filter_by(review_card_id=card.id).all()
    assert len(logs) == 1 and logs[0].rating == 1
    assert logs[0].state_after["due"] == state["due"]


# ---------------- FSRS hoi quy (so cua spike EL-006) ----------------

def test_fsrs_new_card_again_shorter_than_good():
    again, _ = fe.apply_rating(None, 1, D0)
    good, _ = fe.apply_rating(None, 3, D0)
    easy, _ = fe.apply_rating(None, 4, D0)
    assert fe._parse_dt(again["due"]) - D0 == timedelta(minutes=1)
    assert fe._parse_dt(good["due"]) - D0 == timedelta(minutes=10)
    assert fe._parse_dt(again["due"]) < fe._parse_dt(good["due"])
    assert fe._parse_dt(easy["due"]) - D0 == timedelta(days=8)


def test_fsrs_good_streak_intervals_grow_like_spike():
    state, _ = fe.apply_rating(None, "again", D0)          # sai trong de o D0
    when = fe._parse_dt(state["due"])
    state, _ = fe.apply_rating(state, "good", when)        # hoc lai trong phien
    when = fe._parse_dt(state["due"])
    state, _ = fe.apply_rating(state, "good", when)        # tot nghiep Learning
    assert state["state"] == 2  # Review
    intervals = []
    for _ in range(5):
        when = fe._parse_dt(state["due"])
        state, _ = fe.apply_rating(state, "good", when)
        intervals.append((fe._parse_dt(state["due"]) - when).days)
    # 1 ngay la khoang tot nghiep; cac khoang Review tiep theo theo spike
    assert intervals == [2, 7, 19, 48, 111]


def test_fsrs_retention_changes_interval_in_right_direction():
    def first_review_interval(retention):
        state, _ = fe.apply_rating(None, 3, D0, desired_retention=retention)
        when = fe._parse_dt(state["due"])
        state, _ = fe.apply_rating(state, 3, when, desired_retention=retention)
        return (fe._parse_dt(state["due"]) - fe._parse_dt(state["last_review"])).days

    assert first_review_interval(0.85) == 4
    assert first_review_interval(0.90) == 2
    assert first_review_interval(0.85) > first_review_interval(0.90)


def test_fsrs_state_dict_round_trip():
    state, _ = fe.apply_rating(None, 1, D0)
    when = fe._parse_dt(state["due"])
    state, _ = fe.apply_rating(state, 3, when)
    restored = fe.card_to_state(fe.card_from_state(state))
    assert restored == state


def test_fsrs_preview_intervals_and_naive_datetime_rejected():
    preview = fe.preview_intervals(None, D0)
    assert preview[1]["interval"] == timedelta(minutes=1)
    assert preview[3]["interval"] == timedelta(minutes=10)
    assert preview[4]["interval"] == timedelta(days=8)
    with pytest.raises(ValueError):
        fe.apply_rating(None, 3, datetime(2026, 11, 5, 2, 0))  # naive -> loi


def test_due_queue_filters_sorts_and_caps_new_cards():
    past = D0 - timedelta(days=2)
    cards = [
        {"id": "future", "due_at": D0 + timedelta(days=1), "reps": 0},
        {"id": "suspended", "due_at": past, "reps": 3, "suspended_at": D0},
        {"id": "old-b", "due_at": past + timedelta(hours=1), "reps": 5},
        {"id": "old-a", "due_at": past, "reps": 5},
    ] + [{"id": f"new-{i}", "due_at": past, "reps": 0} for i in range(25)]
    out = fe.due_queue(cards, D0, limit=35, new_limit=20)
    ids = [c["id"] for c in out]
    assert "future" not in ids and "suspended" not in ids
    assert ids[0] == "old-a"  # qua han lau nhat truoc
    assert sum(1 for i in ids if i.startswith("new-")) == 20  # tran the moi/ngay
