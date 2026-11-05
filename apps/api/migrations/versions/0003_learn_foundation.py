"""Learn Sprint 1 foundation - 24 bang ExamBank Learn.

20 bang loi theo DB-API-SPEC muc 2 cong 4 bang phu EL-007 (L4/L5).
Chi dung op.create_table / op.create_index / op.create_foreign_key.
Khong dung SQL tho, khong chen vi du JSON vao migration (bai hoc 0001).

Revision ID: 0003_learn_foundation
Revises: 0002_password_hash
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0003_learn_foundation"
down_revision = "0002_password_hash"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB(astext_type=sa.Text())
_TS = sa.DateTime(timezone=True)


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
    # ----- Nhom A - Con nguoi va to chuc lop -----
    op.create_table(
        "student_profiles",
        _id(),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        _ws(),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("birth_year", sa.SmallInteger(), nullable=False),
        sa.Column("school_class_name", sa.Text()),
        sa.Column("status", sa.Text(), server_default="pending_consent", nullable=False),
        _created(), _updated(),
        sa.CheckConstraint("birth_year > 1900 AND birth_year <= 2100",
                           name="ck_student_profiles_birth_year"),
        sa.CheckConstraint("status IN ('pending_consent','active','disabled','graduated')",
                           name="ck_student_profiles_status"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_student_profiles_workspace_status", "student_profiles",
                    ["workspace_id", "status"])

    op.create_table(
        "parent_profiles",
        _id(),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        _ws(),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("contact_phone", sa.Text()),
        _created(), _updated(),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "classes",
        _id(),
        _ws(),
        sa.Column("owner_teacher_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=False),
        sa.Column("school_year", sa.Text(), nullable=False),
        sa.Column("join_code", sa.Text(), nullable=False),
        sa.Column("desired_retention", sa.Numeric(3, 2), server_default="0.90", nullable=False),
        sa.Column("archived_at", _TS),
        _created(), _updated(),
        sa.CheckConstraint("grade IN (10,11,12)", name="ck_classes_grade"),
        sa.CheckConstraint("desired_retention BETWEEN 0.85 AND 0.95",
                           name="ck_classes_desired_retention"),
        sa.UniqueConstraint("join_code"),
        sa.UniqueConstraint("workspace_id", "name", "school_year", name="uq_classes_ws_name_year"),
    )

    op.create_table(
        "class_memberships",
        sa.Column("class_id", _UUID, sa.ForeignKey("classes.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("student_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("joined_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("left_at", _TS),
        sa.Column("source", sa.Text(), server_default="teacher_added", nullable=False),
        sa.CheckConstraint("source IN ('teacher_added','join_code')",
                           name="ck_class_memberships_source"),
    )
    op.create_index("ix_class_memberships_student_left", "class_memberships",
                    ["student_user_id", "left_at"])

    op.create_table(
        "parent_links",
        _id(),
        _ws(),
        sa.Column("parent_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("student_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("approved_by", _UUID, sa.ForeignKey("users.id")),
        sa.Column("revoked_at", _TS),
        _created(), _updated(),
        sa.CheckConstraint("relation IN ('father','mother','guardian','other')",
                           name="ck_parent_links_relation"),
        sa.CheckConstraint("status IN ('pending','active','revoked')",
                           name="ck_parent_links_status"),
        sa.CheckConstraint("status <> 'revoked' OR revoked_at IS NOT NULL",
                           name="ck_parent_links_revoked_at"),
        sa.UniqueConstraint("parent_user_id", "student_user_id", name="uq_parent_links_pair"),
    )
    op.create_index("ix_parent_links_parent_status", "parent_links",
                    ["parent_user_id", "status"])
    op.create_index("ix_parent_links_student_status", "parent_links",
                    ["student_user_id", "status"])

    op.create_table(
        "consent_records",
        _id(),
        _ws(),
        sa.Column("student_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("consenter_user_id", _UUID, sa.ForeignKey("users.id")),
        sa.Column("consent_type", sa.Text(), nullable=False),
        sa.Column("consent_scope", _JSONB, nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("recorded_by", _UUID, sa.ForeignKey("users.id")),
        sa.Column("granted_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("withdrawn_at", _TS),
        _created(),
        sa.CheckConstraint("consent_type IN ('student_self','parent_guardian')",
                           name="ck_consent_records_type"),
        sa.CheckConstraint("method IN ('in_app','paper_form')", name="ck_consent_records_method"),
    )
    op.create_index("ix_consent_records_student_type", "consent_records",
                    ["student_user_id", "consent_type", "withdrawn_at"])

    # ----- Nhom B - Giao bai va lam bai -----
    op.create_table(
        "assignments",
        _id(),
        _ws(),
        sa.Column("class_id", _UUID, sa.ForeignKey("classes.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("created_by", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exam_version_id", _UUID, sa.ForeignKey("exam_versions.id")),
        sa.Column("source_exam_id", _UUID, sa.ForeignKey("source_exams.id")),
        sa.Column("assignment_kind", sa.Text(), server_default="regular", nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("opens_at", _TS, nullable=False),
        sa.Column("due_at", _TS, nullable=False),
        sa.Column("answer_release_at", _TS, nullable=False),
        sa.Column("shuffle_questions", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("shuffle_options", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("show_score_immediately", sa.Boolean(), server_default=sa.false(),
                  nullable=False),
        sa.Column("attempt_limit", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("desired_retention_override", sa.Numeric(3, 2)),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("student_snapshot_json", _JSONB),
        _created(), _updated(),
        sa.CheckConstraint("(exam_version_id IS NOT NULL) <> (source_exam_id IS NOT NULL)",
                           name="ck_assignments_one_source"),
        sa.CheckConstraint("assignment_kind IN ('regular','probe')", name="ck_assignments_kind"),
        sa.CheckConstraint("mode IN ('online','paper_quick_entry')", name="ck_assignments_mode"),
        sa.CheckConstraint("due_at > opens_at", name="ck_assignments_due_after_opens"),
        sa.CheckConstraint("status IN ('draft','published','closed')",
                           name="ck_assignments_status"),
        sa.CheckConstraint("desired_retention_override IS NULL OR "
                           "desired_retention_override BETWEEN 0.85 AND 0.95",
                           name="ck_assignments_retention_override"),
    )
    op.create_index("ix_assignments_class_status_due", "assignments",
                    ["class_id", "status", "due_at"])
    op.create_index("ix_assignments_workspace_status", "assignments",
                    ["workspace_id", "status"])

    op.create_table(
        "attempts",
        _id(),
        _ws(),
        sa.Column("assignment_id", _UUID, sa.ForeignKey("assignments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("student_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("status", sa.Text(), server_default="in_progress", nullable=False),
        sa.Column("entry_method", sa.Text(), nullable=False),
        sa.Column("started_at", _TS),
        sa.Column("submitted_at", _TS),
        sa.Column("score_raw", sa.Numeric()),
        sa.Column("score_max", sa.Numeric()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("client_uuid", _UUID, nullable=False),
        sa.Column("shuffle_seed", sa.Text(), nullable=False),
        _created(), _updated(),
        sa.CheckConstraint("status IN ('in_progress','submitted','graded','expired')",
                           name="ck_attempts_status"),
        sa.CheckConstraint("entry_method IN ('online','quick_entry','teacher_entry')",
                           name="ck_attempts_entry_method"),
        sa.UniqueConstraint("client_uuid"),
    )
    op.create_index("ix_attempts_student_submitted", "attempts",
                    ["student_user_id", "submitted_at"])
    op.create_index("ix_attempts_assignment_status", "attempts", ["assignment_id", "status"])

    # ----- Nhom C - Hoc tap va spaced repetition -----
    op.create_table(
        "learning_atoms",
        _id(),
        _ws(),
        sa.Column("headword", sa.Text(), nullable=False),
        sa.Column("atom_type", sa.Text(), nullable=False),
        sa.Column("front_html", sa.Text(), nullable=False),
        sa.Column("front_text", sa.Text(), nullable=False),
        sa.Column("back_html", sa.Text(), nullable=False),
        sa.Column("back_text", sa.Text(), nullable=False),
        sa.Column("meaning_vi", sa.Text(), nullable=False),
        sa.Column("meaning_en", sa.Text()),
        sa.Column("pronunciation_ipa", sa.Text()),
        sa.Column("example_sentence", sa.Text(), nullable=False),
        sa.Column("source_sentence", sa.Text()),
        sa.Column("contrast_with", _JSONB, nullable=False),
        sa.Column("cluster_id", _UUID),
        sa.Column("priority", sa.Text(), server_default="P2", nullable=False),
        sa.Column("common_error_code", sa.Text()),
        sa.Column("cefr_level", sa.Text()),
        sa.Column("source_question_id", _UUID, sa.ForeignKey("question_items.id"),
                  nullable=False),
        sa.Column("source_passage_id", _UUID, sa.ForeignKey("passage_groups.id")),
        sa.Column("status", sa.Text(), server_default="pending_review", nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("answer_provenance", sa.Text(), nullable=False),
        sa.Column("ai_confidence", sa.Numeric(4, 3)),
        sa.Column("needs_teacher_confirmation", sa.Boolean(), server_default=sa.false(),
                  nullable=False),
        sa.Column("dedup_hash", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column("created_by", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", _UUID, sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", _TS),
        _created(), _updated(),
        sa.CheckConstraint("atom_type IN ('vocab','collocation','phrasal_verb','grammar_point',"
                           "'reading_skill','distractor_trap','discourse','paraphrase')",
                           name="ck_learning_atoms_type"),
        sa.CheckConstraint("status IN ('pending_review','approved','rejected','archived')",
                           name="ck_learning_atoms_status"),
        sa.CheckConstraint("origin IN ('ai_generated','teacher_created','rule_based')",
                           name="ck_learning_atoms_origin"),
        sa.CheckConstraint("answer_provenance IN ('teacher_manual','answer_key_table','red_text',"
                           "'highlight','ai_inferred')", name="ck_learning_atoms_provenance"),
        sa.CheckConstraint("priority IN ('P1','P2','P3')", name="ck_learning_atoms_priority"),
        sa.CheckConstraint("common_error_code IS NULL OR common_error_code IN "
                           "('LEX','COL','L1','GRA','ABS','LOG','SPD')",
                           name="ck_learning_atoms_error_code"),
        sa.CheckConstraint("cefr_level IS NULL OR cefr_level IN ('A2','B1','B2')",
                           name="ck_learning_atoms_cefr"),
        sa.UniqueConstraint("workspace_id", "dedup_hash", name="uq_learning_atoms_ws_dedup"),
    )
    op.create_index("ix_learning_atoms_workspace_status", "learning_atoms",
                    ["workspace_id", "status"])
    op.create_index("ix_learning_atoms_source_question", "learning_atoms",
                    ["source_question_id"])
    op.create_index("ix_learning_atoms_ws_priority_status", "learning_atoms",
                    ["workspace_id", "priority", "status"])

    op.create_table(
        "atom_sources",
        sa.Column("atom_id", _UUID, sa.ForeignKey("learning_atoms.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("question_id", _UUID, sa.ForeignKey("question_items.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("source_exam_id", _UUID, sa.ForeignKey("source_exams.id")),
        sa.Column("source_role", sa.Text(), nullable=False),
        sa.CheckConstraint("source_role IN ('correct_answer','distractor','passage_text','stem',"
                           "'paraphrase_target')", name="ck_atom_sources_role"),
    )
    op.create_index("ix_atom_sources_question", "atom_sources", ["question_id"])

    op.create_table(
        "atom_tags",
        sa.Column("atom_id", _UUID, sa.ForeignKey("learning_atoms.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("tag_id", _UUID, sa.ForeignKey("tags.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("is_ai_suggested", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # correct_option_id cua variant_items gan FK sau khi variant_options da ton tai
    op.create_table(
        "variant_items",
        _id(),
        _ws(),
        sa.Column("parent_question_id", _UUID, sa.ForeignKey("question_items.id")),
        sa.Column("parent_atom_id", _UUID, sa.ForeignKey("learning_atoms.id")),
        sa.Column("variant_tier", sa.Text(), nullable=False),
        sa.Column("stem_html", sa.Text(), nullable=False),
        sa.Column("stem_text", sa.Text(), nullable=False),
        sa.Column("correct_option_id", _UUID),
        sa.Column("status", sa.Text(), server_default="pending_review", nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("ai_confidence", sa.Numeric(4, 3)),
        sa.Column("answer_provenance", sa.Text(), nullable=False),
        sa.Column("created_by", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", _UUID, sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", _TS),
        _created(), _updated(),
        sa.CheckConstraint("(parent_question_id IS NOT NULL) <> (parent_atom_id IS NOT NULL)",
                           name="ck_variant_items_one_parent"),
        sa.CheckConstraint("variant_tier IN ('T0','T1','T2')", name="ck_variant_items_tier"),
        sa.CheckConstraint("status IN ('pending_review','approved','rejected','archived')",
                           name="ck_variant_items_status"),
        sa.CheckConstraint("origin IN ('ai_generated','teacher_created','rule_based')",
                           name="ck_variant_items_origin"),
        sa.CheckConstraint("answer_provenance IN ('teacher_manual','answer_key_table','red_text',"
                           "'highlight','ai_inferred')", name="ck_variant_items_provenance"),
    )

    op.create_table(
        "variant_options",
        _id(),
        sa.Column("variant_id", _UUID, sa.ForeignKey("variant_items.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.UniqueConstraint("variant_id", "label", name="uq_variant_options_variant_label"),
    )
    op.create_foreign_key("fk_variant_correct_option", "variant_items", "variant_options",
                          ["correct_option_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "attempt_items",
        sa.Column("attempt_id", _UUID, sa.ForeignKey("attempts.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("question_id", _UUID, sa.ForeignKey("question_items.id"), primary_key=True),
        sa.Column("exam_item_id", _UUID, sa.ForeignKey("exam_items.id")),
        sa.Column("variant_id", _UUID, sa.ForeignKey("variant_items.id")),
        sa.Column("selected_option_id", _UUID, sa.ForeignKey("options.id")),
        sa.Column("selected_variant_option_id", _UUID, sa.ForeignKey("variant_options.id")),
        sa.Column("is_correct", sa.Boolean()),
        sa.Column("confidence_level", sa.SmallInteger()),
        sa.Column("time_spent_seconds", sa.Integer()),
        sa.Column("marked_for_review", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint("confidence_level IS NULL OR confidence_level IN (1,2,3)",
                           name="ck_attempt_items_confidence"),
    )
    op.create_index("ix_attempt_items_question_correct", "attempt_items",
                    ["question_id", "is_correct"])

    op.create_table(
        "review_cards",
        _id(),
        _ws(),
        sa.Column("student_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("atom_id", _UUID, sa.ForeignKey("learning_atoms.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("fsrs_card_id", sa.BigInteger()),
        sa.Column("fsrs_state", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("fsrs_step", sa.SmallInteger()),
        sa.Column("stability", sa.Float()),
        sa.Column("fsrs_difficulty", sa.Float()),
        sa.Column("due_at", _TS, nullable=False),
        sa.Column("last_reviewed_at", _TS),
        sa.Column("reps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lapses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_result", sa.Text()),
        sa.Column("created_from_attempt_id", _UUID, sa.ForeignKey("attempts.id")),
        sa.Column("created_from_question_id", _UUID, sa.ForeignKey("question_items.id")),
        sa.Column("suspended_at", _TS),
        sa.Column("suspended_reason", sa.Text()),
        sa.Column("fsrs_params_version", sa.Text(), server_default="fsrs-default-v6",
                  nullable=False),
        _created(), _updated(),
        sa.CheckConstraint("first_result IS NULL OR first_result IN ('correct_confident',"
                           "'correct_unsure','correct_guessed','wrong','skipped')",
                           name="ck_review_cards_first_result"),
        sa.CheckConstraint("(created_from_attempt_id IS NULL AND created_from_question_id IS NULL) "
                           "OR (created_from_attempt_id IS NOT NULL AND "
                           "created_from_question_id IS NOT NULL)",
                           name="ck_review_cards_created_from_pair"),
        sa.UniqueConstraint("student_user_id", "atom_id", name="uq_review_cards_student_atom"),
    )
    op.create_index("ix_review_cards_student_due_active", "review_cards",
                    ["student_user_id", "due_at"],
                    postgresql_where=sa.text("suspended_at IS NULL"))
    op.create_index("ix_review_cards_student_state_due", "review_cards",
                    ["student_user_id", "fsrs_state", "due_at"])

    op.create_table(
        "review_logs",
        _id(),
        sa.Column("review_card_id", _UUID, sa.ForeignKey("review_cards.id"), nullable=False),
        sa.Column("student_user_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("atom_id", _UUID, sa.ForeignKey("learning_atoms.id"), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=False),
        sa.Column("variant_id", _UUID, sa.ForeignKey("variant_items.id")),
        sa.Column("variant_tier", sa.Text()),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("result", sa.Text()),
        sa.Column("is_probe", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("hint_used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("explanation_viewed", sa.Boolean(), server_default=sa.false(),
                  nullable=False),
        sa.Column("confidence_level", sa.SmallInteger()),
        sa.Column("reviewed_at", _TS, nullable=False),
        sa.Column("scheduled_due_before", _TS),
        sa.Column("elapsed_ms", sa.Integer()),
        sa.Column("session_id", _UUID),
        sa.Column("position_in_session", sa.SmallInteger()),
        sa.Column("state_before", _JSONB, nullable=False),
        sa.Column("state_after", _JSONB, nullable=False),
        sa.Column("fsrs_params_version", sa.Text(), server_default="fsrs-default-v6",
                  nullable=False),
        sa.Column("device_kind", sa.Text()),
        sa.Column("client_uuid", _UUID, nullable=False),
        sa.Column("corrects_log_id", _UUID, sa.ForeignKey("review_logs.id")),
        _created(),
        sa.CheckConstraint("activity_type IN ('flashcard','contrast_card','cloze_variant',"
                           "'quiz_retry','dictation','paraphrase_match','sentence_build',"
                           "'error_spot','probe')", name="ck_review_logs_activity_type"),
        sa.CheckConstraint("rating BETWEEN 1 AND 4", name="ck_review_logs_rating"),
        sa.CheckConstraint("result IS NULL OR result IN ('correct','incorrect')",
                           name="ck_review_logs_result"),
        sa.CheckConstraint("variant_tier IS NULL OR variant_tier IN ('T0','T1','T2')",
                           name="ck_review_logs_variant_tier"),
        sa.CheckConstraint("confidence_level IS NULL OR confidence_level IN (1,2,3)",
                           name="ck_review_logs_confidence"),
        sa.CheckConstraint("device_kind IS NULL OR device_kind IN ('mobile','desktop','unknown')",
                           name="ck_review_logs_device_kind"),
        sa.UniqueConstraint("client_uuid"),
    )
    op.create_index("ix_review_logs_student_reviewed", "review_logs",
                    ["student_user_id", "reviewed_at"])
    op.create_index("ix_review_logs_card_reviewed", "review_logs",
                    ["review_card_id", "reviewed_at"])
    op.create_index("ix_review_logs_atom", "review_logs", ["atom_id"])

    op.create_table(
        "mastery_snapshots",
        _id(),
        _ws(),
        sa.Column("student_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("tag_id", _UUID, sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("atoms_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("atoms_due", sa.Integer(), server_default="0", nullable=False),
        sa.Column("atoms_reviewed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("atoms_mature", sa.Integer(), server_default="0", nullable=False),
        sa.Column("probe_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("probe_correct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retention_estimate", sa.Numeric(4, 3)),
        sa.Column("computed_at", _TS, nullable=False),
        sa.UniqueConstraint("student_user_id", "tag_id", "period_start",
                            name="uq_mastery_student_tag_period"),
    )
    op.create_index("ix_mastery_workspace_period", "mastery_snapshots",
                    ["workspace_id", "period_start"])

    # ----- Nhom D - Bao cao, van hanh, an toan -----
    op.create_table(
        "notifications",
        _id(),
        _ws(),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", _JSONB, nullable=False),
        sa.Column("scheduled_for", _TS, nullable=False),
        sa.Column("sent_at", _TS),
        sa.Column("read_at", _TS),
        sa.Column("channel", sa.Text(), server_default="in_app", nullable=False),
        _created(),
        sa.CheckConstraint("kind IN ('assignment_new','review_due','weekly_report_ready',"
                           "'leech_alert','consent_request')", name="ck_notifications_kind"),
    )
    op.create_index("ix_notifications_user_read_sched", "notifications",
                    ["user_id", "read_at", "scheduled_for"])

    op.create_table(
        "audit_logs",
        _id(),
        _ws(),
        sa.Column("actor_user_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", _UUID),
        sa.Column("metadata", _JSONB, nullable=False),
        _created(),
    )
    op.create_index("ix_audit_logs_workspace_created", "audit_logs",
                    ["workspace_id", "created_at"])
    op.create_index("ix_audit_logs_actor_created", "audit_logs",
                    ["actor_user_id", "created_at"])

    op.create_table(
        "ai_generation_jobs",
        _id(),
        _ws(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("source_question_id", _UUID, sa.ForeignKey("question_items.id")),
        sa.Column("source_atom_id", _UUID, sa.ForeignKey("learning_atoms.id")),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("tokens_in", sa.Integer()),
        sa.Column("tokens_out", sa.Integer()),
        sa.Column("cost_usd_estimate", sa.Numeric(10, 6)),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("error_log", _JSONB, nullable=False),
        _created(),
        sa.Column("finished_at", _TS),
        sa.CheckConstraint("kind IN ('atom_extract','variant_gen','explain','solve')",
                           name="ck_ai_generation_jobs_kind"),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed')",
                           name="ck_ai_generation_jobs_status"),
    )
    op.create_index("ix_ai_jobs_workspace_created", "ai_generation_jobs",
                    ["workspace_id", "created_at"])
    op.create_index("ix_ai_jobs_source_question_kind", "ai_generation_jobs",
                    ["source_question_id", "kind"])

    # ----- Bang phu EL-007 - L4 Quan tri (additive, 0 sua bang loi) -----
    op.create_table(
        "enrollment_requests",
        _id(),
        _ws(),
        sa.Column("class_id", _UUID, sa.ForeignKey("classes.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("requester_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("requester_role", sa.Text(), server_default="student", nullable=False),
        sa.Column("requester_display_name", sa.Text(), nullable=False),
        sa.Column("requester_birth_year", sa.SmallInteger()),
        sa.Column("join_code_used", sa.Text()),
        sa.Column("message", sa.Text()),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("decided_by", _UUID, sa.ForeignKey("users.id")),
        sa.Column("decided_at", _TS),
        _created(), _updated(),
        sa.CheckConstraint("requester_role IN ('student','parent')",
                           name="ck_enrollment_requests_role"),
        sa.CheckConstraint("status IN ('pending','approved','rejected')",
                           name="ck_enrollment_requests_status"),
    )
    op.create_index("ix_enrollment_requests_class_status", "enrollment_requests",
                    ["class_id", "status"])

    op.create_table(
        "student_admin_records",
        _id(),
        _ws(),
        sa.Column("class_id", _UUID, sa.ForeignKey("classes.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("student_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("admin_status", sa.Text(), server_default="active", nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("updated_by", _UUID, sa.ForeignKey("users.id"), nullable=False),
        _created(), _updated(),
        sa.CheckConstraint("admin_status IN ('active','paused')",
                           name="ck_student_admin_records_status"),
        sa.UniqueConstraint("class_id", "student_user_id", name="uq_student_admin_class_student"),
    )

    # ----- Bang phu EL-007 - L5 Tich hop ngoai (cache/log, xoa di tra lai duoc) -----
    op.create_table(
        "lookup_cache",
        _id(),
        sa.Column("workspace_id", _UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("lookup_key", sa.Text(), nullable=False),
        sa.Column("payload_json", _JSONB, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_license", sa.Text()),
        sa.Column("fetched_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("kind IN ('dictionary','vi_meaning','related')",
                           name="ck_lookup_cache_kind"),
        sa.CheckConstraint("source IN ('freedict','datamuse','gemini')",
                           name="ck_lookup_cache_source"),
        sa.UniqueConstraint("kind", "lookup_key", name="uq_lookup_cache_kind_key"),
    )

    op.create_table(
        "api_usage_logs",
        _id(),
        sa.Column("workspace_id", _UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("endpoint_kind", sa.Text(), nullable=False),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id")),
        sa.Column("class_id", _UUID, sa.ForeignKey("classes.id")),
        sa.Column("units", sa.Integer()),
        sa.Column("est_cost", sa.Numeric(10, 6)),
        _created(),
    )
    op.create_index("ix_api_usage_workspace_created", "api_usage_logs",
                    ["workspace_id", "created_at"])
    op.create_index("ix_api_usage_provider_created", "api_usage_logs",
                    ["provider", "created_at"])


_DROP_ORDER = [
    "api_usage_logs", "lookup_cache", "student_admin_records", "enrollment_requests",
    "ai_generation_jobs", "audit_logs", "notifications", "mastery_snapshots",
    "review_logs", "review_cards", "attempt_items", "variant_options", "variant_items",
    "atom_tags", "atom_sources", "learning_atoms", "attempts", "assignments",
    "consent_records", "parent_links", "class_memberships", "classes",
    "parent_profiles", "student_profiles",
]


def downgrade() -> None:
    op.drop_constraint("fk_variant_correct_option", "variant_items", type_="foreignkey")
    for table in _DROP_ORDER:
        op.drop_table(table)
