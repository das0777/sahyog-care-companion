"""W2 ingest: the job queue, quarantine, embedding cache, and OCR marking on chunks.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'er', 'safety_unchecked', 'low_confidence', 'advice_request', "
    "'no_availability', 'model_failure', 'ai_booking', 'late_block'"
)
NEW_KINDS = OLD_KINDS + ", 'doc_held', 'doc_quarantine'"


def upgrade() -> None:
    op.drop_constraint("document_status_valid", "document", type_="check")
    op.create_check_constraint(
        "document_status_valid",
        "document",
        "status IN ('queued', 'parsed', 'indexed', 'held', 'failed')",
    )
    op.add_column("document", sa.Column("content_hash", sa.String(64)))
    op.create_index(
        "uq_document_patient_content",
        "document",
        ["patient_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("status <> 'failed' AND content_hash IS NOT NULL"),
    )
    op.add_column(
        "doc_chunk", sa.Column("source", sa.String(8), server_default="text", nullable=False)
    )
    op.add_column("doc_chunk", sa.Column("ocr_confidence", sa.Float()))
    op.drop_constraint("desk_ticket_kind_valid", "desk_ticket", type_="check")
    op.create_check_constraint("desk_ticket_kind_valid", "desk_ticket", f"kind IN ({NEW_KINDS})")

    op.create_table(
        "ingest_job",
        sa.Column(
            "job_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True
        ),
        sa.Column(
            "doc_id",
            sa.Uuid(),
            sa.ForeignKey("document.doc_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("patient_id", sa.String(8), sa.ForeignKey("patient.patient_id"), nullable=False),
        sa.Column("status", sa.String(10), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("pages_total", sa.Integer()),
        sa.Column("pages_ocr", sa.Integer()),
        sa.Column("chunks_indexed", sa.Integer()),
        sa.Column("chunks_quarantined", sa.Integer()),
        sa.Column("reason", sa.Text()),
        sa.Column("trace_id", sa.String(40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name="ingest_job_status_valid"
        ),
    )
    op.create_index("ix_ingest_job_patient_id", "ingest_job", ["patient_id"])
    op.create_index("ix_ingest_job_queue", "ingest_job", ["status", "created_at"])

    op.create_table(
        "quarantined_chunk",
        sa.Column(
            "quarantine_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "doc_id",
            sa.Uuid(),
            sa.ForeignKey("document.doc_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("patient_id", sa.String(8), sa.ForeignKey("patient.patient_id"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_quarantined_chunk_doc_id", "quarantined_chunk", ["doc_id"])

    op.create_table(
        "embedding_cache",
        sa.Column("content_hash", sa.String(64), primary_key=True),
        sa.Column("model", sa.String(80), primary_key=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(1024), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("embedding_cache")
    op.drop_table("quarantined_chunk")
    op.drop_table("ingest_job")
    op.drop_constraint("desk_ticket_kind_valid", "desk_ticket", type_="check")
    op.create_check_constraint("desk_ticket_kind_valid", "desk_ticket", f"kind IN ({OLD_KINDS})")
    op.drop_column("doc_chunk", "ocr_confidence")
    op.drop_column("doc_chunk", "source")
    op.drop_index("uq_document_patient_content", table_name="document")
    op.drop_column("document", "content_hash")
    op.drop_constraint("document_status_valid", "document", type_="check")
    op.create_check_constraint(
        "document_status_valid", "document", "status IN ('queued', 'parsed', 'indexed', 'failed')"
    )
