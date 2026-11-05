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
from app.models import (
    Assignment, Attempt, AttemptItem, ClassMembership, ConsentRecord,
    EnrollmentRequest, Exam, ExamItem, ExamVersion, LearnClass, Option,
    ParentLink, ParentProfile, PassageGroup, QuestionItem, QuestionStatus,
    SourceExam, StudentProfile, User, Workspace,
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
