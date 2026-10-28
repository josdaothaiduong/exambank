import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Tag, User, Workspace  # noqa: F401

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine, tables=[User.__table__, Workspace.__table__, Tag.__table__])
TestingSession = sessionmaker(bind=engine)


def _override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_db
client = TestClient(app)


def _register(email, name="Teacher", pw="matkhau123"):
    return client.post("/api/v1/auth/register",
                       json={"email": email, "full_name": name, "password": pw})


@pytest.fixture(scope="module")
def user_a():
    r = _register("a@school.edu.vn", "Teacher A")
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="module")
def user_b():
    r = _register("b@school.edu.vn", "Teacher B")
    assert r.status_code == 201, r.text
    return r.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_creates_default_workspace(user_a):
    assert user_a["default_workspace_id"]
    r = client.get("/api/v1/workspaces", headers=_auth(user_a["access_token"]))
    assert r.status_code == 200 and len(r.json()) == 1


def test_duplicate_email_409(user_a):
    r = _register("a@school.edu.vn", "Teacher A2")
    assert r.status_code == 409


def test_login_ok_and_wrong_password_401(user_a):
    ok = client.post("/api/v1/auth/login", json={"email": "a@school.edu.vn", "password": "matkhau123"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    bad = client.post("/api/v1/auth/login", json={"email": "a@school.edu.vn", "password": "sai-mat-khau"})
    assert bad.status_code == 401


def test_me_requires_token(user_a):
    assert client.get("/api/v1/auth/me").status_code == 401
    r = client.get("/api/v1/auth/me", headers=_auth(user_a["access_token"]))
    assert r.status_code == 200 and r.json()["email"] == "a@school.edu.vn"
    r = client.get("/api/v1/auth/me", headers=_auth("token-gia"))
    assert r.status_code == 401


def test_workspace_isolation_between_users(user_a, user_b):
    # A tạo thêm 1 workspace riêng
    r = client.post("/api/v1/workspaces", headers=_auth(user_a["access_token"]),
                    json={"name": "Tổ Tiếng Anh — A", "school_name": "THPT A"})
    assert r.status_code == 201
    ws_a_id = r.json()["id"]

    # B liệt kê: chỉ thấy workspace mặc định của B, không thấy của A
    r = client.get("/api/v1/workspaces", headers=_auth(user_b["access_token"]))
    ids_b = [w["id"] for w in r.json()]
    assert ws_a_id not in ids_b and len(ids_b) == 1

    # B truy cập trực tiếp workspace của A -> 404 (không lộ tồn tại)
    r = client.get(f"/api/v1/workspaces/{ws_a_id}", headers=_auth(user_b["access_token"]))
    assert r.status_code == 404

    # A truy cập workspace của chính mình -> 200
    r = client.get(f"/api/v1/workspaces/{ws_a_id}", headers=_auth(user_a["access_token"]))
    assert r.status_code == 200 and r.json()["name"] == "Tổ Tiếng Anh — A"

    # Chưa đăng nhập -> 401
    assert client.get("/api/v1/workspaces").status_code == 401


def test_password_not_stored_in_plaintext():
    db = TestingSession()
    user = db.query(User).filter_by(email="a@school.edu.vn").one()
    assert user.password_hash.startswith("pbkdf2_sha256$")
    assert "matkhau123" not in user.password_hash
    db.close()
