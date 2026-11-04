"""Initial schema: the 14 spec tables plus the database-level safety rules.

Triggers enforce what must never depend on application code: the audit log is append-only,
a signed clinical note is immutable, and a booking token can never exceed the block capacity.

Revision ID: 0001
Revises:
Create Date: 2026-10-29 18:22:53.776634
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SAFETY_RULES = [
    # Audit log is append-only (E6.1): no row may change or disappear
    """
    CREATE FUNCTION reject_audit_change() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit_event is append-only: % rejected', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER audit_event_append_only
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION reject_audit_change()
    """,
    """
    CREATE TRIGGER audit_event_no_truncate
    BEFORE TRUNCATE ON audit_event
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_change()
    """,
    # A signed note is immutable (E5.2): edits create a new version instead
    """
    CREATE FUNCTION reject_signed_note_change() RETURNS trigger AS $$
    BEGIN
        IF OLD.signed_at IS NOT NULL THEN
            RAISE EXCEPTION 'clinical_note % is signed and immutable: % rejected', OLD.note_id, TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER clinical_note_signed_immutable
    BEFORE UPDATE OR DELETE ON clinical_note
    FOR EACH ROW EXECUTE FUNCTION reject_signed_note_change()
    """,
    # A block is never overbooked (E2.3): token number must fit the block's capacity
    """
    CREATE FUNCTION check_token_within_capacity() RETURNS trigger AS $$
    DECLARE
        cap integer;
    BEGIN
        SELECT capacity INTO cap FROM slot WHERE slot_id = NEW.slot_id;
        IF NEW.token_no > cap THEN
            RAISE EXCEPTION 'token % exceeds capacity % of slot %', NEW.token_no, cap, NEW.slot_id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER appointment_token_within_capacity
    BEFORE INSERT OR UPDATE OF token_no, slot_id ON appointment
    FOR EACH ROW EXECUTE FUNCTION check_token_within_capacity()
    """,
]

DROP_SAFETY_RULES = [
    "DROP TRIGGER IF EXISTS appointment_token_within_capacity ON appointment",
    "DROP FUNCTION IF EXISTS check_token_within_capacity()",
    "DROP TRIGGER IF EXISTS clinical_note_signed_immutable ON clinical_note",
    "DROP FUNCTION IF EXISTS reject_signed_note_change()",
    "DROP TRIGGER IF EXISTS audit_event_no_truncate ON audit_event",
    "DROP TRIGGER IF EXISTS audit_event_append_only ON audit_event",
    "DROP FUNCTION IF EXISTS reject_audit_change()",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "audit_event",
        sa.Column(
            "event_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("actor_id", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("table_name", sa.String(length=40), nullable=False),
        sa.Column("record_id", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=8), nullable=False),
        sa.Column("trace_id", sa.String(length=40), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("outcome IN ('allowed', 'denied')", name="audit_outcome_valid"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(op.f("ix_audit_event_record_id"), "audit_event", ["record_id"], unique=False)
    op.create_table(
        "clinic",
        sa.Column("clinic_id", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("city", sa.String(length=60), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=False),
        sa.Column("closes_at", sa.Time(), nullable=False),
        sa.PrimaryKeyConstraint("clinic_id"),
    )
    op.create_table(
        "patient",
        sa.Column("patient_id", sa.String(length=8), nullable=False),
        sa.Column("abha_id", sa.String(length=17), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("dob", sa.Date(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("synthetic", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("patient_id"),
        sa.UniqueConstraint("abha_id"),
    )
    op.create_table(
        "specialty",
        sa.Column("specialty_id", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "red_flag_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("specialty_id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "consent",
        sa.Column(
            "consent_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("patient_id", sa.String(length=8), nullable=False),
        sa.Column("grantee_id", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patient.patient_id"],
        ),
        sa.PrimaryKeyConstraint("consent_id"),
    )
    op.create_index(op.f("ix_consent_grantee_id"), "consent", ["grantee_id"], unique=False)
    op.create_index(op.f("ix_consent_patient_id"), "consent", ["patient_id"], unique=False)
    op.create_table(
        "doctor",
        sa.Column("doctor_id", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("specialty_id", sa.String(length=8), nullable=False),
        sa.Column("clinic_id", sa.String(length=8), nullable=False),
        sa.Column("languages", sa.ARRAY(sa.String(length=8)), nullable=False),
        sa.Column("synthetic", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinic.clinic_id"],
        ),
        sa.ForeignKeyConstraint(
            ["specialty_id"],
            ["specialty.specialty_id"],
        ),
        sa.PrimaryKeyConstraint("doctor_id"),
    )
    op.create_index(op.f("ix_doctor_clinic_id"), "doctor", ["clinic_id"], unique=False)
    op.create_index(op.f("ix_doctor_specialty_id"), "doctor", ["specialty_id"], unique=False)
    op.create_table(
        "document",
        sa.Column("doc_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("patient_id", sa.String(length=8), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("phi_status", sa.String(length=16), server_default="identified", nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'parsed', 'indexed', 'failed')", name="document_status_valid"
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patient.patient_id"],
        ),
        sa.PrimaryKeyConstraint("doc_id"),
    )
    op.create_index(op.f("ix_document_patient_id"), "document", ["patient_id"], unique=False)
    op.create_table(
        "medicine_stock",
        sa.Column("medicine_id", sa.String(length=16), nullable=False),
        sa.Column("clinic_id", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("composition", sa.String(length=160), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinic.clinic_id"],
        ),
        sa.PrimaryKeyConstraint("medicine_id", "clinic_id"),
    )
    op.create_table(
        "doc_chunk",
        sa.Column(
            "chunk_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("doc_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.String(length=8), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["doc_id"], ["document.doc_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patient.patient_id"],
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(op.f("ix_doc_chunk_doc_id"), "doc_chunk", ["doc_id"], unique=False)
    op.create_index(
        "ix_doc_chunk_embedding_hnsw",
        "doc_chunk",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(op.f("ix_doc_chunk_patient_id"), "doc_chunk", ["patient_id"], unique=False)
    op.create_index("ix_doc_chunk_tsv", "doc_chunk", ["tsv"], unique=False, postgresql_using="gin")
    op.create_table(
        "slot",
        sa.Column("slot_id", sa.String(length=24), nullable=False),
        sa.Column("doctor_id", sa.String(length=8), nullable=False),
        sa.Column("clinic_id", sa.String(length=8), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.CheckConstraint("capacity > 0", name="slot_capacity_positive"),
        sa.CheckConstraint("ends_at > starts_at", name="slot_ends_after_start"),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinic.clinic_id"],
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctor.doctor_id"],
        ),
        sa.PrimaryKeyConstraint("slot_id"),
    )
    op.create_index("ix_slot_doctor_starts", "slot", ["doctor_id", "starts_at"], unique=False)
    op.create_table(
        "appointment",
        sa.Column(
            "appt_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("patient_id", sa.String(length=8), nullable=False),
        sa.Column("slot_id", sa.String(length=24), nullable=False),
        sa.Column("token_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="booked", nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("booked_by", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consult_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consult_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('booked', 'checked_in', 'in_consult', 'done', 'cancelled', 'no_show')",
            name="appointment_status_valid",
        ),
        sa.CheckConstraint("token_no >= 1", name="appointment_token_positive"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patient.patient_id"],
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"],
            ["slot.slot_id"],
        ),
        sa.PrimaryKeyConstraint("appt_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("slot_id", "token_no", name="uq_appointment_slot_token"),
    )
    op.create_index(op.f("ix_appointment_patient_id"), "appointment", ["patient_id"], unique=False)
    op.create_table(
        "encounter",
        sa.Column(
            "encounter_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("appt_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.String(length=8), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audio_uri", sa.Text(), nullable=True),
        sa.Column("transcript_uri", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["appt_id"],
            ["appointment.appt_id"],
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctor.doctor_id"],
        ),
        sa.PrimaryKeyConstraint("encounter_id"),
    )
    op.create_index(op.f("ix_encounter_appt_id"), "encounter", ["appt_id"], unique=False)
    op.create_table(
        "clinical_note",
        sa.Column(
            "note_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("encounter_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.String(length=8), nullable=False),
        sa.Column("soap_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("supersedes", sa.UUID(), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctor.doctor_id"],
        ),
        sa.ForeignKeyConstraint(
            ["encounter_id"],
            ["encounter.encounter_id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes"],
            ["clinical_note.note_id"],
        ),
        sa.PrimaryKeyConstraint("note_id"),
        sa.UniqueConstraint("encounter_id", "version", name="uq_note_encounter_version"),
    )
    op.create_table(
        "prescription",
        sa.Column("rx_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("note_id", sa.UUID(), nullable=False),
        sa.Column("medicine_id", sa.String(length=16), nullable=False),
        sa.Column("dose", sa.String(length=80), nullable=False),
        sa.Column("substitute_ok", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["clinical_note.note_id"],
        ),
        sa.PrimaryKeyConstraint("rx_id"),
    )
    op.create_index(op.f("ix_prescription_note_id"), "prescription", ["note_id"], unique=False)
    for statement in SAFETY_RULES:
        op.execute(statement)


def downgrade() -> None:
    for statement in DROP_SAFETY_RULES:
        op.execute(statement)
    op.drop_index(op.f("ix_prescription_note_id"), table_name="prescription")
    op.drop_table("prescription")
    op.drop_table("clinical_note")
    op.drop_index(op.f("ix_encounter_appt_id"), table_name="encounter")
    op.drop_table("encounter")
    op.drop_index(op.f("ix_appointment_patient_id"), table_name="appointment")
    op.drop_table("appointment")
    op.drop_index("ix_slot_doctor_starts", table_name="slot")
    op.drop_table("slot")
    op.drop_index("ix_doc_chunk_tsv", table_name="doc_chunk", postgresql_using="gin")
    op.drop_index(op.f("ix_doc_chunk_patient_id"), table_name="doc_chunk")
    op.drop_index(
        "ix_doc_chunk_embedding_hnsw",
        table_name="doc_chunk",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_doc_chunk_doc_id"), table_name="doc_chunk")
    op.drop_table("doc_chunk")
    op.drop_table("medicine_stock")
    op.drop_index(op.f("ix_document_patient_id"), table_name="document")
    op.drop_table("document")
    op.drop_index(op.f("ix_doctor_specialty_id"), table_name="doctor")
    op.drop_index(op.f("ix_doctor_clinic_id"), table_name="doctor")
    op.drop_table("doctor")
    op.drop_index(op.f("ix_consent_patient_id"), table_name="consent")
    op.drop_index(op.f("ix_consent_grantee_id"), table_name="consent")
    op.drop_table("consent")
    op.drop_table("specialty")
    op.drop_table("patient")
    op.drop_table("clinic")
    op.drop_index(op.f("ix_audit_event_record_id"), table_name="audit_event")
    op.drop_table("audit_event")
