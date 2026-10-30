"""Who may read whose records. Checked on every read and never cached: consent can expire between
two questions, and an expired consent must return nothing (E3.2)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog.auth import AuthContext, Role
from sahyog.models import Consent

READ_SCOPE = "records:read"


def can_read(session: Session, ctx: AuthContext, patient_id: str) -> bool:
    if ctx.role == Role.PATIENT:
        return ctx.actor_id == patient_id
    if ctx.role == Role.CAREGIVER:
        return (
            session.scalar(
                select(Consent.consent_id).where(
                    Consent.patient_id == patient_id,
                    Consent.grantee_id == ctx.actor_id,
                    Consent.scope == READ_SCOPE,
                    Consent.purpose == ctx.purpose,
                    Consent.expires_at > datetime.now(UTC),
                )
            )
            is not None
        )
    return False  # Clinical roles arrive with W3; until then they don't read through W2
