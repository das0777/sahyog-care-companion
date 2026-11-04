"""Traces: one row per model call, for the operations tiles and cost per consultation.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trace_span",
        sa.Column(
            "span_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True
        ),
        sa.Column("trace_id", sa.String(40), nullable=False),
        sa.Column("workflow", sa.String(16), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40)),
        sa.Column("model", sa.String(80)),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Float(), server_default="0", nullable=False),
        sa.Column("scrubbed", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_trace_span_trace", "trace_span", ["trace_id"])
    op.create_index("ix_trace_span_workflow_at", "trace_span", ["workflow", "at"])


def downgrade() -> None:
    op.drop_table("trace_span")
