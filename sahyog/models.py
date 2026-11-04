"""The 14 tables of the spec's data model: the pack's 12 entities plus Clinic and AuditEvent.

Sensitivity classes (spec, Data model): direct identifiers never leave the boundary; clinical
content leaves only de-identified; operational data may leave but is audited when tied to a
patient. Each table's contract lives in docs/data-contracts/.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Clinic(Base):
    __tablename__ = "clinic"

    clinic_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(60))
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)


class Specialty(Base):
    __tablename__ = "specialty"

    specialty_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    # Starter red-flag phrases read by the S1 rule engine; reviewed_by stays null until a
    # clinician signs off the crosswalk row.
    red_flag_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


class Doctor(Base):
    __tablename__ = "doctor"

    doctor_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    specialty_id: Mapped[str] = mapped_column(ForeignKey("specialty.specialty_id"), index=True)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.clinic_id"), index=True)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)))
    synthetic: Mapped[bool] = mapped_column(server_default="true")


class Patient(Base):
    __tablename__ = "patient"

    patient_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    abha_id: Mapped[str] = mapped_column(String(17), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    dob: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(8))
    synthetic: Mapped[bool] = mapped_column(server_default="true")


class Consent(Base):
    __tablename__ = "consent"

    consent_id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.patient_id"), index=True)
    grantee_id: Mapped[str] = mapped_column(String(16), index=True)
    scope: Mapped[str] = mapped_column(String(40))
    purpose: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class Document(Base):
    __tablename__ = "document"

    doc_id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.patient_id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    uri: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    phi_status: Mapped[str] = mapped_column(String(16), server_default="identified")
    uploaded_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'parsed', 'indexed', 'failed')", name="document_status_valid"
        ),
    )


class DocChunk(Base):
    __tablename__ = "doc_chunk"

    chunk_id: Mapped[uuid.UUID] = _uuid_pk()
    doc_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document.doc_id", ondelete="CASCADE"), index=True
    )
    # Denormalised so the retrieval filter on patient runs in SQL without a join (spec W2)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.patient_id"), index=True)
    page: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True)
    )

    __table_args__ = (
        Index(
            "ix_doc_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_doc_chunk_tsv", "tsv", postgresql_using="gin"),
    )


class Slot(Base):
    """A booking block: a time window with capacity, not a single appointment (decision E2.4)."""

    __tablename__ = "slot"

    slot_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctor.doctor_id"))
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.clinic_id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int]

    __table_args__ = (
        CheckConstraint("capacity > 0", name="slot_capacity_positive"),
        CheckConstraint("ends_at > starts_at", name="slot_ends_after_start"),
        Index("ix_slot_doctor_starts", "doctor_id", "starts_at"),
    )


class Appointment(Base):
    __tablename__ = "appointment"

    appt_id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.patient_id"), index=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey("slot.slot_id"))
    token_no: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), server_default="booked")
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    booked_by: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = _created_at()
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Measured durations feed the later live wait-time estimate (Pro extension)
    consult_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consult_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("slot_id", "token_no", name="uq_appointment_slot_token"),
        CheckConstraint("token_no >= 1", name="appointment_token_positive"),
        CheckConstraint(
            "status IN ('booked', 'checked_in', 'in_consult', 'done', 'cancelled', 'no_show')",
            name="appointment_status_valid",
        ),
    )


class Encounter(Base):
    __tablename__ = "encounter"

    encounter_id: Mapped[uuid.UUID] = _uuid_pk()
    appt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appointment.appt_id"), index=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctor.doctor_id"))
    started_at: Mapped[datetime] = _created_at()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audio_uri: Mapped[str | None] = mapped_column(Text)  # object expires within 24 h
    transcript_uri: Mapped[str | None] = mapped_column(Text)


class ClinicalNote(Base):
    """Immutable once signed: a trigger rejects any UPDATE or DELETE of a signed row."""

    __tablename__ = "clinical_note"

    note_id: Mapped[uuid.UUID] = _uuid_pk()
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounter.encounter_id"))
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctor.doctor_id"))
    soap_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(server_default="1")
    supersedes: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinical_note.note_id"))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("encounter_id", "version", name="uq_note_encounter_version"),
    )


class Prescription(Base):
    __tablename__ = "prescription"

    rx_id: Mapped[uuid.UUID] = _uuid_pk()
    note_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical_note.note_id"), index=True)
    medicine_id: Mapped[str] = mapped_column(String(16))
    dose: Mapped[str] = mapped_column(String(80))  # only ever from the doctor
    substitute_ok: Mapped[bool] = mapped_column(server_default="false")


class MedicineStock(Base):
    __tablename__ = "medicine_stock"

    medicine_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.clinic_id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    composition: Mapped[str] = mapped_column(String(160))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    qty: Mapped[int]
    as_of: Mapped[date] = mapped_column(Date)


class AuditEvent(Base):
    """Append-only: a trigger rejects UPDATE and DELETE. Kept for one year."""

    __tablename__ = "audit_event"

    event_id: Mapped[uuid.UUID] = _uuid_pk()
    actor_id: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(40))
    table_name: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(8))
    trace_id: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("outcome IN ('allowed', 'denied')", name="audit_outcome_valid"),
    )
