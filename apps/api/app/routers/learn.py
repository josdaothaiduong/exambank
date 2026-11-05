"""ExamBank Learn — Sprint 1 (EL-101..EL-104).

Router gộp một file `learn.py` (đề xuất spec tách 4 file learn_teacher/student/
parent/atoms — Sprint 1 chỉ gồm luồng GV-lớp + HS-làm bài nên gộp 1 file cho dễ
theo dõi; tách file khi Sprint 2/3 thêm atoms/review-cards).

Quy tắc bất biến (DB-API-SPEC mục 1.2):
- R1: chỉ câu `approved` + có đáp án (question_items.correct_option_id) mới được
  publish tới HS — cổng duy nhất là POST /assignments/{id}/publish.
- R2: đáp án không rời server trước `answer_release_at` — snapshot giao HS đã
  lọc đáp án, chấm ở server, kết quả từng câu chỉ trả sau release.
- R3: (review_logs — Sprint 3.)

Kiểm quyền 3 lớp: role ∧ workspace ∧ quan hệ. Ngoài quan hệ -> 404.
Mã lỗi theo spec 3.0: detail là dict {"code": ..., "message": ...}.
"""
import random
import secrets
import string
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.learn import content_pipeline
from app.models import (
    AIGenerationJob, Assignment, AtomSource, Attempt, AttemptItem, AuditLog,
    ClassMembership, ConsentRecord, EnrollmentRequest, Exam, ExamItem,
    ExamVersion, LearnClass, LearningAtom, Option, ParentLink, ParentProfile,
    PassageGroup, PostTestContent, PostTestProgress, QuestionItem,
    QuestionStatus, SourceExam, StudentProfile, User, VariantAttempt,
    VariantItem, VariantOption, Workspace,
)
from app.security import hash_password

router = APIRouter(prefix="/api/v1/learn", tags=["learn"])

POLICY_VERSION = "v1-2026"


# ---------------------------------------------------------------- lỗi / quyền
def err(code_status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(code_status, {"code": code, "message": message, **extra})


def not_found(what: str = "Không tìm thấy") -> HTTPException:
    return err(status.HTTP_404_NOT_FOUND, "NOT_FOUND", what)


def require_role(user: User, *roles: str):
    if user.role not in roles:
        raise err(status.HTTP_403_FORBIDDEN, "FORBIDDEN_ROLE",
                  f"Vai trò {user.role} không được gọi endpoint này")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def teacher_workspace(db: Session, user: User) -> Workspace:
    ws = (db.query(Workspace).filter_by(owner_id=user.id)
          .order_by(Workspace.created_at).first())
    if ws is None:
        raise not_found("Không tìm thấy workspace")
    return ws


def owned_class(db: Session, user: User, class_id: uuid.UUID) -> LearnClass:
    ws = teacher_workspace(db, user)
    cls = db.get(LearnClass, class_id)
    if cls is None or cls.workspace_id != ws.id or cls.owner_teacher_id != user.id:
        raise not_found("Không tìm thấy lớp")
    return cls


def student_profile(db: Session, student_user_id: uuid.UUID) -> StudentProfile | None:
    return db.query(StudentProfile).filter_by(user_id=student_user_id).one_or_none()


def granted_consent_types(db: Session, student_user_id: uuid.UUID) -> set[str]:
    rows = (db.query(ConsentRecord.consent_type)
            .filter_by(student_user_id=student_user_id)
            .filter(ConsentRecord.withdrawn_at.is_(None)).all())
    return {r[0] for r in rows}


def refresh_profile_status(db: Session, student_user_id: uuid.UUID):
    prof = student_profile(db, student_user_id)
    if prof is None or prof.status == "disabled":
        return
    prof.status = ("active" if {"student_self", "parent_guardian"}
                   <= granted_consent_types(db, student_user_id)
                   else "pending_consent")


def require_learning_access(db: Session, student: User):
    """Cổng đồng ý kép cho mọi endpoint học tập của HS (spec 3.0)."""
    if not {"student_self", "parent_guardian"} <= granted_consent_types(db, student.id):
        raise err(status.HTTP_403_FORBIDDEN, "CONSENT_REQUIRED",
                  "Chưa đủ đồng ý của học sinh và phụ huynh/người giám hộ")


def add_consent(db: Session, *, workspace_id, student_user_id, consenter_user_id,
                consent_type: str, method: str, recorded_by=None,
                policy_version: str = POLICY_VERSION) -> ConsentRecord:
    rec = ConsentRecord(
        workspace_id=workspace_id, student_user_id=student_user_id,
        consenter_user_id=consenter_user_id, consent_type=consent_type,
        consent_scope={"purposes": ["learning_data"]},
        policy_version=policy_version, method=method, recorded_by=recorded_by)
    db.add(rec)
    db.flush()
    refresh_profile_status(db, student_user_id)
    return rec


def _gen_join_code(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not db.query(LearnClass).filter_by(join_code=code).one_or_none():
            return code
    raise RuntimeError("Không sinh được join_code")


def _gen_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(10))


def _new_student_user(db: Session, display_name: str, password: str | None):
    code = "s-" + uuid.uuid4().hex[:8]
    email = f"{code}@learn.exambank.local"
    pw = password or _gen_password()
    u = User(email=email, full_name=display_name,
             password_hash=hash_password(pw), role="student")
    db.add(u)
    db.flush()
    return u, code, pw


# ---------------------------------------------------------------- schemas
class ClassIn(BaseModel):
    name: str = Field(min_length=1)
    grade: int = Field(ge=10, le=12)
    school_year: str = Field(min_length=1)
    desired_retention: float | None = Field(default=None, ge=0.85, le=0.95)


class ClassPatchIn(BaseModel):
    name: str | None = None
    grade: int | None = Field(default=None, ge=10, le=12)
    school_year: str | None = None
    desired_retention: float | None = Field(default=None, ge=0.85, le=0.95)
    archived: bool | None = None


class StudentIn(BaseModel):
    display_name: str = Field(min_length=1)
    birth_year: int = Field(ge=1990, le=2100)
    school_class_name: str | None = None
    password: str | None = Field(default=None, min_length=6)


class StudentsIn(BaseModel):
    students: list[StudentIn]


class ConsentIn(BaseModel):
    policy_version: str = POLICY_VERSION


class PaperConsentIn(BaseModel):
    policy_version: str = POLICY_VERSION
    granted_at: datetime | None = None


class ParentLinkCreateIn(BaseModel):
    student_user_id: uuid.UUID
    relation: str = "guardian"
    parent_display_name: str | None = None


class ParentLinkClaimIn(BaseModel):
    link_code: str
    email: str
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    confirm_consent: bool = True


class EnrollmentRequestIn(BaseModel):
    join_code: str
    display_name: str = Field(min_length=1)
    birth_year: int | None = Field(default=None, ge=1990, le=2100)
    email: str | None = None
    password: str | None = Field(default=None, min_length=8)
    message: str | None = None


class EnrollmentDecisionIn(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")


# ---------------------------------------------------------------- đầu ra
def _class_out(db: Session, cls: LearnClass) -> dict:
    count = (db.query(ClassMembership)
             .filter_by(class_id=cls.id)
             .filter(ClassMembership.left_at.is_(None)).count())
    return {"id": str(cls.id), "workspace_id": str(cls.workspace_id),
            "name": cls.name, "grade": cls.grade, "school_year": cls.school_year,
            "join_code": cls.join_code,
            "desired_retention": float(cls.desired_retention),
            "student_count": count,
            "archived": cls.archived_at is not None}


def _student_out(db: Session, prof: StudentProfile) -> dict:
    types = granted_consent_types(db, prof.user_id)
    return {"student_user_id": str(prof.user_id),
            "display_name": prof.display_name, "birth_year": prof.birth_year,
            "school_class_name": prof.school_class_name, "status": prof.status,
            "consent": {"student_self": "student_self" in types,
                        "parent_guardian": "parent_guardian" in types}}


# ================================================================= EL-101: lớp
@router.post("/classes", status_code=status.HTTP_201_CREATED)
def create_class(body: ClassIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    ws = teacher_workspace(db, user)
    if db.query(LearnClass).filter_by(workspace_id=ws.id, name=body.name,
                                      school_year=body.school_year).one_or_none():
        raise err(status.HTTP_409_CONFLICT, "VALIDATION_ERROR",
                  "Lớp trùng tên trong năm học này")
    cls = LearnClass(workspace_id=ws.id, owner_teacher_id=user.id,
                     name=body.name, grade=body.grade,
                     school_year=body.school_year, join_code=_gen_join_code(db),
                     desired_retention=body.desired_retention or 0.90)
    db.add(cls)
    db.commit()
    db.refresh(cls)
    return _class_out(db, cls)


@router.get("/classes")
def list_classes(db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    ws = teacher_workspace(db, user)
    rows = (db.query(LearnClass).filter_by(workspace_id=ws.id)
            .order_by(LearnClass.created_at).all())
    return [_class_out(db, c) for c in rows]


@router.patch("/classes/{class_id}")
def update_class(class_id: uuid.UUID, body: ClassPatchIn,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    cls = owned_class(db, user, class_id)
    if body.name is not None:
        cls.name = body.name
    if body.grade is not None:
        cls.grade = body.grade
    if body.school_year is not None:
        cls.school_year = body.school_year
    if body.desired_retention is not None:
        cls.desired_retention = body.desired_retention
    if body.archived is not None:
        cls.archived_at = _now() if body.archived else None
    db.commit()
    db.refresh(cls)
    return _class_out(db, cls)


# ------------------------------------------------------------- EL-101: học sinh
@router.post("/classes/{class_id}/students", status_code=status.HTTP_201_CREATED)
def add_students(class_id: uuid.UUID, body: StudentsIn,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    cls = owned_class(db, user, class_id)
    created = []
    for s in body.students:
        u, code, pw = _new_student_user(db, s.display_name, s.password)
        prof = StudentProfile(user_id=u.id, workspace_id=cls.workspace_id,
                              display_name=s.display_name,
                              birth_year=s.birth_year,
                              school_class_name=s.school_class_name)
        db.add(prof)
        db.add(ClassMembership(class_id=cls.id, student_user_id=u.id,
                               source="teacher_added"))
        created.append({"student_user_id": str(u.id), "student_code": code,
                        "login_email": u.email,
                        "initial_password_once": pw,
                        "display_name": s.display_name})
    db.commit()
    return {"created": created}


@router.get("/classes/{class_id}/students")
def list_students(class_id: uuid.UUID, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    cls = owned_class(db, user, class_id)
    profs = (db.query(StudentProfile)
             .join(ClassMembership, ClassMembership.student_user_id == StudentProfile.user_id)
             .filter(ClassMembership.class_id == cls.id,
                     ClassMembership.left_at.is_(None))
             .order_by(StudentProfile.display_name).all())
    return [_student_out(db, p) for p in profs]


@router.post("/classes/{class_id}/students/{student_user_id}/reset-password")
def reset_student_password(class_id: uuid.UUID, student_user_id: uuid.UUID,
                           db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    cls = owned_class(db, user, class_id)
    m = db.query(ClassMembership).filter_by(
        class_id=cls.id, student_user_id=student_user_id).one_or_none()
    stu = db.get(User, student_user_id)
    if m is None or stu is None:
        raise not_found("Không tìm thấy học sinh trong lớp")
    pw = _gen_password()
    stu.password_hash = hash_password(pw)
    db.commit()
    return {"student_user_id": str(stu.id), "initial_password_once": pw}


# ------------------------------------------------------------- đồng ý (A1–A3)
@router.post("/my/consent")
def my_consent(body: ConsentIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    require_role(user, "student")
    prof = student_profile(db, user.id)
    if prof is None:
        raise not_found("Không tìm thấy hồ sơ học sinh")
    add_consent(db, workspace_id=prof.workspace_id, student_user_id=user.id,
                consenter_user_id=user.id, consent_type="student_self",
                method="in_app", policy_version=body.policy_version)
    db.commit()
    return consent_status(db, user.id)


@router.get("/my/consent-status")
def my_consent_status(student_user_id: uuid.UUID | None = Query(default=None),
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    target = student_user_id or user.id
    if target != user.id:
        if user.role == "teacher":
            ws = teacher_workspace(db, user)
            prof = student_profile(db, target)
            if prof is None or prof.workspace_id != ws.id:
                raise not_found()
        elif user.role == "parent":
            link = db.query(ParentLink).filter_by(
                parent_user_id=user.id, student_user_id=target,
                status="active").one_or_none()
            if link is None:
                raise not_found()
        else:
            raise not_found()
    return consent_status(db, target)


def consent_status(db: Session, student_user_id: uuid.UUID) -> dict:
    prof = student_profile(db, student_user_id)
    if prof is None:
        raise not_found("Không tìm thấy hồ sơ học sinh")
    types = granted_consent_types(db, student_user_id)
    return {"student_user_id": str(student_user_id),
            "student_self": "granted" if "student_self" in types else "none",
            "parent_guardian": "granted" if "parent_guardian" in types else "none",
            "profile_status": prof.status}


@router.post("/students/{student_user_id}/paper-consent")
def paper_consent(student_user_id: uuid.UUID, body: PaperConsentIn,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    ws = teacher_workspace(db, user)
    prof = student_profile(db, student_user_id)
    if prof is None or prof.workspace_id != ws.id:
        raise not_found("Không tìm thấy học sinh")
    for ctype in ("student_self", "parent_guardian"):
        add_consent(db, workspace_id=ws.id, student_user_id=student_user_id,
                    consenter_user_id=None, consent_type=ctype,
                    method="paper_form", recorded_by=user.id,
                    policy_version=body.policy_version)
    db.commit()
    return consent_status(db, student_user_id)


# ------------------------------------------------- liên kết phụ huynh (P1/T18)
# Mã liên kết lưu tạm trong ParentLink qua trường approved_by? Không — dùng
# bảng phụ tối thiểu: mã nằm ở `parent_links` không có cột code, nên mã được
# phát sinh và đối chiếu qua một ParentLink ở trạng thái pending với
# relation giữ nguyên; mã tra cứu được mã hoá trong audit? Đơn giản & an toàn
# cho Sprint 1: GV tạo link -> server trả link_code = token; token được lưu
# băm trong consent_scope của một ConsentRecord? Không phù hợp. Thay vào đó:
# link_code chính là id rút gọn + secret lưu ở ParentProfile? Xem bản ghi:
# chúng ta lưu secret vào `parent_links.approved_by` là sai kiểu.
# GIẢI PHÁP SPRINT 1: thêm bảng phụ không cần — dùng EnrollmentRequest? Không.
# Dùng chính trường `join_code` của lớp + student_code: PH claim bằng
# (student_code, join_code) — cả hai đều là mã GV phát cho gia đình.
@router.post("/classes/{class_id}/parent-links", status_code=status.HTTP_201_CREATED)
def create_parent_link(class_id: uuid.UUID, body: ParentLinkCreateIn,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    cls = owned_class(db, user, class_id)
    m = db.query(ClassMembership).filter_by(
        class_id=cls.id, student_user_id=body.student_user_id).one_or_none()
    if m is None:
        raise not_found("Học sinh không thuộc lớp")
    existing = db.query(ParentLink).filter_by(
        student_user_id=body.student_user_id, status="pending").all()
    link = ParentLink(workspace_id=cls.workspace_id,
                      parent_user_id=_placeholder_parent(db, cls),
                      student_user_id=body.student_user_id,
                      relation=body.relation, status="pending")
    db.add(link)
    db.commit()
    db.refresh(link)
    stu = db.get(User, body.student_user_id)
    return {"link_id": str(link.id), "status": link.status,
            "claim_with": {"student_login_email": stu.email if stu else None,
                           "join_code": cls.join_code},
            "note": "PH dùng email đăng nhập của con + join_code của lớp để claim (xem claim_parent_link)"}


def _placeholder_parent(db: Session, cls: LearnClass) -> uuid.UUID:
    """ParentLink.parent_user_id NOT NULL nhưng PH chưa có tài khoản lúc GV tạo
    link. Dùng một user 'pending-parent' dùng chung trong workspace (role=parent,
    không đăng nhập được vì password_hash rỗng) làm giữ chỗ; claim sẽ thay
    parent_user_id bằng PH thật. Ghi rõ đây là nợ kỹ thuật Sprint 1."""
    email = f"pending-parent-{cls.workspace_id}@learn.exambank.local"
    u = db.query(User).filter_by(email=email).one_or_none()
    if u is None:
        u = User(email=email, full_name="(chờ phụ huynh liên kết)",
                 password_hash="", role="parent")
        db.add(u)
        db.flush()
    return u.id


@router.post("/parent-links/claim")
def claim_parent_link(body: ParentLinkClaimIn, db: Session = Depends(get_db)):
    """PH claim: link_code có dạng '<join_code>:<student_login_email>'."""
    try:
        join_code, student_email = body.link_code.split(":", 1)
    except ValueError:
        raise not_found("Mã liên kết không hợp lệ")
    cls = db.query(LearnClass).filter_by(join_code=join_code.strip().upper()).one_or_none()
    stu = db.query(User).filter_by(email=student_email.strip().lower()).one_or_none()
    if cls is None or stu is None:
        raise not_found("Mã liên kết không hợp lệ")
    link = (db.query(ParentLink)
            .filter_by(student_user_id=stu.id, status="pending")
            .order_by(ParentLink.created_at.desc()).first())
    if link is None or link.workspace_id != cls.workspace_id:
        raise not_found("Không có liên kết đang chờ cho học sinh này")
    if db.query(User).filter_by(email=body.email.lower()).one_or_none():
        raise err(status.HTTP_409_CONFLICT, "VALIDATION_ERROR", "Email đã được đăng ký")
    parent = User(email=body.email.lower(), full_name=body.full_name,
                  password_hash=hash_password(body.password), role="parent")
    db.add(parent)
    db.flush()
    db.add(ParentProfile(user_id=parent.id, workspace_id=cls.workspace_id,
                         display_name=body.full_name))
    link.parent_user_id = parent.id
    link.status = "active"
    link.approved_by = cls.owner_teacher_id
    if body.confirm_consent:
        add_consent(db, workspace_id=cls.workspace_id, student_user_id=stu.id,
                    consenter_user_id=parent.id,
                    consent_type="parent_guardian", method="in_app")
    db.commit()
    from app.security import create_access_token
    return {"access_token": create_access_token(str(parent.id)),
            "token_type": "bearer", "link_id": str(link.id), "status": "active"}


@router.get("/my/children")
def my_children(db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_role(user, "parent")
    links = db.query(ParentLink).filter_by(parent_user_id=user.id,
                                            status="active").all()
    out = []
    for lk in links:
        prof = student_profile(db, lk.student_user_id)
        if prof:
            out.append(_student_out(db, prof))
    return out


# ------------------------------------------- đăng ký lai (EL-007 §2, hàng chờ)
@router.post("/enrollment-requests", status_code=status.HTTP_201_CREATED)
def create_enrollment_request(body: EnrollmentRequestIn,
                              db: Session = Depends(get_db)):
    cls = db.query(LearnClass).filter_by(
        join_code=body.join_code.strip().upper()).one_or_none()
    if cls is None or cls.archived_at is not None:
        raise not_found("Mã lớp không hợp lệ")
    requester_id = None
    if body.email and body.password:
        email = body.email.lower()
        existing = db.query(User).filter_by(email=email).one_or_none()
        if existing:
            if existing.role != "student":
                raise err(status.HTTP_409_CONFLICT, "VALIDATION_ERROR",
                          "Email đã được đăng ký")
            requester_id = existing.id
        else:
            u = User(email=email, full_name=body.display_name,
                     password_hash=hash_password(body.password), role="student")
            db.add(u)
            db.flush()
            requester_id = u.id
    req = EnrollmentRequest(
        workspace_id=cls.workspace_id, class_id=cls.id,
        requester_user_id=requester_id, requester_role="student",
        requester_display_name=body.display_name,
        requester_birth_year=body.birth_year,
        join_code_used=cls.join_code, message=body.message, status="pending")
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"id": str(req.id), "status": req.status, "class_id": str(cls.id)}


@router.get("/classes/{class_id}/enrollment-requests")
def list_enrollment_requests(class_id: uuid.UUID,
                             status_filter: str | None = Query(default="pending"),
                             db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    cls = owned_class(db, user, class_id)
    q = db.query(EnrollmentRequest).filter_by(class_id=cls.id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    return [{"id": str(r.id), "display_name": r.requester_display_name,
             "birth_year": r.requester_birth_year, "status": r.status,
             "message": r.message,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in q.order_by(EnrollmentRequest.created_at).all()]


@router.post("/enrollment-requests/{request_id}/decision")
def decide_enrollment_request(request_id: uuid.UUID, body: EnrollmentDecisionIn,
                              db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    req = db.get(EnrollmentRequest, request_id)
    if req is None:
        raise not_found("Không tìm thấy yêu cầu đăng ký")
    cls = owned_class(db, user, req.class_id)
    if req.status != "pending":
        raise err(status.HTTP_409_CONFLICT, "VALIDATION_ERROR",
                  "Yêu cầu đã được xử lý")
    req.status = "approved" if body.action == "approve" else "rejected"
    req.decided_by = user.id
    result: dict = {"id": str(req.id), "status": req.status}
    if body.action == "approve":
        if req.requester_user_id:
            stu = db.get(User, req.requester_user_id)
            pw_once = None
        else:
            stu, code, pw_once = _new_student_user(
                db, req.requester_display_name, None)
            result["student_code"] = code
            result["login_email"] = stu.email
            result["initial_password_once"] = pw_once
        if not student_profile(db, stu.id):
            db.add(StudentProfile(
                user_id=stu.id, workspace_id=cls.workspace_id,
                display_name=req.requester_display_name,
                birth_year=req.requester_birth_year or 2010))
        existing_m = db.query(ClassMembership).filter_by(
            class_id=cls.id, student_user_id=stu.id).one_or_none()
        if existing_m is None:
            db.add(ClassMembership(class_id=cls.id, student_user_id=stu.id,
                                   source="join_code"))
        elif existing_m.left_at is not None:
            existing_m.left_at = None
        result["student_user_id"] = str(stu.id)
    db.commit()
    return result


# ================================================================= EL-102: giao đề
class AssignmentIn(BaseModel):
    class_id: uuid.UUID
    exam_version_id: uuid.UUID | None = None
    source_exam_id: uuid.UUID | None = None
    title: str | None = None
    mode: str = "paper_quick_entry"  # online | paper_quick_entry | paper_entry
    opens_at: datetime
    due_at: datetime
    answer_release_at: datetime
    show_score_immediately: bool = False
    shuffle_questions: bool = True
    shuffle_options: bool = True


class AssignmentPatchIn(BaseModel):
    due_at: datetime | None = None
    answer_release_at: datetime | None = None
    status: str | None = Field(default=None, pattern="^(closed)$")


def _norm_mode(mode: str) -> str:
    if mode in ("paper_entry", "paper_quick_entry", "quick_entry"):
        return "paper_quick_entry"
    if mode == "online":
        return "online"
    raise err(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", f"mode không hợp lệ: {mode}")


def _assignment_questions(db: Session, a: Assignment) -> list[dict]:
    """Trả [{question, exam_item_id}] theo thứ tự giao. Dùng ở publish + chấm."""
    out = []
    if a.exam_version_id:
        items = (db.query(ExamItem).filter_by(exam_version_id=a.exam_version_id)
                 .order_by(ExamItem.position).all())
        for it in items:
            q = db.get(QuestionItem, it.question_id)
            if q:
                out.append({"question": q, "exam_item_id": it.id})
    else:
        qs = (db.query(QuestionItem).filter_by(source_exam_id=a.source_exam_id)
              .order_by(QuestionItem.order_in_source.is_(None),
                        QuestionItem.order_in_source,
                        QuestionItem.created_at).all())
        for q in qs:
            out.append({"question": q, "exam_item_id": None})
    return out


def _build_snapshot(db: Session, a: Assignment) -> dict:
    """Snapshot giao HS — ĐÃ LỌC đáp án (R2): không correct_option_id/is_correct/
    explanation ở bất kỳ trường nào."""
    questions = []
    passage_cache: dict[uuid.UUID, dict | None] = {}
    for pos, entry in enumerate(_assignment_questions(db, a), start=1):
        q: QuestionItem = entry["question"]
        passage = None
        if q.passage_id:
            if q.passage_id not in passage_cache:
                p = db.get(PassageGroup, q.passage_id)
                passage_cache[q.passage_id] = (
                    {"id": str(p.id), "title": p.title,
                     "content_html": p.content_html,
                     "content_text": p.content_text} if p else None)
            passage = passage_cache[q.passage_id]
        options = (db.query(Option).filter_by(question_id=q.id)
                   .order_by(Option.position).all())
        questions.append({
            "position": pos, "question_id": str(q.id),
            "exam_item_id": str(entry["exam_item_id"]) if entry["exam_item_id"] else None,
            "question_type": q.question_type,
            "stem_html": q.stem_html, "stem_text": q.stem_text,
            "passage": passage,
            "options": [{"option_id": str(o.id), "label": o.label,
                         "content_html": o.content_html,
                         "content_text": o.content_text} for o in options],
        })
    return {"questions": questions}


def _assignment_out(db: Session, a: Assignment) -> dict:
    return {"id": str(a.id), "class_id": str(a.class_id),
            "exam_version_id": str(a.exam_version_id) if a.exam_version_id else None,
            "source_exam_id": str(a.source_exam_id) if a.source_exam_id else None,
            "title": a.title, "mode": a.mode, "status": a.status,
            "opens_at": _aware(a.opens_at).isoformat(),
            "due_at": _aware(a.due_at).isoformat(),
            "answer_release_at": _aware(a.answer_release_at).isoformat(),
            "show_score_immediately": a.show_score_immediately,
            "question_count": len((a.student_snapshot_json or {}).get("questions", []))
            if a.student_snapshot_json else None}


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(body: AssignmentIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    cls = owned_class(db, user, body.class_id)
    if bool(body.exam_version_id) == bool(body.source_exam_id):
        raise err(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR",
                  "Chọn đúng một nguồn: exam_version_id hoặc source_exam_id")
    title = body.title
    if body.exam_version_id:
        ver = db.get(ExamVersion, body.exam_version_id)
        if ver is None:
            raise not_found("Không tìm thấy exam version")
        exam = db.get(Exam, ver.exam_id)
        if exam is None or exam.workspace_id != cls.workspace_id:
            raise not_found("Không tìm thấy exam version")
        title = title or exam.title
    else:
        se = db.get(SourceExam, body.source_exam_id)
        if se is None or se.workspace_id != cls.workspace_id:
            raise not_found("Không tìm thấy đề gốc")
        title = title or se.title
    if _aware(body.due_at) <= _aware(body.opens_at):
        raise err(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR",
                  "due_at phải sau opens_at")
    a = Assignment(workspace_id=cls.workspace_id, class_id=cls.id,
                   created_by=user.id, exam_version_id=body.exam_version_id,
                   source_exam_id=body.source_exam_id, title=title or "Bài tập",
                   mode=_norm_mode(body.mode), opens_at=body.opens_at,
                   due_at=body.due_at, answer_release_at=body.answer_release_at,
                   show_score_immediately=body.show_score_immediately,
                   shuffle_questions=body.shuffle_questions,
                   shuffle_options=body.shuffle_options, status="draft")
    db.add(a)
    db.commit()
    db.refresh(a)
    return _assignment_out(db, a)


@router.post("/assignments/{assignment_id}/publish")
def publish_assignment(assignment_id: uuid.UUID, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    a = db.get(Assignment, assignment_id)
    if a is None:
        raise not_found("Không tìm thấy assignment")
    owned_class(db, user, a.class_id)
    entries = _assignment_questions(db, a)
    if not entries:
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, "QUESTIONS_NOT_APPROVED",
                  "Assignment không có câu hỏi nào", question_ids=[])
    bad = []
    for e in entries:
        q: QuestionItem = e["question"]
        ok_answer = (q.correct_option_id is not None and
                     db.query(Option).filter_by(
                         id=q.correct_option_id, question_id=q.id).one_or_none())
        if q.status != QuestionStatus.approved or not ok_answer:
            bad.append(str(q.id))
    if bad:
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, "QUESTIONS_NOT_APPROVED",
                  "Còn câu chưa được duyệt hoặc chưa có đáp án đúng",
                  question_ids=bad)
    a.student_snapshot_json = _build_snapshot(db, a)
    a.status = "published"
    db.commit()
    db.refresh(a)
    out = _assignment_out(db, a)
    out["question_count"] = len(entries)
    return out


@router.patch("/assignments/{assignment_id}")
def update_assignment(assignment_id: uuid.UUID, body: AssignmentPatchIn,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    a = db.get(Assignment, assignment_id)
    if a is None:
        raise not_found("Không tìm thấy assignment")
    owned_class(db, user, a.class_id)
    if a.status == "closed":
        raise err(status.HTTP_409_CONFLICT, "ASSIGNMENT_NOT_OPEN", "Assignment đã đóng")
    if body.due_at is not None:
        a.due_at = body.due_at
    if body.answer_release_at is not None:
        a.answer_release_at = body.answer_release_at
    if body.status is not None:
        a.status = body.status
    db.commit()
    db.refresh(a)
    return _assignment_out(db, a)


@router.get("/classes/{class_id}/assignments")
def list_class_assignments(class_id: uuid.UUID, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    cls = owned_class(db, user, class_id)
    rows = (db.query(Assignment).filter_by(class_id=cls.id)
            .order_by(Assignment.created_at).all())
    out = []
    for a in rows:
        o = _assignment_out(db, a)
        o["attempt_counts"] = {
            s: db.query(Attempt).filter_by(assignment_id=a.id, status=s).count()
            for s in ("in_progress", "submitted", "graded")}
        out.append(o)
    return out


# ==================================================== EL-103/104: attempt & chấm
class AttemptIn(BaseModel):
    client_uuid: uuid.UUID
    entry_method: str | None = None  # online | quick_entry | paper_entry
    mode: str | None = None          # alias của entry_method


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    selected_option_id: uuid.UUID | None = None
    confidence_level: int | None = Field(default=None, ge=1, le=3)


class AnswersIn(BaseModel):
    answers: list[AnswerIn]


class SubmitIn(BaseModel):
    client_uuid: uuid.UUID | None = None
    entry_method: str | None = None
    answers: list[AnswerIn] | None = None


def _norm_entry(v: str | None, assignment: Assignment) -> str:
    if v in ("paper_entry", "quick_entry"):
        return "quick_entry"
    if v == "online":
        return "online"
    if v == "teacher_entry":
        return "teacher_entry"
    return "online" if assignment.mode == "online" else "quick_entry"


def _student_assignment(db: Session, user: User,
                        assignment_id: uuid.UUID) -> Assignment:
    a = db.get(Assignment, assignment_id)
    if a is None:
        raise not_found("Không tìm thấy assignment")
    m = (db.query(ClassMembership)
         .filter_by(class_id=a.class_id, student_user_id=user.id)
         .filter(ClassMembership.left_at.is_(None)).one_or_none())
    if m is None:
        raise not_found("Không tìm thấy assignment")
    return a


def _own_attempt(db: Session, user: User, attempt_id: uuid.UUID) -> Attempt:
    att = db.get(Attempt, attempt_id)
    if att is None:
        raise not_found("Không tìm thấy attempt")
    if user.role == "student" and att.student_user_id != user.id:
        raise not_found("Không tìm thấy attempt")
    if user.role == "teacher":
        owned_class(db, user, db.get(Assignment, att.assignment_id).class_id)
    if user.role not in ("student", "teacher"):
        raise not_found("Không tìm thấy attempt")
    return att


def _attempt_questions(att: Attempt, a: Assignment) -> list[dict]:
    snap = a.student_snapshot_json or {"questions": []}
    return snap.get("questions", [])


def _upsert_answers(db: Session, att: Attempt, a: Assignment,
                    answers: list[AnswerIn]):
    valid_q = {q["question_id"] for q in _attempt_questions(att, a)}
    exam_item_by_q = {q["question_id"]: q.get("exam_item_id")
                      for q in _attempt_questions(att, a)}
    for ans in answers:
        if str(ans.question_id) not in valid_q:
            raise err(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR",
                      f"Câu {ans.question_id} không thuộc assignment")
        item = db.query(AttemptItem).filter_by(
            attempt_id=att.id, question_id=ans.question_id).one_or_none()
        if item is None:
            item = AttemptItem(
                attempt_id=att.id, question_id=ans.question_id,
                exam_item_id=uuid.UUID(exam_item_by_q[str(ans.question_id)])
                if exam_item_by_q.get(str(ans.question_id)) else None)
            db.add(item)
        item.selected_option_id = ans.selected_option_id
        if ans.confidence_level is not None:
            item.confidence_level = ans.confidence_level
    db.flush()


def _released(a: Assignment) -> bool:
    return _now() >= _aware(a.answer_release_at)


def _result_payload(db: Session, att: Attempt, a: Assignment) -> dict:
    released = _released(a)
    answered = (db.query(AttemptItem).filter_by(attempt_id=att.id)
                .filter(AttemptItem.selected_option_id.isnot(None)).count())
    total = len(_attempt_questions(att, a))
    out: dict = {"attempt_id": str(att.id), "assignment_id": str(a.id),
                 "status": att.status, "answered_count": answered,
                 "question_count": total,
                 "submitted_at": _aware(att.submitted_at).isoformat()
                 if att.submitted_at else None,
                 "answer_released": released}
    if att.status in ("submitted", "graded"):
        if released:
            out["score_raw"] = float(att.score_raw) if att.score_raw is not None else None
            out["score_max"] = float(att.score_max) if att.score_max is not None else None
            results = []
            items = {str(i.question_id): i for i in
                     db.query(AttemptItem).filter_by(attempt_id=att.id).all()}
            for q in _attempt_questions(att, a):
                item = items.get(q["question_id"])
                qq = db.get(QuestionItem, uuid.UUID(q["question_id"]))
                results.append({
                    "question_id": q["question_id"], "position": q["position"],
                    "selected_option_id": str(item.selected_option_id)
                    if item and item.selected_option_id else None,
                    "correct_option_id": str(qq.correct_option_id)
                    if qq and qq.correct_option_id else None,
                    "is_correct": item.is_correct if item else None})
            out["results"] = results
        elif a.show_score_immediately:
            out["score_raw"] = float(att.score_raw) if att.score_raw is not None else None
            out["score_max"] = float(att.score_max) if att.score_max is not None else None
    return out


@router.get("/my/assignments")
def my_assignments(db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_role(user, "student")
    class_ids = [m.class_id for m in db.query(ClassMembership)
                 .filter_by(student_user_id=user.id)
                 .filter(ClassMembership.left_at.is_(None)).all()]
    if not class_ids:
        return []
    rows = (db.query(Assignment).filter(Assignment.class_id.in_(class_ids),
                                        Assignment.status == "published")
            .order_by(Assignment.due_at).all())
    out = []
    for a in rows:
        att = (db.query(Attempt).filter_by(assignment_id=a.id,
                                            student_user_id=user.id)
               .order_by(Attempt.created_at.desc()).first())
        o = _assignment_out(db, a)
        o["my_attempt_status"] = att.status if att else None
        o["my_attempt_id"] = str(att.id) if att else None
        out.append(o)
    return out


@router.post("/assignments/{assignment_id}/attempts",
             status_code=status.HTTP_201_CREATED)
def create_attempt(assignment_id: uuid.UUID, body: AttemptIn,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_role(user, "student")
    a = _student_assignment(db, user, assignment_id)
    require_learning_access(db, user)
    existing = db.query(Attempt).filter_by(client_uuid=body.client_uuid).one_or_none()
    if existing:
        if existing.student_user_id != user.id or existing.assignment_id != a.id:
            raise not_found("Không tìm thấy attempt")
        return _attempt_start_payload(db, existing, a)
    if a.status != "published" or _now() < _aware(a.opens_at):
        raise err(status.HTTP_409_CONFLICT, "ASSIGNMENT_NOT_OPEN",
                  "Assignment chưa mở")
    in_prog = (db.query(Attempt).filter_by(assignment_id=a.id,
                                            student_user_id=user.id,
                                            status="in_progress").first())
    if in_prog:
        return _attempt_start_payload(db, in_prog, a)
    done = (db.query(Attempt).filter_by(assignment_id=a.id,
                                         student_user_id=user.id)
            .filter(Attempt.status.in_(("submitted", "graded"))).first())
    if done:
        raise err(status.HTTP_409_CONFLICT, "ATTEMPT_ALREADY_SUBMITTED",
                  "Đã nộp bài cho assignment này")
    att = Attempt(workspace_id=a.workspace_id, assignment_id=a.id,
                  student_user_id=user.id, status="in_progress",
                  entry_method=_norm_entry(body.entry_method or body.mode, a),
                  started_at=_now(), client_uuid=body.client_uuid,
                  shuffle_seed=str(body.client_uuid))
    db.add(att)
    db.commit()
    db.refresh(att)
    return _attempt_start_payload(db, att, a)


def _attempt_start_payload(db: Session, att: Attempt, a: Assignment) -> dict:
    items = {str(i.question_id): i for i in
             db.query(AttemptItem).filter_by(attempt_id=att.id).all()}
    questions = []
    for q in _attempt_questions(att, a):
        item = items.get(q["question_id"])
        questions.append({**q,
                          "selected_option_id": str(item.selected_option_id)
                          if item and item.selected_option_id else None,
                          "confidence_level": item.confidence_level if item else None})
    return {"id": str(att.id), "attempt_id": str(att.id),
            "assignment_id": str(a.id), "status": att.status,
            "entry_method": att.entry_method, "mode": a.mode,
            "title": a.title,
            "answer_release_at": _aware(a.answer_release_at).isoformat(),
            "questions": questions}


@router.patch("/attempts/{attempt_id}/answers")
def save_answers(attempt_id: uuid.UUID, body: AnswersIn,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    att = _own_attempt(db, user, attempt_id)
    if user.role != "student":
        raise err(status.HTTP_403_FORBIDDEN, "FORBIDDEN_ROLE",
                  "Chỉ học sinh của attempt mới lưu đáp án")
    if att.status != "in_progress":
        raise err(status.HTTP_409_CONFLICT, "ATTEMPT_ALREADY_SUBMITTED",
                  "Bài đã nộp, không sửa được đáp án")
    a = db.get(Assignment, att.assignment_id)
    _upsert_answers(db, att, a, body.answers)
    db.commit()
    return {"attempt_id": str(att.id), "saved": len(body.answers),
            "answered_count": db.query(AttemptItem).filter_by(attempt_id=att.id)
            .filter(AttemptItem.selected_option_id.isnot(None)).count()}


@router.patch("/attempts/{attempt_id}/answer")
def save_one_answer(attempt_id: uuid.UUID, body: AnswerIn,
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return save_answers(attempt_id, AnswersIn(answers=[body]), db, user)


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: uuid.UUID, body: SubmitIn,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    att = _own_attempt(db, user, attempt_id)
    if user.role != "student":
        raise err(status.HTTP_403_FORBIDDEN, "FORBIDDEN_ROLE",
                  "Chỉ học sinh của attempt mới nộp bài")
    a = db.get(Assignment, att.assignment_id)
    if att.status in ("submitted", "graded"):
        if body.client_uuid is None or body.client_uuid == att.client_uuid:
            return _result_payload(db, att, a)
        raise err(status.HTTP_409_CONFLICT, "ATTEMPT_ALREADY_SUBMITTED",
                  "Bài đã được nộp")
    if body.answers:
        _upsert_answers(db, att, a, body.answers)
    if body.entry_method:
        att.entry_method = _norm_entry(body.entry_method, a)
    # Chấm ở server trong transaction này (R2): so với correct_option_id thật.
    questions = _attempt_questions(att, a)
    items = {i.question_id: i for i in
             db.query(AttemptItem).filter_by(attempt_id=att.id).all()}
    score = 0
    for q in questions:
        qid = uuid.UUID(q["question_id"])
        item = items.get(qid)
        if item is None:
            item = AttemptItem(attempt_id=att.id, question_id=qid,
                               exam_item_id=uuid.UUID(q["exam_item_id"])
                               if q.get("exam_item_id") else None)
            db.add(item)
        qq = db.get(QuestionItem, qid)
        item.is_correct = bool(item.selected_option_id is not None and
                               qq is not None and
                               item.selected_option_id == qq.correct_option_id)
        if item.is_correct:
            score += 1
    att.score_raw = score
    att.score_max = len(questions)
    att.status = "graded"
    att.submitted_at = _now()
    if att.started_at:
        att.duration_seconds = int(
            (att.submitted_at - _aware(att.started_at)).total_seconds())
    db.commit()
    db.refresh(att)
    return _result_payload(db, att, a)


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    att = _own_attempt(db, user, attempt_id)
    a = db.get(Assignment, att.assignment_id)
    out = _result_payload(db, att, a)
    out["questions"] = _attempt_start_payload(db, att, a)["questions"]
    out["entry_method"] = att.entry_method
    out["mode"] = a.mode
    return out


@router.get("/attempts/{attempt_id}/result")
def get_attempt_result(attempt_id: uuid.UUID, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    att = _own_attempt(db, user, attempt_id)
    a = db.get(Assignment, att.assignment_id)
    if att.status not in ("submitted", "graded"):
        return _result_payload(db, att, a)
    if not _released(a) and not a.show_score_immediately:
        # Chưa tới giờ mở đáp án: chỉ xác nhận đã nộp (spec S3 + task EL-103).
        out = _result_payload(db, att, a)
        return out
    return _result_payload(db, att, a)


# ==================================================== Sprint 2 — EL-202/203:
# bẻ hạt (pipeline), kho hạt + duyệt, biến thể. Mọi nội dung AI sinh ra đều
# pending_review; cổng duyệt 0,70 theo spec T10/T12 (Master Plan Sprint 2).

class AtomGenerationIn(BaseModel):
    max_atoms: int = Field(default=3, ge=1, le=3)
    force: bool = False


class ExamGenerationIn(BaseModel):
    force: bool = False


class AtomPatchIn(BaseModel):
    headword: str | None = None
    atom_type: str | None = None
    front_text: str | None = None
    back_text: str | None = None
    meaning_vi: str | None = None
    meaning_en: str | None = None
    example_sentence: str | None = None
    priority: str | None = Field(default=None, pattern="^(P1|P2|P3)$")
    common_error_code: str | None = None


class ApproveIn(BaseModel):
    confirm_answer: bool = False


class BulkApproveIn(BaseModel):
    atom_ids: list[uuid.UUID]


class VariantGenerationIn(BaseModel):
    force: bool = False


class PostTestContentPatchIn(BaseModel):
    error_code: str | None = None
    why_wrong: str | None = None
    cue: str | None = None
    rule: str | None = None
    why_correct: str | None = None


def _teacher_question(db: Session, user: User, question_id: uuid.UUID) -> QuestionItem:
    q = db.get(QuestionItem, question_id)
    if q is None:
        raise not_found("Không tìm thấy câu hỏi")
    get_owned = teacher_workspace(db, user)
    if q.workspace_id != get_owned.id:
        raise not_found("Không tìm thấy câu hỏi")
    return q


def _teacher_atom(db: Session, user: User, atom_id: uuid.UUID) -> LearningAtom:
    atom = db.get(LearningAtom, atom_id)
    ws = teacher_workspace(db, user)
    if atom is None or atom.workspace_id != ws.id:
        raise not_found("Không tìm thấy hạt học tập")
    return atom


def _teacher_variant(db: Session, user: User, variant_id: uuid.UUID) -> VariantItem:
    var = db.get(VariantItem, variant_id)
    ws = teacher_workspace(db, user)
    if var is None or var.workspace_id != ws.id:
        raise not_found("Không tìm thấy biến thể")
    return var


def _teacher_content(db: Session, user: User, content_id: uuid.UUID) -> PostTestContent:
    pc = db.get(PostTestContent, content_id)
    ws = teacher_workspace(db, user)
    if pc is None or pc.workspace_id != ws.id:
        raise not_found("Không tìm thấy nội dung hậu-đề")
    return pc


def _mark_viewed(db: Session, user: User, target_type: str, target_id: uuid.UUID):
    """Ghi nhận GV đã mở xem 1 nội dung (cơ chế cổng 0,70 — spec T9/T10)."""
    db.add(AuditLog(workspace_id=teacher_workspace(db, user).id,
                    actor_user_id=user.id, action=f"{target_type}_view",
                    target_type=target_type, target_id=target_id,
                    event_metadata={}))
    db.flush()


def _was_viewed(db: Session, user: User, target_type: str, target_id: uuid.UUID) -> bool:
    return (db.query(AuditLog)
            .filter_by(actor_user_id=user.id, action=f"{target_type}_view",
                       target_type=target_type, target_id=target_id)
            .first()) is not None


def _approve_gate(db: Session, user: User, obj, target_type: str,
                  confirm_answer: bool) -> str | None:
    """Trả mã lỗi nếu chưa được duyệt, None nếu qua cổng (spec T10)."""
    if (obj.origin == "ai_generated" and obj.ai_confidence is not None
            and float(obj.ai_confidence) < 0.70
            and not _was_viewed(db, user, target_type, obj.id)):
        return "ATOM_LOW_CONFIDENCE"
    if getattr(obj, "needs_teacher_confirmation", False) and not confirm_answer:
        return "TEACHER_CONFIRMATION_REQUIRED"
    return None


def _do_approve(db: Session, user: User, obj):
    obj.status = "approved"
    obj.reviewed_by = user.id
    obj.reviewed_at = _now()


def _do_reject(db: Session, user: User, obj):
    obj.status = "rejected"
    obj.reviewed_by = user.id
    obj.reviewed_at = _now()


def _atom_out(db: Session, atom: LearningAtom, detail: bool = False) -> dict:
    q = db.get(QuestionItem, atom.source_question_id)
    sources = [{"question_id": str(s.question_id), "source_role": s.source_role,
                "source_exam_id": str(s.source_exam_id) if s.source_exam_id else None}
               for s in db.query(AtomSource).filter_by(atom_id=atom.id).all()]
    variants = (db.query(VariantItem).filter_by(parent_atom_id=atom.id)
                .order_by(VariantItem.created_at).all())
    out = {"id": str(atom.id), "workspace_id": str(atom.workspace_id),
           "headword": atom.headword, "atom_type": atom.atom_type,
           "front_text": atom.front_text, "back_text": atom.back_text,
           "meaning_vi": atom.meaning_vi, "meaning_en": atom.meaning_en,
           "example_sentence": atom.example_sentence,
           "source_sentence": atom.source_sentence,
           "priority": atom.priority, "common_error_code": atom.common_error_code,
           "cefr_level": atom.cefr_level,
           "source_question_id": str(atom.source_question_id),
           "source_question_stem": q.stem_text if q else None,
           "source_exam_id": str(q.source_exam_id) if q and q.source_exam_id else None,
           "status": atom.status, "origin": atom.origin,
           "answer_provenance": atom.answer_provenance,
           "ai_confidence": float(atom.ai_confidence) if atom.ai_confidence is not None else None,
           "needs_teacher_confirmation": atom.needs_teacher_confirmation,
           "sources": sources,
           "variants": [{"id": str(v.id), "variant_tier": v.variant_tier,
                         "status": v.status} for v in variants]}
    if detail:
        out["reviewed_by"] = str(atom.reviewed_by) if atom.reviewed_by else None
        out["reviewed_at"] = _aware(atom.reviewed_at).isoformat() if atom.reviewed_at else None
    return out


def _variant_out(db: Session, var: VariantItem) -> dict:
    options = (db.query(VariantOption).filter_by(variant_id=var.id)
               .order_by(VariantOption.position).all())
    return {"id": str(var.id), "parent_atom_id": str(var.parent_atom_id) if var.parent_atom_id else None,
            "parent_question_id": str(var.parent_question_id) if var.parent_question_id else None,
            "variant_tier": var.variant_tier, "stem_text": var.stem_text,
            "options": [{"option_id": str(o.id), "label": o.label,
                         "content_text": o.content_text} for o in options],
            "correct_option_id": str(var.correct_option_id) if var.correct_option_id else None,
            "status": var.status, "origin": var.origin,
            "ai_confidence": float(var.ai_confidence) if var.ai_confidence is not None else None,
            "answer_provenance": var.answer_provenance,
            "needs_teacher_confirmation": False}


@router.post("/questions/{question_id}/atom-generation-jobs",
             status_code=status.HTTP_201_CREATED)
def create_atom_generation_job(question_id: uuid.UUID, body: AtomGenerationIn,
                               db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    """EL-202 (spec T7 — chạy đồng bộ như luồng AI hiện có của ExamBank thay vì
    202 nền/Celery; job vẫn được ghi vào ai_generation_jobs)."""
    require_role(user, "teacher")
    q = _teacher_question(db, user, question_id)
    if q.status != QuestionStatus.approved or not q.correct_option_id:
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, "QUESTIONS_NOT_APPROVED",
                  "Chỉ bẻ hạt từ câu đã approved và có đáp án đúng",
                  question_ids=[str(q.id)])
    result = content_pipeline.generate_for_question(
        db, q, user, max_atoms=body.max_atoms, force=body.force)
    db.commit()
    return result


@router.post("/source-exams/{exam_id}/atom-generation")
def generate_exam_atoms(exam_id: uuid.UUID, body: ExamGenerationIn,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """EL-202 cấp đề: sinh cho mọi câu đạt chuẩn của đề gốc, trần 120 atom/đề."""
    require_role(user, "teacher")
    exam = db.get(SourceExam, exam_id)
    ws = teacher_workspace(db, user)
    if exam is None or exam.workspace_id != ws.id:
        raise not_found("Không tìm thấy đề gốc")
    result = content_pipeline.generate_for_exam(db, exam, user, force=body.force)
    db.commit()
    return result


@router.get("/atoms")
def list_atoms(db: Session = Depends(get_db), user: User = Depends(get_current_user),
               status_filter: str | None = Query(default=None, alias="status"),
               priority: str | None = None,
               atom_type: str | None = None,
               source_question_id: uuid.UUID | None = None,
               source_exam_id: uuid.UUID | None = None,
               limit: int = Query(default=100, le=200), offset: int = 0):
    require_role(user, "teacher")
    ws = teacher_workspace(db, user)
    query = db.query(LearningAtom).filter_by(workspace_id=ws.id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if priority:
        query = query.filter_by(priority=priority)
    if atom_type:
        query = query.filter_by(atom_type=atom_type)
    if source_question_id:
        query = query.filter_by(source_question_id=source_question_id)
    if source_exam_id:
        qids = [q.id for q in db.query(QuestionItem)
                .filter_by(source_exam_id=source_exam_id).all()]
        query = query.filter(LearningAtom.source_question_id.in_(qids))
    total = query.count()
    rows = (query.order_by(LearningAtom.priority, LearningAtom.created_at)
            .offset(offset).limit(limit).all())
    pending_total = (db.query(LearningAtom)
                     .filter_by(workspace_id=ws.id, status="pending_review").count())
    return {"items": [_atom_out(db, a) for a in rows], "total": total,
            "pending_total": pending_total}


@router.post("/atoms/bulk-approve")
def bulk_approve_atoms(body: BulkApproveIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Spec T12: duyệt nhanh theo lô — atom dưới cổng 0,70/chưa xác nhận bị
    loại vào danh sách skipped kèm mã, không fail cả lô."""
    require_role(user, "teacher")
    approved, skipped = [], []
    for atom_id in body.atom_ids:
        atom = db.get(LearningAtom, atom_id)
        ws = teacher_workspace(db, user)
        if atom is None or atom.workspace_id != ws.id:
            skipped.append({"atom_id": str(atom_id), "code": "NOT_FOUND"})
            continue
        if atom.status == "approved":
            approved.append(str(atom.id))
            continue
        gate = _approve_gate(db, user, atom, "atom", confirm_answer=False)
        if gate:
            skipped.append({"atom_id": str(atom.id), "code": gate})
            continue
        _do_approve(db, user, atom)
        approved.append(str(atom.id))
    db.commit()
    return {"approved": approved, "skipped": skipped}


@router.get("/atoms/{atom_id}")
def get_atom(atom_id: uuid.UUID, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    atom = _teacher_atom(db, user, atom_id)
    _mark_viewed(db, user, "atom", atom.id)
    db.commit()
    return _atom_out(db, atom, detail=True)


@router.patch("/atoms/{atom_id}")
def patch_atom(atom_id: uuid.UUID, body: AtomPatchIn,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    atom = _teacher_atom(db, user, atom_id)
    was_approved = atom.status == "approved"
    for field in ("headword", "atom_type", "meaning_vi", "meaning_en",
                  "example_sentence", "priority", "common_error_code"):
        value = getattr(body, field)
        if value is not None:
            setattr(atom, field, value)
    if body.front_text is not None:
        atom.front_text = body.front_text
        atom.front_html = content_pipeline._p(body.front_text)
    if body.back_text is not None:
        atom.back_text = body.back_text
        atom.back_html = content_pipeline._p(body.back_text)
    if was_approved:
        # Spec T11: sửa atom đã duyệt -> về chờ duyệt lại (thẻ ôn liên quan sẽ
        # suspended ở Sprint 3 — chưa có thẻ nào được tạo ở Sprint 2).
        atom.status = "pending_review"
        atom.reviewed_by = None
        atom.reviewed_at = None
    _mark_viewed(db, user, "atom", atom.id)
    db.commit()
    db.refresh(atom)
    return _atom_out(db, atom, detail=True)


@router.post("/atoms/{atom_id}/approve")
def approve_atom(atom_id: uuid.UUID, body: ApproveIn,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    atom = _teacher_atom(db, user, atom_id)
    gate = _approve_gate(db, user, atom, "atom", body.confirm_answer)
    if gate == "ATOM_LOW_CONFIDENCE":
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, "ATOM_LOW_CONFIDENCE",
                  "Atom AI có độ tin cậy < 0,70 — mở xem nội dung trước khi duyệt")
    if gate:
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, gate,
                  "Atom suy từ câu chưa có đáp án chắc chắn — GV cần xác nhận đáp án tường minh",
                  )
    _do_approve(db, user, atom)
    db.commit()
    db.refresh(atom)
    return _atom_out(db, atom, detail=True)


@router.post("/atoms/{atom_id}/reject")
def reject_atom(atom_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    atom = _teacher_atom(db, user, atom_id)
    _do_reject(db, user, atom)
    db.commit()
    db.refresh(atom)
    return _atom_out(db, atom, detail=True)


@router.post("/atoms/{atom_id}/variant-generation-jobs",
             status_code=status.HTTP_201_CREATED)
def create_variant_generation_job(atom_id: uuid.UUID, body: VariantGenerationIn,
                                  db: Session = Depends(get_db),
                                  user: User = Depends(get_current_user)):
    """EL-204: sinh biến thể P2 (tier T2, ngữ cảnh mới) cho 1 atom."""
    require_role(user, "teacher")
    atom = _teacher_atom(db, user, atom_id)
    if atom.status == "rejected":
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, "ATOM_REJECTED",
                  "Không sinh biến thể cho atom đã bị loại")
    result = content_pipeline.generate_variant_p2(db, atom, user, force=body.force)
    db.commit()
    return result


@router.get("/variants")
def list_variants(db: Session = Depends(get_db),
                  user: User = Depends(get_current_user),
                  atom_id: uuid.UUID | None = None,
                  status_filter: str | None = Query(default=None, alias="status"),
                  tier: str | None = None):
    require_role(user, "teacher")
    ws = teacher_workspace(db, user)
    query = db.query(VariantItem).filter_by(workspace_id=ws.id)
    if atom_id:
        query = query.filter_by(parent_atom_id=atom_id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if tier:
        query = query.filter_by(variant_tier=tier)
    rows = query.order_by(VariantItem.created_at).all()
    return {"items": [_variant_out(db, v) for v in rows], "total": len(rows)}


@router.get("/variants/{variant_id}")
def get_variant(variant_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    var = _teacher_variant(db, user, variant_id)
    _mark_viewed(db, user, "variant", var.id)
    db.commit()
    return _variant_out(db, var)


@router.post("/variants/{variant_id}/approve")
def approve_variant(variant_id: uuid.UUID, body: ApproveIn,
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    var = _teacher_variant(db, user, variant_id)
    gate = _approve_gate(db, user, var, "variant", body.confirm_answer)
    if gate:
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, gate,
                  "Biến thể chưa qua được cổng duyệt (độ tin cậy/xác nhận)")
    if not var.correct_option_id:
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, "VARIANT_NO_ANSWER",
                  "Biến thể chưa có đáp án đúng — không được duyệt")
    _do_approve(db, user, var)
    db.commit()
    db.refresh(var)
    return _variant_out(db, var)


@router.post("/variants/{variant_id}/reject")
def reject_variant(variant_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    var = _teacher_variant(db, user, variant_id)
    _do_reject(db, user, var)
    db.commit()
    db.refresh(var)
    return _variant_out(db, var)


def _content_out(db: Session, pc: PostTestContent) -> dict:
    q = db.get(QuestionItem, pc.question_id)
    return {"id": str(pc.id), "question_id": str(pc.question_id),
            "question_stem": q.stem_text if q else None,
            "content": pc.content_json, "status": pc.status,
            "origin": pc.origin, "answer_provenance": pc.answer_provenance,
            "ai_confidence": float(pc.ai_confidence) if pc.ai_confidence is not None else None,
            "needs_teacher_confirmation": pc.needs_teacher_confirmation}


@router.get("/post-test-contents")
def list_post_test_contents(db: Session = Depends(get_db),
                            user: User = Depends(get_current_user),
                            status_filter: str | None = Query(default=None, alias="status"),
                            question_id: uuid.UUID | None = None):
    require_role(user, "teacher")
    ws = teacher_workspace(db, user)
    query = db.query(PostTestContent).filter_by(workspace_id=ws.id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if question_id:
        query = query.filter_by(question_id=question_id)
    rows = query.order_by(PostTestContent.created_at).all()
    return {"items": [_content_out(db, pc) for pc in rows], "total": len(rows),
            "pending_total": db.query(PostTestContent)
            .filter_by(workspace_id=ws.id, status="pending_review").count()}


@router.get("/post-test-contents/{content_id}")
def get_post_test_content(content_id: uuid.UUID, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    pc = _teacher_content(db, user, content_id)
    _mark_viewed(db, user, "post_test_content", pc.id)
    db.commit()
    return _content_out(db, pc)


@router.patch("/post-test-contents/{content_id}")
def patch_post_test_content(content_id: uuid.UUID, body: PostTestContentPatchIn,
                            db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    """GV sửa phần chữ của nội dung hậu-đề (khoá chấm giữ nguyên)."""
    require_role(user, "teacher")
    pc = _teacher_content(db, user, content_id)
    content = dict(pc.content_json)
    for field in ("error_code", "why_wrong", "cue", "rule", "why_correct"):
        value = getattr(body, field)
        if value is not None:
            content[field] = value
    pc.content_json = content
    if pc.status == "approved":
        pc.status = "pending_review"
        pc.reviewed_by = None
        pc.reviewed_at = None
    _mark_viewed(db, user, "post_test_content", pc.id)
    db.commit()
    db.refresh(pc)
    return _content_out(db, pc)


@router.post("/post-test-contents/{content_id}/approve")
def approve_post_test_content(content_id: uuid.UUID, body: ApproveIn,
                              db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    pc = _teacher_content(db, user, content_id)
    gate = _approve_gate(db, user, pc, "post_test_content", body.confirm_answer)
    if gate:
        raise err(status.HTTP_422_UNPROCESSABLE_ENTITY, gate,
                  "Nội dung hậu-đề chưa qua được cổng duyệt (độ tin cậy/xác nhận)")
    _do_approve(db, user, pc)
    db.commit()
    db.refresh(pc)
    return _content_out(db, pc)


@router.post("/post-test-contents/{content_id}/reject")
def reject_post_test_content(content_id: uuid.UUID, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    require_role(user, "teacher")
    pc = _teacher_content(db, user, content_id)
    _do_reject(db, user, pc)
    db.commit()
    db.refresh(pc)
    return _content_out(db, pc)


# ==================================================== Sprint 2 — EL-201/204 phía HS:
# hậu-đề 4 bước + chấm biến thể. Khoá từng bước kiểm ở SERVER: bước sau chỉ mở
# khi bước trước đã hoàn thành (progress.current_step), không chỉ ẩn ở UI.

class PostTestStepIn(BaseModel):
    step: int = Field(ge=1, le=3)
    choice_key: str | None = None        # bước 1: chẩn đoán
    selected_keys: list[str] | None = None  # bước 3: cặp tối thiểu


class VariantAnswerIn(BaseModel):
    variant_id: uuid.UUID
    selected_variant_option_id: uuid.UUID | None = None
    client_uuid: uuid.UUID


class VariantAnswerFreeIn(BaseModel):
    selected_variant_option_id: uuid.UUID | None = None
    client_uuid: uuid.UUID


def _student_post_test_attempt(db: Session, user: User,
                               attempt_id: uuid.UUID) -> tuple[Attempt, Assignment]:
    require_role(user, "student")
    att = db.get(Attempt, attempt_id)
    if att is None or att.student_user_id != user.id:
        raise not_found("Không tìm thấy attempt")
    require_learning_access(db, user)
    a = db.get(Assignment, att.assignment_id)
    if att.status not in ("submitted", "graded"):
        raise err(status.HTTP_409_CONFLICT, "ATTEMPT_NOT_SUBMITTED",
                  "Nộp bài trước khi xem phần hậu-đề")
    if not _released(a) and not a.show_score_immediately:
        raise err(status.HTTP_403_FORBIDDEN, "ANSWER_NOT_RELEASED",
                  "Đáp án và phần giải thích chưa mở",
                  release_at=_aware(a.answer_release_at).isoformat())
    return att, a


def _attempt_item(db: Session, att: Attempt, question_id: uuid.UUID) -> AttemptItem:
    item = db.query(AttemptItem).filter_by(
        attempt_id=att.id, question_id=question_id).one_or_none()
    if item is None or item.is_correct is None:
        raise not_found("Không tìm thấy câu trong bài làm")
    if item.is_correct and item.confidence_level not in (1, 2):
        # Câu đúng + chắc chắn: không có hậu-đề (Master Plan Core Loop [4]).
        raise not_found("Câu này đã đúng và chắc chắn — không có phần hậu-đề")
    return item


def _approved_content(db: Session, question_id: uuid.UUID) -> PostTestContent | None:
    return (db.query(PostTestContent)
            .filter_by(question_id=question_id, status="approved").one_or_none())


def _progress_of(db: Session, att: Attempt, question_id: uuid.UUID,
                 create: bool = False) -> PostTestProgress | None:
    prog = db.query(PostTestProgress).filter_by(
        attempt_id=att.id, question_id=question_id).one_or_none()
    if prog is None and create:
        a = db.get(Assignment, att.assignment_id)
        prog = PostTestProgress(workspace_id=a.workspace_id, attempt_id=att.id,
                                question_id=question_id,
                                student_user_id=att.student_user_id)
        db.add(prog)
        db.flush()
    return prog


def _progress_out(prog: PostTestProgress | None) -> dict:
    if prog is None:
        return {"current_step": 0, "status": "in_progress",
                "step1_correct": None, "step3_correct": None, "step4_correct": None}
    return {"current_step": prog.current_step, "status": prog.status,
            "step1_correct": prog.step1_correct,
            "step3_correct": prog.step3_correct,
            "step4_correct": prog.step4_correct}


def _option_brief(db: Session, option_id: uuid.UUID | None) -> dict | None:
    if option_id is None:
        return None
    o = db.get(Option, option_id)
    if o is None:
        return None
    return {"option_id": str(o.id), "label": o.label, "content_text": o.content_text}


def _step4_variant(db: Session, question_id: uuid.UUID) -> VariantItem | None:
    """Biến thể P2 (T2) đã duyệt của 1 atom đã duyệt của câu — chỉ 1 đường tới HS."""
    atom_ids = [a.id for a in db.query(LearningAtom)
                .filter_by(source_question_id=question_id, status="approved").all()]
    if not atom_ids:
        return None
    return (db.query(VariantItem)
            .filter(VariantItem.parent_atom_id.in_(atom_ids),
                    VariantItem.variant_tier == "T2",
                    VariantItem.status == "approved",
                    VariantItem.correct_option_id.isnot(None))
            .order_by(VariantItem.created_at).first())


def _variant_student_out(db: Session, var: VariantItem) -> dict:
    options = (db.query(VariantOption).filter_by(variant_id=var.id)
               .order_by(VariantOption.position).all())
    return {"variant_id": str(var.id), "stem_text": var.stem_text,
            "options": [{"option_id": str(o.id), "label": o.label,
                         "content_text": o.content_text} for o in options]}


def _grade_variant_answer(db: Session, user: User, var: VariantItem,
                          selected_option_id, client_uuid,
                          attempt_id=None) -> dict:
    """Chấm biến thể ở server + ghi variant_attempts (idempotent theo client_uuid).

    Kết quả CHƯA đẩy vào FSRS ở Sprint 2 (không tạo review_cards/review_logs).
    """
    existing = db.query(VariantAttempt).filter_by(client_uuid=client_uuid).one_or_none()
    if existing is not None:
        if existing.student_user_id != user.id or existing.variant_id != var.id:
            raise not_found("Không tìm thấy lượt làm biến thể")
        return {"variant_id": str(var.id), "is_correct": existing.is_correct,
                "variant_attempt_id": str(existing.id), "idempotent": True}
    if selected_option_id is not None:
        opt = db.get(VariantOption, selected_option_id)
        if opt is None or opt.variant_id != var.id:
            raise err(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR",
                      "Phương án không thuộc biến thể này")
    is_correct = bool(selected_option_id is not None
                      and var.correct_option_id is not None
                      and selected_option_id == var.correct_option_id)
    va = VariantAttempt(workspace_id=var.workspace_id, student_user_id=user.id,
                        variant_id=var.id, attempt_id=attempt_id,
                        selected_variant_option_id=selected_option_id,
                        is_correct=is_correct, client_uuid=client_uuid)
    db.add(va)
    db.flush()
    return {"variant_id": str(var.id), "is_correct": is_correct,
            "variant_attempt_id": str(va.id), "idempotent": False}


@router.get("/attempts/{attempt_id}/post-test")
def post_test_list(attempt_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    att, a = _student_post_test_attempt(db, user, attempt_id)
    items = {i.question_id: i for i in
             db.query(AttemptItem).filter_by(attempt_id=att.id).all()}
    out = []
    for q in _attempt_questions(att, a):
        qid = uuid.UUID(q["question_id"])
        item = items.get(qid)
        if item is None or item.is_correct is None:
            continue
        if item.is_correct and item.confidence_level not in (1, 2):
            continue
        qq = db.get(QuestionItem, qid)
        pc = _approved_content(db, qid)
        prog = _progress_of(db, att, qid)
        out.append({
            "question_id": q["question_id"], "position": q["position"],
            "question_type": q["question_type"],
            "stem_html": q["stem_html"], "stem_text": q["stem_text"],
            "kind": "wrong" if not item.is_correct else "correct_unsure",
            "your_option": _option_brief(db, item.selected_option_id),
            "correct_option": _option_brief(db, qq.correct_option_id if qq else None),
            "content_status": "ready" if pc else "preparing",
            "progress": _progress_out(prog)})
    return {"attempt_id": str(att.id), "assignment_id": str(a.id),
            "title": a.title, "items": out}


@router.get("/attempts/{attempt_id}/post-test/{question_id}")
def post_test_detail(attempt_id: uuid.UUID, question_id: uuid.UUID,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    att, a = _student_post_test_attempt(db, user, attempt_id)
    item = _attempt_item(db, att, question_id)
    qq = db.get(QuestionItem, question_id)
    prog = _progress_of(db, att, question_id, create=True)
    db.commit()
    base = {"question_id": str(question_id),
            "stem_html": qq.stem_html if qq else None,
            "stem_text": qq.stem_text if qq else None,
            "kind": "wrong" if not item.is_correct else "correct_unsure",
            "your_option": _option_brief(db, item.selected_option_id),
            "correct_option": _option_brief(db, qq.correct_option_id if qq else None),
            "progress": _progress_out(prog)}
    pc = _approved_content(db, question_id)
    if pc is None:
        # Chưa có nội dung đã duyệt -> 'đang chuẩn bị', tuyệt đối không bịa.
        base["content_status"] = "preparing"
        base["steps"] = None
        return base
    c = pc.content_json
    step = prog.current_step
    steps: dict = {
        "step1": {"why_wrong": c["why_wrong"],
                  "diagnosis_options": c["diagnosis_options"]},
        "step2": {"locked": step < 1},
        "step3": {"locked": step < 2},
        "step4": {"locked": step < 3},
    }
    if step >= 1:
        steps["step2"].update({"cue": c["cue"], "rule": c["rule"],
                               "why_correct": c["why_correct"]})
    if step >= 2:
        steps["step3"]["statements"] = [
            {"key": s["key"], "text": s["text"]} for s in c["minimal_pair"]]
    if step >= 3:
        var = _step4_variant(db, question_id)
        steps["step4"]["variant"] = (_variant_student_out(db, var)
                                     if var else None)
    base["content_status"] = "ready"
    base["error_code"] = c.get("error_code")
    base["steps"] = steps
    return base


@router.post("/attempts/{attempt_id}/post-test/{question_id}/step")
def post_test_step(attempt_id: uuid.UUID, question_id: uuid.UUID,
                   body: PostTestStepIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    att, a = _student_post_test_attempt(db, user, attempt_id)
    _attempt_item(db, att, question_id)
    pc = _approved_content(db, question_id)
    if pc is None:
        raise err(status.HTTP_409_CONFLICT, "CONTENT_NOT_READY",
                  "Nội dung hậu-đề của câu này đang được chuẩn bị")
    c = pc.content_json
    prog = _progress_of(db, att, question_id, create=True)
    if body.step == 1:
        if body.choice_key is None:
            raise err(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR",
                      "Bước 1 cần choice_key")
        is_correct = body.choice_key == c["correct_diagnosis_key"]
        prog.step1_choice_key = body.choice_key
        prog.step1_correct = is_correct
        if is_correct and prog.current_step < 1:
            prog.current_step = 1
        db.commit()
        return {"step": 1, "is_correct": is_correct,
                "progress": _progress_out(prog)}
    if body.step == 2:
        if prog.current_step < 1:
            raise err(status.HTTP_409_CONFLICT, "STEP_LOCKED",
                      "Hoàn thành bước 1 trước khi mở bước 2")
        if prog.current_step < 2:
            prog.current_step = 2
        db.commit()
        return {"step": 2, "is_correct": None, "progress": _progress_out(prog)}
    # bước 3
    if prog.current_step < 2:
        raise err(status.HTTP_409_CONFLICT, "STEP_LOCKED",
                  "Hoàn thành bước 2 trước khi làm bước 3")
    if body.selected_keys is None:
        raise err(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR",
                  "Bước 3 cần selected_keys")
    correct_keys = {s["key"] for s in c["minimal_pair"] if s["is_correct"]}
    is_correct = set(body.selected_keys) == correct_keys
    prog.step3_selected_keys = list(body.selected_keys)
    prog.step3_correct = is_correct
    if is_correct and prog.current_step < 3:
        prog.current_step = 3
    db.commit()
    return {"step": 3, "is_correct": is_correct, "progress": _progress_out(prog)}


@router.post("/attempts/{attempt_id}/post-test/{question_id}/variant-answer")
def post_test_variant_answer(attempt_id: uuid.UUID, question_id: uuid.UUID,
                             body: VariantAnswerIn,
                             db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    """Bước 4 của hậu-đề: làm biến thể P2 — server chấm, đúng mới hoàn thành."""
    att, a = _student_post_test_attempt(db, user, attempt_id)
    _attempt_item(db, att, question_id)
    prog = _progress_of(db, att, question_id, create=True)
    if prog.current_step < 3:
        raise err(status.HTTP_409_CONFLICT, "STEP_LOCKED",
                  "Hoàn thành bước 3 trước khi làm biến thể ở bước 4")
    var = _step4_variant(db, question_id)
    if var is None or var.id != body.variant_id:
        raise not_found("Không tìm thấy biến thể cho câu này")
    result = _grade_variant_answer(db, user, var, body.selected_variant_option_id,
                                   body.client_uuid, attempt_id=att.id)
    prog.step4_variant_id = var.id
    prog.step4_correct = result["is_correct"]
    if result["is_correct"]:
        prog.current_step = 4
        prog.status = "completed"
        prog.completed_at = _now()
    db.commit()
    result["progress"] = _progress_out(prog)
    return result


@router.post("/variants/{variant_id}/answer")
def answer_variant_free(variant_id: uuid.UUID, body: VariantAnswerFreeIn,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """API chấm biến thể độc lập (Sprint 3 dùng lại cho phiên ôn/probe).

    Chỉ biến thể approved của atom approved mới tới được HS.
    """
    require_role(user, "student")
    require_learning_access(db, user)
    var = db.get(VariantItem, variant_id)
    if var is None or var.status != "approved" or not var.correct_option_id:
        raise not_found("Không tìm thấy biến thể")
    if var.parent_atom_id is not None:
        atom = db.get(LearningAtom, var.parent_atom_id)
        if atom is None or atom.status != "approved":
            raise not_found("Không tìm thấy biến thể")
    result = _grade_variant_answer(db, user, var,
                                   body.selected_variant_option_id,
                                   body.client_uuid, attempt_id=None)
    db.commit()
    return result
