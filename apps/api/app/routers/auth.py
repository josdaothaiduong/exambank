from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# Validate email bằng pattern tối giản, tránh phụ thuộc thêm gói email-validator.
from pydantic import field_validator
import re

from app.db import get_db
from app.deps import get_current_user
from app.models import User, Workspace
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str
    full_name: str = Field(min_length=1)
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Email không hợp lệ")
        return v.lower()


class LoginIn(BaseModel):
    email: str
    password: str


def _user_out(user: User) -> dict:
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "role": user.role}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=body.email).one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email đã được đăng ký")
    user = User(email=body.email, full_name=body.full_name,
                password_hash=hash_password(body.password), role="teacher")
    db.add(user)
    db.flush()
    # Mỗi giáo viên có sẵn 1 workspace cá nhân ngay khi đăng ký
    ws = Workspace(owner_id=user.id, name=f"Cá nhân — {body.full_name}")
    db.add(ws)
    db.commit()
    db.refresh(user)
    return {"access_token": create_access_token(str(user.id)), "token_type": "bearer",
            "user": _user_out(user), "default_workspace_id": str(ws.id)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email.lower()).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email hoặc mật khẩu không đúng")
    return {"access_token": create_access_token(str(user.id)), "token_type": "bearer",
            "user": _user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_out(user)
