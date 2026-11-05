"""Learn Sprint 2 (EL-202/203/201/204) — test qua HTTP thật (TestClient).

Bao phủ bắt buộc:
- pipeline bẻ hạt idempotent (chạy 2 lần = 1 bộ atom, không gọi lại/sinh trùng)
- validate JSON hỏng -> job failed, không lưu rác
- trần 3 atom/câu + trần 120 atom/đề
- atom draft KHÔNG lộ ở bất kỳ payload nào phía HS
- GV duyệt -> HS thấy hậu-đề; cổng release 403 ANSWER_NOT_RELEASED
- khoá bước 2/3/4 ở server khi chưa xong bước trước (STEP_LOCKED)
- chấm chẩn đoán (bước 1) + cặp tối thiểu (bước 3) + biến thể (bước 4)
- reject không bị ghi đè khi sinh lại (kể cả force)
- cổng duyệt 0,70: atom AI conf < 0,70 chưa mở xem -> 422 ATOM_LOW_CONFIDENCE
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    AIGenerationJob, Assignment, AtomSource, Attempt, AttemptItem, AuditLog,
    ClassMembership, ConsentRecord, EnrollmentRequest, Exam, ExamItem,
    ExamVersion, LearnClass, LearningAtom, Option, ParentLink, ParentProfile,
    PassageGroup, PostTestContent, PostTestProgress, QuestionItem,
    QuestionStatus, QuestionTag, ReviewCard, ReviewLog, SourceExam,
    StudentProfile, Tag, User,
    VariantAttempt, VariantItem, VariantOption, Workspace,
)
from app.security import create_access_token, hash_password

TABLES = [t.__table__ for t in (
    User, Workspace, SourceExam, PassageGroup, QuestionItem, Option, Tag,
    QuestionTag,
    Exam, ExamVersion, ExamItem, StudentProfile, ParentProfile, LearnClass,
    ClassMembership, ParentLink, ConsentRecord, Assignment, Attempt,
    AttemptItem, EnrollmentRequest, LearningAtom, AtomSource, ReviewCard,
    ReviewLog,
    __import__("app.models", fromlist=["AtomTag"]).AtomTag,
    PostTestContent, PostTestProgress, VariantItem, VariantOption,
    VariantAttempt, AIGenerationJob, AuditLog,
    __import__("app.models", fromlist=["ApiUsageLog"]).ApiUsageLog)]

NOW = datetime.now(timezone.utc)
STEM_Q7 = "…a growing ___ of families now encourage their children to learn important skills at home."


def _mk_question(db, ws, teacher, se, i, stem, correct_label, opt_texts,
                 status=QuestionStatus.approved, qtype="cloze"):
    q = QuestionItem(workspace_id=ws.id, source_exam_id=se.id,
                     question_type=qtype, order_in_source=i,
                     stem_html=stem, stem_text=stem, status=status,
                     dedup_hash=f"learn-s2-{se.id}-{i}", created_by=teacher.id)
    db.add(q)
    db.flush()
    opts = []
    for j, (label, text) in enumerate(opt_texts):
        o = Option(question_id=q.id, label=label, content_html=text,
                   content_text=text, position=j)
        db.add(o)
        opts.append(o)
    db.flush()
    if correct_label:
        q.correct_option_id = next(o.id for o in opts if o.label == correct_label)
    return q


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

    teacher = User(email="gv@truong.edu", full_name="GV",
                   password_hash=hash_password("teacher-pass"), role="teacher")
    db.add(teacher)
    db.flush()
    ws = Workspace(owner_id=teacher.id, name="WS GV")
    db.add(ws)
    db.commit()

    def tok(u):
        return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}

    out = {"client": client, "db": db, "teacher": teacher, "ws": ws,
           "tok_t": tok(teacher)}

    r = client.post("/api/v1/learn/classes", headers=out["tok_t"], json={
        "name": "11A2", "grade": 11, "school_year": "2026-2027"})
    assert r.status_code == 201, r.text
    out["class"] = r.json()
    r = client.post(f"/api/v1/learn/classes/{out['class']['id']}/students",
                    headers=out["tok_t"], json={"students": [
                        {"display_name": "Minh Anh", "birth_year": 2009}]})
    assert r.status_code == 201, r.text
    created = r.json()["created"][0]
    out["student_id"] = created["student_user_id"]
    # đồng ý kép qua phiếu giấy (GV ghi nhận) -> HS active
    r = client.post(f"/api/v1/learn/students/{out['student_id']}/paper-consent",
                    headers=out["tok_t"], json={})
    assert r.status_code in (200, 201), r.text
    stu = db.get(User, uuid.UUID(out["student_id"]))
    out["tok_s"] = tok(stu)

    # --- đề: Q7-lượng từ (đúng B number), Q-vocab (đúng A), Q-chưa duyệt
    se = SourceExam(workspace_id=ws.id, title="UNIT 1 TEST 1", grade=11,
                    created_by=teacher.id)
    db.add(se)
    db.flush()
    q7 = _mk_question(db, ws, teacher, se, 7, STEM_Q7, "B",
                      [("A", "amount"), ("B", "number"),
                       ("C", "level"), ("D", "range")])
    qv = _mk_question(db, ws, teacher, se, 5,
                      "People should be ___ for the help they receive.", "A",
                      [("A", "grateful"), ("B", "grate"), ("C", "gratitude"),
                       ("D", "gratefully")], qtype="vocabulary_mc")
    qbad = _mk_question(db, ws, teacher, se, 99, "Câu chưa duyệt?", None,
                        [("A", "x"), ("B", "y")],
                        status=QuestionStatus.pending_review)
    db.commit()
    out.update({"se": se, "q7": q7, "qv": qv, "qbad": qbad})

    def publish_assignment(release_delta):
        body = {"class_id": out["class"]["id"], "source_exam_id": str(se.id),
                "mode": "paper_quick_entry",
                "opens_at": (NOW - timedelta(hours=2)).isoformat(),
                "due_at": (NOW + timedelta(days=1)).isoformat(),
                "answer_release_at": (NOW + release_delta).isoformat()}
        rr = client.post("/api/v1/learn/assignments", headers=out["tok_t"], json=body)
        assert rr.status_code == 201, rr.text
        a = rr.json()
        rr = client.post(f"/api/v1/learn/assignments/{a['id']}/publish",
                         headers=out["tok_t"], json={})
        assert rr.status_code == 200, rr.text
        return a["id"]

    # assignment chính chỉ gồm q7+qv: tạo đề riêng 2 câu để publish sạch
    se2 = SourceExam(workspace_id=ws.id, title="Đề hậu-đề", grade=11,
                     created_by=teacher.id)
    db.add(se2)
    db.flush()
    q7b = _mk_question(db, ws, teacher, se2, 7, STEM_Q7, "B",
                       [("A", "amount"), ("B", "number"),
                        ("C", "level"), ("D", "range")])
    qvb = _mk_question(db, ws, teacher, se2, 5,
                       "People should be ___ for the help they receive.", "A",
                       [("A", "grateful"), ("B", "grate"), ("C", "gratitude"),
                        ("D", "gratefully")], qtype="vocabulary_mc")
    db.commit()
    out.update({"se2": se2, "q7b": q7b, "qvb": qvb})

    def publish_on(exam, release_delta, title_suffix=""):
        body = {"class_id": out["class"]["id"], "source_exam_id": str(exam.id),
                "mode": "paper_quick_entry",
                "opens_at": (NOW - timedelta(hours=2)).isoformat(),
                "due_at": (NOW + timedelta(days=1)).isoformat(),
                "answer_release_at": (NOW + release_delta).isoformat()}
        rr = client.post("/api/v1/learn/assignments", headers=out["tok_t"], json=body)
        assert rr.status_code == 201, rr.text
        a = rr.json()
        rr = client.post(f"/api/v1/learn/assignments/{a['id']}/publish",
                         headers=out["tok_t"], json={})
        assert rr.status_code == 200, rr.text
        return a["id"]

    out["assignment_released"] = publish_on(se2, timedelta(hours=-1))
    out["assignment_locked"] = publish_on(se2, timedelta(hours=3))

    def do_attempt(assignment_id, answers: dict):
        rr = client.post(f"/api/v1/learn/assignments/{assignment_id}/attempts",
                         headers=out["tok_s"],
                         json={"client_uuid": str(uuid.uuid4()),
                               "entry_method": "quick_entry"})
        assert rr.status_code == 201, rr.text
        att = rr.json()
        payload = [{"question_id": qid, "selected_option_id": oid}
                   for qid, oid in answers.items()]
        rr = client.post(f"/api/v1/learn/attempts/{att['attempt_id']}/submit",
                         headers=out["tok_s"],
                         json={"client_uuid": att["attempt_id"], "answers": payload})
        assert rr.status_code == 200, rr.text
        return att["attempt_id"], rr.json()

    opt = {(str(o.question_id), o.label): str(o.id)
           for o in db.query(Option).all()}
    out["opt"] = opt
    # HS sai Q7 (chọn amount), đúng Qvocab
    att_id, res = do_attempt(out["assignment_released"], {
        str(q7b.id): opt[(str(q7b.id), "A")],
        str(qvb.id): opt[(str(qvb.id), "A")],
    })
    out["attempt_released"] = att_id
    att2_id, _ = do_attempt(out["assignment_locked"], {
        str(q7b.id): opt[(str(q7b.id), "A")],
        str(qvb.id): opt[(str(qvb.id), "A")],
    })
    out["attempt_locked"] = att2_id
    yield out
    app.dependency_overrides.pop(get_db, None)


# ------------------------------------------------------------------ EL-202
def test_generation_creates_atoms_content_and_variants(ctx):
    c, db = ctx["client"], ctx["db"]
    r = c.post(f"/api/v1/learn/questions/{ctx['q7b'].id}/atom-generation-jobs",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    atoms = db.query(LearningAtom).filter_by(source_question_id=ctx["q7b"].id).all()
    assert 1 <= len(atoms) <= 3  # trần 3/câu
    assert all(a.status == "pending_review" for a in atoms)
    headwords = {a.headword for a in atoms}
    assert "number" in headwords and "amount" in headwords  # đáp án + distractor thật
    pc = db.query(PostTestContent).filter_by(question_id=ctx["q7b"].id).one()
    assert pc.status == "pending_review"
    assert pc.content_json["correct_diagnosis_key"] == "l1_transfer"  # mẫu Q7 báo cáo 03
    assert pc.content_json["rule"].startswith("a number of")
    # nguồn atom truy được về câu + distractor (atom_sources)
    roles = {s.source_role for s in db.query(AtomSource)
             .filter(AtomSource.atom_id.in_([a.id for a in atoms])).all()}
    assert "correct_answer" in roles and "distractor" in roles
    # biến thể P1 (T1) đã sinh cho atom, cũng chờ duyệt
    vars_ = db.query(VariantItem).filter(
        VariantItem.parent_atom_id.in_([a.id for a in atoms])).all()
    assert vars_ and all(v.status == "pending_review" for v in vars_)
    assert all(v.correct_option_id for v in vars_)
    # job + sổ chi phí
    job = db.get(AIGenerationJob, uuid.UUID(body["job_id"]))
    assert job.status == "succeeded" and job.kind == "atom_extract"
    from app.models import ApiUsageLog
    assert db.query(ApiUsageLog).filter_by(endpoint_kind="atom_extract").count() >= 1
    ctx["atoms_q7"] = atoms
    ctx["content_q7"] = pc


def test_generation_idempotent_second_run(ctx):
    c, db = ctx["client"], ctx["db"]
    before = db.query(LearningAtom).filter_by(source_question_id=ctx["q7b"].id).count()
    jobs_before = db.query(AIGenerationJob).count()
    r = c.post(f"/api/v1/learn/questions/{ctx['q7b'].id}/atom-generation-jobs",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "existing"
    assert db.query(LearningAtom).filter_by(source_question_id=ctx["q7b"].id).count() == before
    assert db.query(AIGenerationJob).count() == jobs_before  # không gọi AI/job mới


def test_generation_rejects_unapproved_question(ctx):
    c = ctx["client"]
    r = c.post(f"/api/v1/learn/questions/{ctx['qbad'].id}/atom-generation-jobs",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "QUESTIONS_NOT_APPROVED"


def test_generation_validation_failure_saves_nothing(ctx, monkeypatch):
    import app.learn.content_pipeline as pipeline

    class BadProvider:
        name = "bad"
        model = "bad-model"

        def generate_json(self, *, system, user):
            return {"data": {"atoms": "không phải list"},
                    "raw": {}, "usage": {"input_tokens": 1, "output_tokens": 1}}

        def cost_usd(self, usage):
            return 0.0

    monkeypatch.setattr(pipeline, "get_provider", lambda settings: BadProvider())
    c, db = ctx["client"], ctx["db"]
    r = c.post(f"/api/v1/learn/questions/{ctx['qvb'].id}/atom-generation-jobs",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "failed"
    assert db.query(LearningAtom).filter_by(source_question_id=ctx["qvb"].id).count() == 0
    assert db.query(PostTestContent).filter_by(question_id=ctx["qvb"].id).count() == 0
    job = db.get(AIGenerationJob, uuid.UUID(r.json()["job_id"]))
    assert job.status == "failed" and job.error_log


def test_reject_not_overwritten_by_regeneration(ctx):
    c, db = ctx["client"], ctx["db"]
    atoms = db.query(LearningAtom).filter_by(source_question_id=ctx["q7b"].id).all()
    victim = next(a for a in atoms if a.headword == "amount")
    r = c.post(f"/api/v1/learn/atoms/{victim.id}/reject", headers=ctx["tok_t"], json={})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # sinh lại có chủ đích (force) — atom đã reject giữ nguyên, không đẻ bản sao
    r = c.post(f"/api/v1/learn/questions/{ctx['q7b'].id}/atom-generation-jobs",
               headers=ctx["tok_t"], json={"force": True})
    assert r.status_code == 201, r.text
    db.expire_all()
    same = db.query(LearningAtom).filter_by(source_question_id=ctx["q7b"].id,
                                            headword="amount").all()
    assert len(same) == 1 and same[0].status == "rejected"


# ------------------------------------------------------------------ EL-203
def test_low_confidence_gate(ctx):
    db = ctx["db"]
    low = LearningAtom(
        workspace_id=ctx["ws"].id, headword="lowconf", atom_type="vocab",
        front_html="f", front_text="f", back_html="b", back_text="b",
        meaning_vi="m", example_sentence="e", priority="P1",
        source_question_id=ctx["qvb"].id, status="pending_review",
        origin="ai_generated", answer_provenance="ai_inferred",
        ai_confidence=0.5, dedup_hash="lowconf-hash", created_by=ctx["teacher"].id)
    db.add(low)
    db.commit()
    c = ctx["client"]
    r = c.post(f"/api/v1/learn/atoms/{low.id}/approve",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "ATOM_LOW_CONFIDENCE"
    # mở xem chi tiết -> qua cổng
    r = c.get(f"/api/v1/learn/atoms/{low.id}", headers=ctx["tok_t"])
    assert r.status_code == 200
    r = c.post(f"/api/v1/learn/atoms/{low.id}/approve",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # bulk-approve bỏ qua atom low-conf chưa xem
    low2 = LearningAtom(
        workspace_id=ctx["ws"].id, headword="lowconf2", atom_type="vocab",
        front_html="f", front_text="f", back_html="b", back_text="b",
        meaning_vi="m", example_sentence="e", priority="P1",
        source_question_id=ctx["qvb"].id, status="pending_review",
        origin="ai_generated", answer_provenance="ai_inferred",
        ai_confidence=0.5, dedup_hash="lowconf2-hash", created_by=ctx["teacher"].id)
    db.add(low2)
    db.commit()
    r = c.post("/api/v1/learn/atoms/bulk-approve", headers=ctx["tok_t"],
               json={"atom_ids": [str(low2.id)]})
    assert r.status_code == 200
    assert r.json()["approved"] == []
    assert r.json()["skipped"][0]["code"] == "ATOM_LOW_CONFIDENCE"


def test_atom_list_filters_and_pending_count(ctx):
    c = ctx["client"]
    r = c.get("/api/v1/learn/atoms?status=pending_review", headers=ctx["tok_t"])
    assert r.status_code == 200
    body = r.json()
    assert body["pending_total"] >= 1
    assert all(a["status"] == "pending_review" for a in body["items"])
    r = c.get(f"/api/v1/learn/atoms?source_question_id={ctx['q7b'].id}",
              headers=ctx["tok_t"])
    assert r.json()["total"] >= 2


# ------------------------------------------------------------------ EL-201
def test_draft_content_not_visible_to_student(ctx):
    c = ctx["client"]
    r = c.get(f"/api/v1/learn/attempts/{ctx['attempt_released']}/post-test",
              headers=ctx["tok_s"])
    assert r.status_code == 200, r.text
    items = {i["question_id"]: i for i in r.json()["items"]}
    assert str(ctx["q7b"].id) in items  # câu sai có trong danh sách
    assert str(ctx["qvb"].id) not in items  # câu đúng chắc chắn không có hậu-đề
    assert items[str(ctx["q7b"].id)]["content_status"] == "preparing"
    r = c.get(f"/api/v1/learn/attempts/{ctx['attempt_released']}/post-test/{ctx['q7b'].id}",
              headers=ctx["tok_s"])
    assert r.status_code == 200
    assert r.json()["content_status"] == "preparing" and r.json()["steps"] is None
    # không một payload HS nào chứa nội dung hạt draft
    blob = str(r.json())
    assert "number of" not in blob and "l1_transfer" not in blob


def test_post_test_release_gate(ctx):
    c = ctx["client"]
    r = c.get(f"/api/v1/learn/attempts/{ctx['attempt_locked']}/post-test",
              headers=ctx["tok_s"])
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "ANSWER_NOT_RELEASED"


@pytest.fixture(scope="module")
def approved_flow(ctx):
    """GV duyệt atom 'number' + nội dung hậu-đề Q7 + sinh & duyệt biến thể P2."""
    c, db = ctx["client"], ctx["db"]
    atoms = db.query(LearningAtom).filter_by(source_question_id=ctx["q7b"].id).all()
    atom_number = next(a for a in atoms if a.headword == "number")
    # câu fixture không có provenance đáp án -> atom mang cờ
    # needs_teacher_confirmation, GV xác nhận tường minh mới duyệt được
    assert atom_number.needs_teacher_confirmation is True
    r = c.post(f"/api/v1/learn/atoms/{atom_number.id}/approve",
               headers=ctx["tok_t"], json={"confirm_answer": True})
    assert r.status_code == 200, r.text
    pc = db.query(PostTestContent).filter_by(question_id=ctx["q7b"].id).one()
    r = c.post(f"/api/v1/learn/post-test-contents/{pc.id}/approve",
               headers=ctx["tok_t"], json={"confirm_answer": True})
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/learn/atoms/{atom_number.id}/variant-generation-jobs",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 201, r.text
    variant_id = r.json()["variant_id"]
    r = c.post(f"/api/v1/learn/variants/{variant_id}/approve",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 200, r.text
    var = db.get(VariantItem, uuid.UUID(variant_id))
    correct_opt = str(var.correct_option_id)
    wrong_opt = next(str(o.id) for o in db.query(VariantOption)
                     .filter_by(variant_id=var.id).all() if str(o.id) != correct_opt)
    return {"atom_number": atom_number, "variant_id": variant_id,
            "variant_correct": correct_opt, "variant_wrong": wrong_opt}


def test_post_test_four_steps_server_gated(ctx, approved_flow):
    c, db = ctx["client"], ctx["db"]
    att, qid = ctx["attempt_released"], str(ctx["q7b"].id)
    base = f"/api/v1/learn/attempts/{att}/post-test/{qid}"

    r = c.get(base, headers=ctx["tok_s"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content_status"] == "ready"
    assert body["steps"]["step2"]["locked"] is True
    assert "cue" not in body["steps"]["step2"]  # khoá ở server, không chỉ ẩn UI
    # chẩn đoán lộ đáp án? options không chứa key đúng
    assert "correct_diagnosis_key" not in str(body)

    # bước 2 bị khoá khi chưa xong bước 1
    r = c.post(base + "/step", headers=ctx["tok_s"], json={"step": 2})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STEP_LOCKED"
    # bước 1 sai -> không tiến
    r = c.post(base + "/step", headers=ctx["tok_s"],
               json={"step": 1, "choice_key": "surface_match"})
    assert r.status_code == 200 and r.json()["is_correct"] is False
    assert r.json()["progress"]["current_step"] == 0
    # bước 1 đúng (Q7: L1 — dịch từ tiếng Việt)
    r = c.post(base + "/step", headers=ctx["tok_s"],
               json={"step": 1, "choice_key": "l1_transfer"})
    assert r.json()["is_correct"] is True
    assert r.json()["progress"]["current_step"] == 1
    # giờ bước 2 mở được nội dung
    r = c.get(base, headers=ctx["tok_s"])
    assert r.json()["steps"]["step2"]["locked"] is False
    assert "a number of" in r.json()["steps"]["step2"]["cue"]
    # bước 3 bị khoá khi chưa xác nhận bước 2
    r = c.post(base + "/step", headers=ctx["tok_s"],
               json={"step": 3, "selected_keys": ["s1", "s3"]})
    assert r.status_code == 409
    r = c.post(base + "/step", headers=ctx["tok_s"], json={"step": 2})
    assert r.json()["progress"]["current_step"] == 2
    # bước 3: chọn thiếu 1 câu đúng -> sai; chọn đúng cả 2 -> qua
    r = c.post(base + "/step", headers=ctx["tok_s"],
               json={"step": 3, "selected_keys": ["s1"]})
    assert r.json()["is_correct"] is False
    r = c.post(base + "/step", headers=ctx["tok_s"],
               json={"step": 3, "selected_keys": ["s1", "s3"]})
    assert r.json()["is_correct"] is True
    assert r.json()["progress"]["current_step"] == 3
    # bước 4: biến thể hiện ra (đã duyệt), không lộ correct_option_id
    r = c.get(base, headers=ctx["tok_s"])
    var = r.json()["steps"]["step4"]["variant"]
    assert var and var["variant_id"] == approved_flow["variant_id"]
    assert "correct" not in str(var)
    # trả lời sai -> chưa hoàn thành
    r = c.post(base + "/variant-answer", headers=ctx["tok_s"], json={
        "variant_id": approved_flow["variant_id"],
        "selected_variant_option_id": approved_flow["variant_wrong"],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200 and r.json()["is_correct"] is False
    assert r.json()["progress"]["status"] == "in_progress"
    # trả lời đúng -> hoàn thành cả 4 bước
    r = c.post(base + "/variant-answer", headers=ctx["tok_s"], json={
        "variant_id": approved_flow["variant_id"],
        "selected_variant_option_id": approved_flow["variant_correct"],
        "client_uuid": str(uuid.uuid4())})
    assert r.json()["is_correct"] is True
    assert r.json()["progress"]["status"] == "completed"
    prog = db.query(PostTestProgress).filter_by(
        attempt_id=uuid.UUID(att), question_id=ctx["q7b"].id).one()
    assert prog.current_step == 4 and prog.status == "completed"
    # tiến độ bền qua 'tải lại trang' (GET lại từ đầu)
    r = c.get(f"/api/v1/learn/attempts/{att}/post-test", headers=ctx["tok_s"])
    item = next(i for i in r.json()["items"] if i["question_id"] == qid)
    assert item["progress"]["status"] == "completed"
    # variant_attempts đã ghi 2 lượt; FSRS chưa bị đụng (Sprint 3)
    assert db.query(VariantAttempt).filter_by(
        student_user_id=uuid.UUID(ctx["student_id"])).count() == 2
    assert db.query(ReviewCard).count() == 0 and db.query(ReviewLog).count() == 0


def test_variant_of_unapproved_atom_not_reachable(ctx):
    c, db = ctx["client"], ctx["db"]
    # biến thể T1 của atom 'number' vẫn pending_review -> HS không chấm được
    atom = next(a for a in db.query(LearningAtom)
                .filter_by(source_question_id=ctx["q7b"].id, headword="number"))
    var = db.query(VariantItem).filter_by(parent_atom_id=atom.id,
                                          variant_tier="T1").first()
    r = c.post(f"/api/v1/learn/variants/{var.id}/answer", headers=ctx["tok_s"],
               json={"selected_variant_option_id": str(var.correct_option_id),
                     "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 404


def test_exam_level_cap_120(ctx):
    c, db = ctx["client"], ctx["db"]
    se = SourceExam(workspace_id=ctx["ws"].id, title="Đề lớn 45 câu", grade=11,
                    created_by=ctx["teacher"].id)
    db.add(se)
    db.flush()
    for i in range(1, 46):
        _mk_question(db, ctx["ws"], ctx["teacher"], se, i,
                     f"Câu {i}: chọn từ đúng — a growing ___ of families",
                     "B", [("A", "amount"), ("B", "number"),
                           ("C", "level"), ("D", "range")])
    db.commit()
    r = c.post(f"/api/v1/learn/source-exams/{se.id}/atom-generation",
               headers=ctx["tok_t"], json={})
    assert r.status_code == 200, r.text
    body = r.json()
    qids = [q.id for q in db.query(QuestionItem).filter_by(source_exam_id=se.id)]
    total = db.query(LearningAtom).filter(
        LearningAtom.source_question_id.in_(qids)).count()
    assert total <= 120
    assert body["atoms_total"] == total
