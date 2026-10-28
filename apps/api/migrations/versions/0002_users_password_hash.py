"""EB-104 — Bổ sung users.password_hash.

Schema Bước 1 chưa có cột lưu mật khẩu (thiếu sót phát hiện khi làm Auth):
bảng users chỉ có email/full_name/role. Migration này thêm cột, không sửa migration 0001.

Revision ID: 0002_password_hash
Revises: 0001_initial
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_password_hash"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
