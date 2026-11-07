"""AI de xuat do kho - bo sung ai_solutions.difficulty.

Tinh nang "AI de xuat do kho": khi AI giai mot cau, no dong thoi de xuat muc
do kho (NB/TH/VD/VDC) de giao vien bam ap dung neu khong tu xac dinh duoc.
Cot difficulty dang chuoi thuan (String(8), nullable) luu de xuat do;
suggested_difficulty (enum, co tu 0001) van duoc pipeline ghi dong bo.
None = AI khong de xuat. Migration nay chi them cot, khong sua 0001-0004.

Revision ID: 0005_ai_difficulty
Revises: 0004_learn_sprint2
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_ai_difficulty"
down_revision = "0004_learn_sprint2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_solutions", sa.Column("difficulty", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_solutions", "difficulty")
