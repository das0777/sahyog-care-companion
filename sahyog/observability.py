"""Traces and operations tiles. One row per model call, joined to audit by trace id.

The spec names Langfuse. It needs its own ClickHouse, Redis and storage, more than this 8 GB
machine should carry, so traces go to Postgres behind one function, and a Langfuse exporter can
replace `record_span` without touching a graph. See ADR 0004.
"""

import logging
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import func, select

from sahyog.db import get_sessionmaker
from sahyog.llm.types import CallRecord
from sahyog.models import AuditEvent, ClinicalNote, DocChunk, Encounter, ScribeJob, TraceSpan

log = logging.getLogger("sahyog.trace")
WORKFLOW_BY_PROMPT = (
    ("W1 second pass", "safety"),
    ("W1 specialty", "w1"),
    ("W1 clarify", "w1"),
    ("W2 grade", "w2"),
    ("W2 answer", "w2"),
    ("W2 judge", "eval"),
    ("W3 draft", "w3"),
    ("W3 medicines", "w3"),
)


def workflow_of(system: str) -> tuple[str, str]:
    for prefix, workflow in WORKFLOW_BY_PROMPT:
        if system.startswith(prefix):
            return workflow, prefix
    return "other", system[:40]


def record_span(record: CallRecord, system: str, outcome: str) -> None:
    """Never lets a tracing fault stop a clinical workflow."""
    workflow, name = workflow_of(system)
    try:
        with get_sessionmaker().begin() as session:
            session.add(
                TraceSpan(
                    trace_id=record.trace_id[:40],
                    workflow=workflow,
                    name=name,
                    provider=record.provider,
                    model=record.model,
                    outcome=outcome,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    cost_usd=record.cost_usd,
                    latency_ms=sum(a.latency_ms for a in record.attempts),
                    scrubbed=record.scrubbed,
                )
            )
    except Exception:  # noqa: BLE001 - see the docstring
        log.exception("trace write failed")


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) < 2:
        return values[0]
    return statistics.quantiles(values, n=20)[-1]


def tiles(*, hours: int = 24) -> dict:
    """Each tile is one query over traces, audit or notes. A tile with no source doesn't exist."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    with get_sessionmaker()() as session:
        spans = list(session.execute(select(TraceSpan).where(TraceSpan.at >= since)).scalars())
        reviews = [
            v
            for v in session.scalars(
                select(ClinicalNote.review_seconds).where(ClinicalNote.created_at >= since)
            )
            if v is not None
        ]
        denied = session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.at >= since, AuditEvent.outcome == "denied")
        )
        reads = session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.at >= since)
        )
    by_workflow: dict[str, list[TraceSpan]] = {}
    for s in spans:
        by_workflow.setdefault(s.workflow, []).append(s)
    out = {
        "window_hours": hours,
        "model_calls": len(spans),
        "cost_usd": round(sum(s.cost_usd for s in spans), 4),
        "failed_calls": sum(s.outcome != "ok" for s in spans),
        "audit_events": reads,
        "audit_denied": denied,
        "review_seconds_median": round(statistics.median(reviews), 1) if reviews else None,
        "review_under_90s": f"{sum(r < 90 for r in reviews)}/{len(reviews)}" if reviews else None,
        "workflows": {},
    }
    for workflow, group in sorted(by_workflow.items()):
        out["workflows"][workflow] = {
            "calls": len(group),
            "p95_call_ms": round(_p95([s.latency_ms for s in group]) or 0),
            "input_tokens": sum(s.input_tokens for s in group),
            "output_tokens": sum(s.output_tokens for s in group),
            "cost_usd": round(sum(s.cost_usd for s in group), 4),
        }
    return out


def cost_per_consultation(prices_file: str = "config/prices.yaml", *, days: int = 30) -> dict:
    """The formula, with its inputs, from what actually ran. Prices come only from the price file.

    cost = (LLM tokens for triage, answers and scribe + STT minutes + embeddings + storage +
    compute) / consultations. STT and embeddings run locally, so they carry a compute price, not a
    per-token one. Compute and storage are inputs in the price file, because this Mac's bill means
    nothing: a real figure needs the hospital's infrastructure price.
    """
    prices = yaml.safe_load(Path(prices_file).read_text())
    infra = prices.get("infrastructure", {})
    since = datetime.now(UTC) - timedelta(days=days)
    with get_sessionmaker()() as session:
        spans = list(session.execute(select(TraceSpan).where(TraceSpan.at >= since)).scalars())
        consultations = session.scalar(
            select(func.count())
            .select_from(Encounter)
            .where(Encounter.started_at >= since, Encounter.ended_at.is_not(None))
        )
        stt_seconds = (
            session.scalar(
                select(func.coalesce(func.sum(ScribeJob.transcribe_seconds), 0.0)).where(
                    ScribeJob.created_at >= since
                )
            )
            or 0.0
        )
        chunks = session.scalar(select(func.count()).select_from(DocChunk))
    per_run = _typical_run_costs(spans)
    llm = sum(s.cost_usd for s in spans if s.workflow in ("w1", "w2", "w3", "safety"))
    stt = stt_seconds / 60 * infra.get("stt_usd_per_minute", 0.0)
    embed = chunks * infra.get("embedding_usd_per_chunk", 0.0)
    fixed = infra.get("storage_compute_usd_per_month", 0.0) * days / 30
    total = llm + stt + embed + fixed
    return {
        "formula": "(LLM + STT + embeddings + storage and compute) / consultations",
        "prices_as_of": str(prices["as_of"]),
        "infrastructure_prices_are_placeholders": infra.get("placeholder", True),
        "window_days": days,
        "consultations": consultations,
        "llm_usd": round(llm, 4),
        "stt_usd": round(stt, 4),
        "embeddings_usd": round(embed, 4),
        "storage_compute_usd": round(fixed, 4),
        "per_consultation_usd": round(total / consultations, 4) if consultations else None,
        "typical_model_cost_usd": per_run,
    }


def _typical_run_costs(spans: list[TraceSpan]) -> dict:
    """Mean model cost of one run of each workflow. A trace is one request or one job, so this
    doesn't depend on how many consultations happened to be signed in the window. The total
    assumes one triage turn, one record question and one note."""
    by_trace: dict[str, list[TraceSpan]] = {}
    for s in spans:
        by_trace.setdefault(s.trace_id, []).append(s)
    groups: dict[str, list[float]] = {"triage": [], "record_answer": [], "note_draft": []}
    for group in by_trace.values():
        kinds = {s.workflow for s in group}
        cost = sum(s.cost_usd for s in group)
        if "w1" in kinds:
            groups["triage"].append(cost)
        elif "w2" in kinds:
            groups["record_answer"].append(cost)
        elif "w3" in kinds:
            groups["note_draft"].append(cost)
    means = {k: round(statistics.mean(v), 5) if v else None for k, v in groups.items()}
    known = [v for v in means.values() if v is not None]
    means["one_of_each"] = round(sum(known), 5) if known else None
    means["runs_counted"] = {k: len(v) for k, v in groups.items()}
    return means
