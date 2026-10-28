"""EB-104 — Bảo mật: hash mật khẩu (PBKDF2-SHA256, thư viện chuẩn) + JWT HS256 (PyJWT)."""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

_PBKDF2_ROUNDS = 210_000
TOKEN_TTL_HOURS = 24 * 7


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, rounds, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(hours=TOKEN_TTL_HOURS)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> str | None:
    """Trả user_id hoặc None nếu token sai/hết hạn."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
