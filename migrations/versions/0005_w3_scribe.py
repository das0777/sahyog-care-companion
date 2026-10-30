"""W3 scribe: the job queue, stock reservations, edit history on notes.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clinical_note", sa.Column("edit_history", postgresql.JSONB(), server_default="[]")
    )
    op.add_column("clinical_note", sa.Column("review_seconds", sa.Float()))
    op.add_column("encounter", sa.Column("audio_deleted_at", sa.DateTime(timezone=True)))
    op.create_table(
        "scribe_job",
        sa.Column(
            "job_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True
        ),
        sa.Column(
            "encounter_id", sa.Uuid(), sa.ForeignKey("encounter.encounter_id"), nullable=False
        ),
        sa.Column("thread_id", sa.String(40), nullable=False, unique=True),
        sa.Column("status", sa.String(10), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("transcript", sa.Text()),
        sa.Column("transcribe_seconds", sa.Float()),
        sa.Column("reason", sa.Text()),
        sa.Column("trace_id", sa.String(40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_scribe_job_queue", "scribe_job", ["status", "created_at"])
    op.create_table(
        "stock_reservation",
        sa.Column(
            "reservation_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("clinical_note.note_id"), nullable=False),
        sa.Column("medicine_id", sa.String(16), nullable=False),
        sa.Column("clinic_id", sa.String(8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("stock_reservation")
    op.drop_table("scribe_job")
    op.drop_column("encounter", "audio_deleted_at")
    op.drop_column("clinical_note", "review_seconds")
    op.drop_column("clinical_note", "edit_history")
