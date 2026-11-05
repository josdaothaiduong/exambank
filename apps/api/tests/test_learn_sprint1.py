"""Learn Sprint 1 (EL-101..EL-104) — test qua HTTP thật (TestClient + override DB).

Bao phủ bắt buộc: RBAC 404, consent 403 CONSENT_REQUIRED, giao đề 422
QUESTIONS_NOT_APPROVED, snapshot/payload không lộ đáp án, chấm server với
fixture 40 câu, idempotent submit, cổng answer_release_at.
"""
import json
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
    Assignment, Attempt, ClassMembership, ConsentRecord, EnrollmentRequest,
    Exam, ExamItem, ExamVersion, LearnClass, Option, ParentLink, ParentProfile,
    PassageGroup, QuestionItem, QuestionStatus, SourceExam, StudentProfile,
    User, Workspace,
)
from app.security import create_access_token, hash_password

TABLES = [t.__table__ for t in (
    User, Workspace, SourceExam, PassageGroup, QuestionItem, Option,
    Exam, ExamVersion, ExamItem, StudentProfile, ParentProfile, LearnClass,
    ClassMembership, ParentLink, ConsentRecord, Assignment, Attempt,
    __import__("app.models", fromlist=["AttemptItem"]).AttemptItem,
    EnrollmentRequest)]

NOW = datetime.now(timezone.utc)


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

    teacher = User(email="gv@truong.edu", full_name="GV Chính",
                   password_hash=hash_password("teacher-pass"), role="teacher")
    teacher2 = User(email="gv2@truong.edu", full_name="GV Khác",
                    password_hash=hash_password("teacher2-pass"), role="teacher")
    db.add_all([teacher, teacher2])
    db.flush()
    ws = Workspace(owner_id=teacher.id, name="WS GV")
    ws2 = Workspace(owner_id=teacher2.id, name="WS GV2")
    db.add_all([ws, ws2])
    db.commit()

    def tok(u):
        return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}

    out = {"client": client, "db": db, "teacher": teacher, "teacher2": teacher2,
           "ws": ws, "tok_t": tok(teacher), "tok_t2": tok(teacher2)}

    # --- lớp A + 2 HS qua API (EL-101)
    r = client.post("/api/v1/learn/classes", headers=out["tok_t"], json={
        "name": "11A2", "grade": 11, "school_year": "2026-2027"})
    assert r.status_code == 201, r.text
    out["class_a"] = r.json()
    r = client.post(f"/api/v1/learn/classes/{out['class_a']['id']}/students",
                    headers=out["tok_t"], json={"students": [
                        {"display_name": "Minh Anh", "birth_year": 2009},
                        {"display_name": "Tuấn Kiệt", "birth_year": 2009}]})
    assert r.status_code == 201, r.text
    out["students_a"] = r.json()["created"]

    def login(email, pw):
        rr = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
        assert rr.status_code == 200, rr.text
        return {"Authorization": f"Bearer {rr.json()['access_token']}"}

    s1 = out["students_a"][0]
    out["tok_s1"] = login(s1["login_email"], s1["initial_password_once"])
    out["s1_id"] = s1["student_user_id"]
    s2 = out["students_a"][1]
    out["tok_s2"] = login(s2["login_email"], s2["initial_password_once"])
    out["s2_id"] = s2["student_user_id"]
    out["s2_login"] = s2

    # --- đề gốc + 40 câu approved có đáp án (fixture chấm điểm)
    se = SourceExam(workspace_id=ws.id, title="UNIT 1 TEST 1", grade=11,
                    created_by=teacher.id)
    db.add(se)
    db.flush()
    out["correct_ids"] = {}
    out["wrong_ids"] = {}
    for i in range(1, 41):
        q = QuestionItem(workspace_id=ws.id, source_exam_id=se.id,
                         question_type="cloze", order_in_source=i,
                         stem_html=f"Câu {i} stem", stem_text=f"Câu {i} stem",
                         status=QuestionStatus.approved,
                         dedup_hash=f"learn-s1-{i}", created_by=teacher.id)
        db.add(q)
        db.flush()
        opts = []
        for j, label in enumerate("ABCD"):
            o = Option(question_id=q.id, label=label,
                       content_html=f"opt {label} câu {i}",
                       content_text=f"opt {label} câu {i}", position=j)
            db.add(o)
            opts.append(o)
        db.flush()
        q.correct_option_id = opts[i % 4].id
        out["correct_ids"][str(q.id)] = str(opts[i % 4].id)
        out["wrong_ids"][str(q.id)] = str(opts[(i + 1) % 4].id)
    out["source_exam"] = se
    # đề xấu: 1 câu chưa duyệt
    se_bad = SourceExam(workspace_id=ws.id, title="Đề chưa duyệt", grade=11,
                        created_by=teacher.id)
    db.add(se_bad)
    db.flush()
    qb = QuestionItem(workspace_id=ws.id, source_exam_id=se_bad.id,
                      question_type="cloze", order_in_source=1,
                      stem_html="bad", stem_text="bad",
                      status=QuestionStatus.pending_review,
                      dedup_hash="learn-s1-bad", created_by=teacher.id)
    db.add(qb)
    db.commit()
    out["bad_question_id"] = str(qb.id)
    out["bad_source_id"] = str(se_bad.id)
    yield out
    app.dependency_overrides.pop(get_db, None)


def _assignment_body(ctx, **kw):
    body = {"class_id": ctx["class_a"]["id"],
            "source_exam_id": str(ctx["source_exam"].id),
            "mode": "paper_quick_entry",
            "opens_at": (NOW - timedelta(hours=1)).isoformat(),
            "due_at": (NOW + timedelta(days=1)).isoformat(),
            "answer_release_at": (NOW + timedelta(hours=1)).isoformat()}
    body.update(kw)
    return body


@pytest.fixture(scope="module")
def published(ctx):
    """Assignment chính đã publish (release ở tương lai)."""
    c = ctx["client"]
    r = c.post("/api/v1/learn/assignments", headers=ctx["tok_t"],
               json=_assignment_body(ctx))
    assert r.status_code == 201, r.text
    a = r.json()
    r = c.post(f"/api/v1/learn/assignments/{a['id']}/publish", headers=ctx["tok_t"])
    assert r.status_code == 200, r.text
    assert r.json()["question_count"] == 40
    ctx["assignment"] = a
    return a


# ------------------------------------------------------------------ EL-101
def test_rbac_404_cross_workspace_and_cross_class(ctx):
    c = ctx["client"]
    # GV khác workspace xem roster lớp A -> 404
    r = c.get(f"/api/v1/learn/classes/{ctx['class_a']['id']}/students",
              headers=ctx["tok_t2"])
    assert r.status_code == 404
    # HS gọi endpoint của GV -> 403 FORBIDDEN_ROLE
    r = c.get(f"/api/v1/learn/classes/{ctx['class_a']['id']}/students",
              headers=ctx["tok_s1"])
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FORBIDDEN_ROLE"


def test_consent_gate_403_then_active(ctx, published):
    c = ctx["client"]
    # Chưa đồng ý gì -> tạo attempt bị chặn 403 CONSENT_REQUIRED
    r = c.post(f"/api/v1/learn/assignments/{published['id']}/attempts",
               headers=ctx["tok_s1"], json={"client_uuid": str(uuid.uuid4())})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "CONSENT_REQUIRED"
    # Chỉ đồng ý của HS -> vẫn chưa đủ
    r = c.post("/api/v1/learn/my/consent", headers=ctx["tok_s1"],
               json={"policy_version": "v1-2026"})
    assert r.status_code == 200, r.text
    assert r.json()["profile_status"] == "pending_consent"
    r = c.post(f"/api/v1/learn/assignments/{published['id']}/attempts",
               headers=ctx["tok_s1"], json={"client_uuid": str(uuid.uuid4())})
    assert r.status_code == 403
    # GV ghi nhận phiếu giấy (đủ chữ ký 2 phía) -> active
    r = c.post(f"/api/v1/learn/students/{ctx['s1_id']}/paper-consent",
               headers=ctx["tok_t"], json={"policy_version": "v1-2026"})
    assert r.status_code == 200, r.text
    assert r.json()["profile_status"] == "active"


def test_parent_claim_flow_and_consent(ctx):
    c = ctx["client"]
    # GV tạo liên kết cho HS2
    r = c.post(f"/api/v1/learn/classes/{ctx['class_a']['id']}/parent-links",
               headers=ctx["tok_t"],
               json={"student_user_id": ctx["s2_id"], "relation": "mother"})
    assert r.status_code == 201, r.text
    code = f"{ctx['class_a']['join_code']}:{ctx['s2_login']['login_email']}"
    r = c.post("/api/v1/learn/parent-links/claim", json={
        "link_code": code, "email": "me@phuhuynh.vn", "password": "parent-pass-1",
        "full_name": "Mẹ Tuấn Kiệt", "confirm_consent": True})
    assert r.status_code == 200, r.text
    tok_p = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = c.get("/api/v1/learn/my/children", headers=tok_p)
    assert r.status_code == 200
    assert [x["student_user_id"] for x in r.json()] == [ctx["s2_id"]]
    # HS2: đã có parent_guardian, tự ghi student_self -> active
    r = c.post("/api/v1/learn/my/consent", headers=ctx["tok_s2"],
               json={"policy_version": "v1-2026"})
    assert r.json()["profile_status"] == "active"


def test_enrollment_hybrid_queue(ctx):
    c = ctx["client"]
    r = c.post("/api/v1/learn/enrollment-requests", json={
        "join_code": ctx["class_a"]["join_code"], "display_name": "Học Sinh Mới",
        "birth_year": 2010})
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    r = c.post("/api/v1/learn/enrollment-requests", json={
        "join_code": "XXXXXX", "display_name": "Sai Mã"})
    assert r.status_code == 404
    r = c.get(f"/api/v1/learn/classes/{ctx['class_a']['id']}/enrollment-requests",
              headers=ctx["tok_t"])
    assert any(x["id"] == req_id for x in r.json())
    r = c.post(f"/api/v1/learn/enrollment-requests/{req_id}/decision",
               headers=ctx["tok_t"], json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["initial_password_once"]
    # HS mới có membership nhưng chưa consent -> vẫn bị cổng consent chặn (đúng thiết kế)
    r = c.post("/api/v1/auth/login", json={
        "email": r.json()["login_email"],
        "password": r.json()["initial_password_once"]})
    assert r.status_code == 200


# ------------------------------------------------------------------ EL-102
def test_publish_blocked_422_for_unapproved(ctx):
    c = ctx["client"]
    r = c.post("/api/v1/learn/assignments", headers=ctx["tok_t"],
               json=_assignment_body(ctx, source_exam_id=ctx["bad_source_id"]))
    assert r.status_code == 201, r.text
    r = c.post(f"/api/v1/learn/assignments/{r.json()['id']}/publish",
               headers=ctx["tok_t"])
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "QUESTIONS_NOT_APPROVED"
    assert detail["question_ids"] == [ctx["bad_question_id"]]


def test_snapshot_has_no_answers(ctx, published):
    db = ctx["db"]
    a = db.get(Assignment, uuid.UUID(published["id"]))
    blob = json.dumps(a.student_snapshot_json)
    assert "correct_option_id" not in blob
    assert "is_correct" not in blob
    assert "explanation" not in blob
    assert len(a.student_snapshot_json["questions"]) == 40


def test_exam_version_assignment_publish(ctx):
    c, db = ctx["client"], ctx["db"]
    exam = Exam(workspace_id=ctx["ws"].id, title="Đề sinh từ ExamBank",
                created_by=ctx["teacher"].id)
    db.add(exam)
    db.flush()
    ver = ExamVersion(exam_id=exam.id, code="001", answer_balance={})
    db.add(ver)
    db.flush()
    qs = (db.query(QuestionItem)
          .filter_by(source_exam_id=ctx["source_exam"].id)
          .order_by(QuestionItem.order_in_source).limit(3).all())
    for pos, q in enumerate(qs, start=1):
        db.add(ExamItem(exam_version_id=ver.id, question_id=q.id,
                        passage_id=q.passage_id, position=pos, snapshot_json={}))
    db.commit()
    body = _assignment_body(ctx, source_exam_id=None,
                            exam_version_id=str(ver.id), mode="online")
    r = c.post("/api/v1/learn/assignments", headers=ctx["tok_t"], json=body)
    assert r.status_code == 201, r.text
    r = c.post(f"/api/v1/learn/assignments/{r.json()['id']}/publish",
               headers=ctx["tok_t"])
    assert r.status_code == 200, r.text
    assert r.json()["question_count"] == 3


# ------------------------------------------------------------- EL-103 / EL-104
def test_attempt_flow_grading_40_and_release_gate(ctx, published):
    c = ctx["client"]
    aid = published["id"]
    # HS lớp khác (HS mới qua enrollment, chưa consent) -> attempt bị consent chặn;
    # dùng HS1 đã active. Tạo attempt (paper entry)
    cu = str(uuid.uuid4())
    r = c.post(f"/api/v1/learn/assignments/{aid}/attempts", headers=ctx["tok_s1"],
               json={"client_uuid": cu, "entry_method": "paper_entry"})
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["entry_method"] == "quick_entry"
    assert len(att["questions"]) == 40
    assert "correct_option_id" not in r.text and "is_correct" not in r.text
    # Tạo lại cùng client_uuid -> cùng attempt (idempotent)
    r2 = c.post(f"/api/v1/learn/assignments/{aid}/attempts", headers=ctx["tok_s1"],
                json={"client_uuid": cu})
    assert r2.json()["attempt_id"] == att["attempt_id"]
    # HS2 xem attempt của HS1 -> 404
    r = c.get(f"/api/v1/learn/attempts/{att['attempt_id']}", headers=ctx["tok_s2"])
    assert r.status_code == 404
    # Tự lưu nháp 5 câu
    answers = []
    for q in att["questions"][:5]:
        answers.append({"question_id": q["question_id"],
                        "selected_option_id": ctx["correct_ids"][q["question_id"]]})
    r = c.patch(f"/api/v1/learn/attempts/{att['attempt_id']}/answers",
                headers=ctx["tok_s1"], json={"answers": answers})
    assert r.status_code == 200 and r.json()["answered_count"] == 5
    # Nộp: 30 đúng (gồm 5 câu nháp), 10 sai
    full = []
    for i, q in enumerate(att["questions"]):
        full.append({"question_id": q["question_id"],
                     "selected_option_id": ctx["correct_ids"][q["question_id"]]
                     if i < 30 else ctx["wrong_ids"][q["question_id"]]})
    r = c.post(f"/api/v1/learn/attempts/{att['attempt_id']}/submit",
               headers=ctx["tok_s1"], json={"client_uuid": cu, "answers": full})
    assert r.status_code == 200, r.text
    body = r.json()
    # Chưa tới answer_release_at + không show_score_immediately -> không điểm/kết quả
    assert body["status"] == "graded" and body["answer_released"] is False
    assert "score_raw" not in body and "results" not in body
    # Nộp lại cùng client_uuid -> idempotent 200; khác uuid -> 409
    r = c.post(f"/api/v1/learn/attempts/{att['attempt_id']}/submit",
               headers=ctx["tok_s1"], json={"client_uuid": cu})
    assert r.status_code == 200
    r = c.post(f"/api/v1/learn/attempts/{att['attempt_id']}/submit",
               headers=ctx["tok_s1"], json={"client_uuid": str(uuid.uuid4())})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ATTEMPT_ALREADY_SUBMITTED"
    # GV mở release về quá khứ -> HS xem được điểm 30/40 và kết quả từng câu
    r = c.patch(f"/api/v1/learn/assignments/{aid}", headers=ctx["tok_t"],
                json={"answer_release_at": (NOW - timedelta(minutes=5)).isoformat()})
    assert r.status_code == 200, r.text
    r = c.get(f"/api/v1/learn/attempts/{att['attempt_id']}/result",
              headers=ctx["tok_s1"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["score_raw"] == 30 and body["score_max"] == 40
    assert sum(1 for x in body["results"] if x["is_correct"]) == 30
    ctx["attempt_id"] = att["attempt_id"]


def test_online_mode_attempt_uses_same_api(ctx):
    c = ctx["client"]
    body = _assignment_body(ctx, mode="online",
                            answer_release_at=(NOW - timedelta(minutes=1)).isoformat())
    r = c.post("/api/v1/learn/assignments", headers=ctx["tok_t"], json=body)
    assert r.status_code == 201
    aid = r.json()["id"]
    r = c.post(f"/api/v1/learn/assignments/{aid}/publish", headers=ctx["tok_t"])
    assert r.status_code == 200
    r = c.post(f"/api/v1/learn/assignments/{aid}/attempts", headers=ctx["tok_s2"],
               json={"client_uuid": str(uuid.uuid4()), "mode": "online"})
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["entry_method"] == "online"
    q0 = att["questions"][0]
    r = c.patch(f"/api/v1/learn/attempts/{att['attempt_id']}/answer",
                headers=ctx["tok_s2"],
                json={"question_id": q0["question_id"],
                      "selected_option_id": ctx["correct_ids"][q0["question_id"]]})
    assert r.status_code == 200
    r = c.post(f"/api/v1/learn/attempts/{att['attempt_id']}/submit",
               headers=ctx["tok_s2"], json={})
    assert r.status_code == 200
    # Đã release -> có điểm ngay: đúng 1/40
    assert r.json()["score_raw"] == 1
