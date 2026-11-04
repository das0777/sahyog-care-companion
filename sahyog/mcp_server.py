"""MCP server (Architect tier): scheduling and stock tools, under the same audit as the API.

Identity comes from the caller's token, never from a tool argument, so a model driving these tools
can't book for someone else. Run with: SAHYOG_TOKEN=<token> python -m sahyog.mcp_server
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from mcp.server.mcpserver import MCPServer

from sahyog import audit
from sahyog.auth import ALGORITHM, AuthContext, Role, new_trace_id
from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.scheduling import service
from sahyog.scribe.stock import CsvStockAdapter

mcp = MCPServer("sahyog")


class NotPermitted(Exception):
    pass


def _context() -> AuthContext:
    claims = jwt.decode(
        os.environ.get("SAHYOG_TOKEN", ""),
        get_settings().jwt_secret,
        algorithms=[ALGORITHM],
        options={"require": ["sub", "role", "exp"]},
    )
    role = Role(claims["role"])
    return AuthContext(claims["sub"], role, f"mcp:{role.value}"[:40], new_trace_id())


def _log(ctx: AuthContext, table: str, record: str, action: str, allowed: bool = True) -> None:
    outcome = audit.Outcome.ALLOWED if allowed else audit.Outcome.DENIED
    audit.record(ctx, table=table, record_id=record[:40], action=action, outcome=outcome)


@mcp.tool()
def search_doctors(specialty_id: str, language: str | None = None) -> list[dict]:
    """Up to three doctors of a specialty with their next free block."""
    ctx = _context()
    _log(ctx, "doctor", specialty_id, "mcp:search")
    with get_sessionmaker()() as session:
        return [vars(c) for c in service.search_doctors(session, specialty_id, language=language)]


@mcp.tool()
def list_slots(doctor_id: str, days: int = 14) -> list[dict]:
    """A doctor's free blocks over the next days."""
    ctx = _context()
    _log(ctx, "slot", doctor_id, "mcp:slots")
    now = datetime.now(UTC)
    with get_sessionmaker()() as session:
        return [
            vars(b)
            for b in service.list_slots(
                session, doctor_id, now, now + timedelta(days=min(days, 30))
            )
        ]


@mcp.tool()
def reserve_slot(slot_id: str, idem_key: str) -> dict:
    """Book a place for the patient named in the token. Only a patient's token can book this way."""
    ctx = _context()
    if ctx.role != Role.PATIENT:
        _log(ctx, "appointment", slot_id, "mcp:reserve", False)
        raise NotPermitted("Only a patient's token can book")
    _log(ctx, "appointment", slot_id, "mcp:reserve")
    key = f"mcp:{uuid.uuid5(uuid.NAMESPACE_OID, ctx.actor_id + idem_key)}"
    with get_sessionmaker().begin() as session:
        r = service.reserve_slot(
            session, slot_id=slot_id, patient_id=ctx.actor_id, idem_key=key, booked_by="mcp"
        )
    return {
        "appt_id": str(r.appt_id),
        "token_no": r.token_no,
        "block_start": r.block_start.isoformat(),
        "block_end": r.block_end.isoformat(),
    }


@mcp.tool()
def stock_lookup(medicine: str, dose: str, clinic_id: str) -> dict:
    """Stock for a medicine at a clinic, with its age. Doctors and pharmacists only."""
    ctx = _context()
    if ctx.role not in (Role.DOCTOR, Role.PHARMACIST):
        _log(ctx, "medicine_stock", medicine, "mcp:stock", False)
        raise NotPermitted("Doctors and pharmacists only")
    _log(ctx, "medicine_stock", medicine, "mcp:stock")
    return vars(CsvStockAdapter(Path(get_settings().stock_csv)).lookup(medicine, dose, clinic_id))


if __name__ == "__main__":
    mcp.run()
