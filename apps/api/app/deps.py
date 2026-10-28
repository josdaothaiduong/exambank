import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, Workspace
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chưa đăng nhập")
    user_id = decode_access_token(creds.credentials)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token không hợp lệ hoặc đã hết hạn")
    user = db.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Người dùng không tồn tại")
    return user


def get_owned_workspace(workspace_id: uuid.UUID, db: Session, user: User) -> Workspace:
    """Chốt phân quyền cốt lõi của EB-104.

    Chỉ chủ sở hữu (owner_id) mới thấy workspace của mình.
    Workspace của người khác trả 404 (không phải 403) để không lộ sự tồn tại của dữ liệu.
    Mọi API dữ liệu về sau (đề, câu hỏi) đều phải đi qua chốt này / lọc theo workspace_id.
    """
    ws = db.get(Workspace, workspace_id)
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy workspace")
    return ws
