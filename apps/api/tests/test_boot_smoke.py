"""Boot smoke — bắt 2 lỗi chỉ lộ khi chạy thật, test thường không thấy:

1. `python -m app.seed` chạy dạng SCRIPT (đúng lệnh trong docker-compose):
   khối __main__ phải chạy được — từng vỡ vì __main__ nằm TRƯỚC định nghĩa
   seed_templates -> NameError -> api không khởi động nổi (sự cố 2026-11-06).
2. Transport Redis của Celery worker: kombu mới đòi redis-py >= 6.1 trong khi
   requirements ghim redis 5.* -> worker chết ngay khi khởi động
   (VersionMismatch). Test này ép kombu tạo client: lỗi phiên bản = fail,
   lỗi kết nối (môi trường test không có broker) = bỏ qua.
"""
import runpy

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as app_db
from app.db import Base
from app.models import ExamTemplate, Tag  # noqa: F401 — đăng ký bảng vào metadata


def test_seed_script_entrypoint(monkeypatch, capsys):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)
    monkeypatch.setattr(app_db, "SessionLocal", testing_session)

    # Chạy đúng như `python -m app.seed`: thực thi module với __name__ == "__main__".
    runpy.run_module("app.seed", run_name="__main__")

    out = capsys.readouterr().out
    assert "Seed taxonomy" in out
    assert "Seed templates" in out
    with testing_session() as s:
        assert s.query(Tag).count() >= 68
        assert s.query(ExamTemplate).filter_by(is_system=True).count() == 3


def test_celery_broker_transport_version_compatible():
    from kombu.exceptions import VersionMismatch

    from app.worker import celery_app

    conn = celery_app.connection()
    try:
        conn.default_channel  # ép kombu dựng redis client -> kiểm tra phiên bản ở đây
    except VersionMismatch as e:
        raise AssertionError(f"redis-py không tương thích với kombu: {e}")
    except Exception:
        pass  # Không có broker trong môi trường test: lỗi kết nối là bình thường.
