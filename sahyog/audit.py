"""Audit on every patient-scoped read (E6.1).

The audit row is written and committed in its own transaction *before* any data is returned,
so a denied attempt is still recorded and a failed audit write fails the request: we never
read without logging.
"""

from enum import StrEnum

from sqlalchemy.orm import Session

from sahyog.auth import AuthContext
from sahyog.db import get_sessionmaker
from sahyog.models import AuditEvent


class Outcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


def record(
    ctx: AuthContext,
    *,
    table: str,
    record_id: str,
    action: str,
    outcome: Outcome,
) -> None:
    with get_sessionmaker()() as session, session.begin():
        _add(session, ctx, table=table, record_id=record_id, action=action, outcome=outcome)


def _add(
    session: Session, ctx: AuthContext, *, table: str, record_id: str, action: str, outcome: Outcome
) -> None:
    session.add(
        AuditEvent(
            actor_id=ctx.actor_id,
            role=ctx.role.value,
            purpose=ctx.purpose,
            table_name=table,
            record_id=record_id,
            action=action,
            outcome=outcome.value,
            trace_id=ctx.trace_id,
        )
    )
