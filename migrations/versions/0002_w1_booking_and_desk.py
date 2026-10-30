"""W1 booking and the front desk: desk tickets, SMS stub, idempotency records.

Also fixes S0's token rule. Cancelled appointments kept their token and the capacity trigger rejects
any token above capacity, so a cancelled place could never be booked again. Uniqueness now applies
to active appointments only.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_appointment_slot_token", "appointment", type_="unique")
    for name, column in (
        ("uq_appointment_active_token", "token_no"),
        ("uq_appointment_active_patient", "patient_id"),
    ):
        op.create_index(
            name,
            "appointment",
            ["slot_id", column],
            unique=True,
            postgresql_where=sa.text("status <> 'cancelled'"),
        )

    op.create_table(
        "desk_ticket",
        sa.Column(
            "ticket_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(10), server_default="open", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "reason_codes", postgresql.ARRAY(sa.String(60)), server_default="{}", nullable=False
        ),
        sa.Column("patient_text", sa.Text()),
        sa.Column("owner", sa.String(16)),
        sa.Column("patient_id", sa.String(8), sa.ForeignKey("patient.patient_id")),
        sa.Column("appt_id", sa.Uuid(), sa.ForeignKey("appointment.appt_id")),
        sa.Column("slot_id", sa.String(24), sa.ForeignKey("slot.slot_id")),
        sa.Column("thread_id", sa.String(40)),
        sa.Column("trace_id", sa.String(40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('er', 'safety_unchecked', 'low_confidence', 'advice_request', "
            "'no_availability', 'model_failure', 'ai_booking', 'late_block')",
            name="desk_ticket_kind_valid",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'claimed', 'closed')", name="desk_ticket_status_valid"
        ),
    )
    op.create_index("ix_desk_ticket_patient_id", "desk_ticket", ["patient_id"])
    op.create_index("ix_desk_ticket_queue", "desk_ticket", ["status", "priority", "created_at"])
    op.create_index(
        "uq_desk_ticket_thread_kind",
        "desk_ticket",
        ["thread_id", "kind"],
        unique=True,
        postgresql_where=sa.text("thread_id IS NOT NULL AND kind <> 'ai_booking'"),
    )
    op.create_index(
        "uq_desk_ticket_appt_kind",
        "desk_ticket",
        ["appt_id", "kind"],
        unique=True,
        postgresql_where=sa.text("appt_id IS NOT NULL"),
    )
    op.create_index(
        "uq_desk_ticket_late_block",
        "desk_ticket",
        ["slot_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'late_block'"),
    )

    op.create_table(
        "sms_outbox",
        sa.Column(
            "sms_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True
        ),
        sa.Column("patient_id", sa.String(8), sa.ForeignKey("patient.patient_id"), nullable=False),
        sa.Column("template", sa.String(40), nullable=False),
        sa.Column("vars", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("appt_id", sa.Uuid(), sa.ForeignKey("appointment.appt_id")),
        sa.Column("trace_id", sa.String(40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_sms_outbox_patient_id", "sms_outbox", ["patient_id"])

    op.create_table(
        "idempotency_record",
        sa.Column("actor_id", sa.String(16), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_record")
    op.drop_table("sms_outbox")
    op.drop_table("desk_ticket")
    op.drop_index("uq_appointment_active_patient", table_name="appointment")
    op.drop_index("uq_appointment_active_token", table_name="appointment")
    op.create_unique_constraint("uq_appointment_slot_token", "appointment", ["slot_id", "token_no"])
