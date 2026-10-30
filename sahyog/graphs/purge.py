"""Thread state expires after 30 days (spec, Memory). Checkpoints hold the patient's own words, so
they go, along with the words copied onto closed tickets and old idempotency replies."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, text, update

from sahyog.db import get_sessionmaker
from sahyog.graphs.runtime import get_runtime
from sahyog.models import DeskTicket, IdempotencyRecord


def purge(*, days: int = 30) -> dict[str, int]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with get_sessionmaker().begin() as session:
        threads = session.scalars(
            text(
                "SELECT thread_id FROM checkpoints GROUP BY thread_id "
                "HAVING max(checkpoint->>'ts') < :cutoff"
            ),
            {"cutoff": cutoff.isoformat()},
        ).all()
        tickets = session.execute(
            update(DeskTicket)
            .where(
                DeskTicket.status == "closed",
                DeskTicket.closed_at < cutoff,
                DeskTicket.patient_text.is_not(None),
            )
            .values(patient_text=None)
        ).rowcount
        replies = session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.created_at < cutoff)
        ).rowcount
    saver = get_runtime().checkpointer
    for thread_id in threads:
        saver.delete_thread(thread_id)
    return {"threads": len(threads), "ticket_texts": tickets, "idempotency_replies": replies}
