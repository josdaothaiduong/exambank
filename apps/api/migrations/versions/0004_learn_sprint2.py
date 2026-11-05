"""Learn Sprint 2 - 3 bang hau-de & bien the (EL-201/EL-204).

DB-API-SPEC giao endpoint S5-S7/T7-T13 cho Sprint 2 nhung chua dac ta bang
chua noi dung hau-de, tien do hau-de va luot lam bien the - 3 bang nay lap
cho do. Chi dung op.create_table / op.create_index, khong SQL tho.

Revision ID: 0004_learn_sprint2
Revises: 0003_learn_foundation
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_learn_sprint2"
down_revision = "0003_learn_foundation"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB(astext_type=sa.Text())
_TS = sa.DateTime(timezone=True)

_STATUS_CK = "status IN ('pending_review','approved','rejected','archived')"
_PROVENANCE_CK = ("answer_provenance IN ('teacher_manual','answer_key_table','red_text',"
                  "'highlight','ai_inferred')")


def _id():
    return sa.Column("id", _UUID, primary_key=True)


def _created():
    return sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False)


def _updated():
    return sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False)


def _ws():
    return sa.Column("workspace_id", _UUID,
                     sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "post_test_contents",
        _id(), _ws(),
        sa.Column("question_id", _UUID,
                  sa.ForeignKey("question_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_json", _JSONB, nullable=False),
        sa.Column("status", sa.Text(), server_default="pending_review", nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("answer_provenance", sa.Text(), nullable=False),
        sa.Column("ai_confidence", sa.Numeric(4, 3)),
        sa.Column("needs_teacher_confirmation", sa.Boolean(), server_default=sa.false(),
                  nullable=False),
        sa.Column("created_by", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", _UUID, sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", _TS),
        _created(), _updated(),
        sa.CheckConstraint(_STATUS_CK, name="ck_post_test_contents_status"),
        sa.CheckConstraint("origin IN ('ai_generated','teacher_created','rule_based')",
                           name="ck_post_test_contents_origin"),
        sa.CheckConstraint(_PROVENANCE_CK, name="ck_post_test_contents_provenance"),
        sa.UniqueConstraint("question_id", name="uq_post_test_contents_question"),
    )
    op.create_index("ix_post_test_contents_workspace_status", "post_test_contents",
                    ["workspace_id", "status"])

    op.create_table(
        "post_test_progress",
        _id(), _ws(),
        sa.Column("attempt_id", _UUID,
                  sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", _UUID,
                  sa.ForeignKey("question_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_user_id", _UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_step", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("step1_choice_key", sa.Text()),
        sa.Column("step1_correct", sa.Boolean()),
        sa.Column("step3_selected_keys", _JSONB),
        sa.Column("step3_correct", sa.Boolean()),
        sa.Column("step4_variant_id", _UUID, sa.ForeignKey("variant_items.id")),
        sa.Column("step4_correct", sa.Boolean()),
        sa.Column("status", sa.Text(), server_default="in_progress", nullable=False),
        sa.Column("completed_at", _TS),
        _created(), _updated(),
        sa.CheckConstraint("current_step BETWEEN 0 AND 4", name="ck_pt_progress_step"),
        sa.CheckConstraint("status IN ('in_progress','completed')",
                           name="ck_pt_progress_status"),
        sa.UniqueConstraint("attempt_id", "question_id",
                            name="uq_pt_progress_attempt_question"),
    )
    op.create_index("ix_pt_progress_student", "post_test_progress",
                    ["student_user_id", "status"])

    op.create_table(
        "variant_attempts",
        _id(), _ws(),
        sa.Column("student_user_id", _UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", _UUID,
                  sa.ForeignKey("variant_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_id", _UUID, sa.ForeignKey("attempts.id", ondelete="CASCADE")),
        sa.Column("selected_variant_option_id", _UUID,
                  sa.ForeignKey("variant_options.id")),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("client_uuid", _UUID, unique=True, nullable=False),
        _created(),
    )
    op.create_index("ix_variant_attempts_student_variant", "variant_attempts",
                    ["student_user_id", "variant_id"])
    op.create_index("ix_variant_attempts_attempt", "variant_attempts", ["attempt_id"])


def downgrade() -> None:
    op.drop_table("variant_attempts")
    op.drop_table("post_test_progress")
    op.drop_table("post_test_contents")
