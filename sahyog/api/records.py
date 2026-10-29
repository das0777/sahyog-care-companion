from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog import audit
from sahyog.auth import AuthContext, Role, get_auth_context
from sahyog.db import get_session
from sahyog.models import AuditEvent, Clinic, Doctor, Patient, Specialty

router = APIRouter()

# S0 access rule for a patient record. Caregivers wait for consent enforcement in S4, so they
# are denied for now rather than allowed without a consent check.
PATIENT_READERS = {Role.DOCTOR, Role.DESK}


class MeOut(BaseModel):
    actor_id: str
    role: Role
    purpose: str
    trace_id: str


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: str
    abha_id: str
    name: str
    dob: date
    phone: str
    language: str
    synthetic: bool


class DoctorOut(BaseModel):
    doctor_id: str
    name: str
    specialty: str
    clinic: str
    city: str
    languages: list[str]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    at: datetime
    actor_id: str
    role: str
    purpose: str
    table_name: str
    record_id: str
    action: str
    outcome: str
    trace_id: str


@router.get("/me", response_model=MeOut, tags=["platform"])
def me(ctx: AuthContext = Depends(get_auth_context)) -> MeOut:
    return MeOut(**ctx.__dict__)


@router.get("/patients/{patient_id}", response_model=PatientOut, tags=["records"])
def read_patient(
    patient_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> Patient:
    allowed = ctx.role in PATIENT_READERS or (
        ctx.role == Role.PATIENT and ctx.actor_id == patient_id
    )
    outcome = audit.Outcome.ALLOWED if allowed else audit.Outcome.DENIED
    audit.record(ctx, table="patient", record_id=patient_id, action="read", outcome=outcome)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted to read this record")
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    return patient


@router.get("/doctors", response_model=list[DoctorOut], tags=["directory"])
def list_doctors(
    specialty: str | None = None,
    city: str | None = None,
    limit: int = Query(default=20, le=100),
    _: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> list[DoctorOut]:
    # Directory data is operational and not tied to a patient, so it is not audited
    stmt = (
        select(Doctor, Specialty.name, Clinic.name, Clinic.city)
        .join(Specialty, Doctor.specialty_id == Specialty.specialty_id)
        .join(Clinic, Doctor.clinic_id == Clinic.clinic_id)
        .order_by(Doctor.doctor_id)
        .limit(limit)
    )
    if specialty:
        stmt = stmt.where(Specialty.name.ilike(specialty))
    if city:
        stmt = stmt.where(Clinic.city.ilike(city))
    return [
        DoctorOut(
            doctor_id=d.doctor_id,
            name=d.name,
            specialty=spec,
            clinic=clinic,
            city=c,
            languages=d.languages,
        )
        for d, spec, clinic, c in session.execute(stmt)
    ]


@router.get("/audit", response_model=list[AuditOut], tags=["compliance"])
def who_saw(
    record_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> list[AuditEvent]:
    """E6.1: answer "who saw this record?" in one query. The query itself is audited too."""
    allowed = ctx.role == Role.COMPLIANCE
    outcome = audit.Outcome.ALLOWED if allowed else audit.Outcome.DENIED
    audit.record(ctx, table="audit_event", record_id=record_id, action="query", outcome=outcome)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Compliance role required")
    stmt = select(AuditEvent).where(AuditEvent.record_id == record_id).order_by(AuditEvent.at)
    return list(session.scalars(stmt))
