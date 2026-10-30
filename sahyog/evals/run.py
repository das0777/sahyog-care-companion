"""`make eval`: the safety and W1 path evals, all on the fake model and free to run. Exits non-zero
on any gate failure. Real accuracy and recall come from `make eval-live`, never from here.

GUARDRAILS=off switches the red-flag gate and the egress scrubber off. That run must fail: it proves
the evals test the guardrails rather than pass on their own.
"""

import argparse
import json
import statistics
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.evals.egress import build_payloads, detect
from sahyog.evals.w1_paths import w1_paths
from sahyog.evals.w2_ask_paths import w2_ask_paths
from sahyog.evals.w2_ingest import w2_ingest
from sahyog.llm.adapters.fake import FakeModel
from sahyog.llm.gateway import ModelGateway, Prices, Route
from sahyog.llm.schemas import Ack, SpecialtyMatch
from sahyog.llm.types import SchemaRejected
from sahyog.models import Patient
from sahyog.safety.deid import KnownIdentity, Scrubber
from sahyog.safety.red_flags import RedFlagEngine

EVALS = Path("evals")
REPORTS = EVALS / "reports"


@dataclass
class Check:
    id: str
    name: str
    target: str
    result: str
    passed: bool | None  # None: reported, not gated

    @property
    def status(self) -> str:
        return {True: "PASS", False: "FAIL", None: "info"}[self.passed]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sahyog.evals.run")
    parser.add_argument("--guardrails", choices=["on", "off"], default="on")
    parser.add_argument("--w2-seed", type=int, default=None, help="Fresh W2 sample reports")
    args = parser.parse_args(argv)
    guardrails = args.guardrails == "on"

    with get_sessionmaker()() as session:
        engine = RedFlagEngine.from_db(session)
        checks, details = _red_flags(engine, guardrails)
        egress_checks, egress_details = _egress(session, guardrails)
    checks += egress_checks
    details |= egress_details
    schema_checks, schema_details = _schemas()
    checks += schema_checks
    details |= schema_details
    checks += _symptoms_survive()
    path_rows, path_details = w1_paths(guardrails)
    checks += [Check(*row) for row in path_rows]
    details |= path_details
    ingest_rows, ingest_details = (
        w2_ingest(guardrails, args.w2_seed) if args.w2_seed else w2_ingest(guardrails)
    )
    checks += [Check(*row) for row in ingest_rows]
    details |= ingest_details
    ask_rows, ask_details = w2_ask_paths(guardrails)
    checks += [Check(*row) for row in ask_rows]
    details |= ask_details

    gated = [c for c in checks if c.passed is not None]
    ok = all(c.passed for c in gated)
    _print(checks, guardrails, engine.version, ok)
    _write(checks, details, guardrails, engine.version, ok)
    return 0 if ok else 1


# ---- W1 red flags ------------------------------------------------------------------------


def _red_flags(engine: RedFlagEngine, guardrails: bool):
    cases = _cases("golden")
    probes = _cases("probe1") + _cases("probe2")
    rows, times = [], []
    for c in cases:
        d = engine.check(c["input"], enabled=guardrails)
        times.append(d.elapsed_ms)
        rows.append(
            {
                "id": c["id"],
                "expect_red_flag": c["expect"]["red_flag"],
                "red_flag": d.red_flag,
                "language_expected": c["language"],
                "language": d.language,
                "fired": [{"rule": f.rule_id, "matched": list(f.matched)} for f in d.fired],
            }
        )
    red = [r for r in rows if r["expect_red_flag"]]
    calm = [r for r in rows if not r["expect_red_flag"]]
    caught = sum(r["red_flag"] for r in red)
    false_alarms = [r["id"] for r in calm if r["red_flag"]]
    missed = [r["id"] for r in red if not r["red_flag"]]
    lang_ok = sum(r["language"] == r["language_expected"] for r in rows)
    probe_missed = [
        c["id"] for c in probes if not engine.check(c["input"], enabled=guardrails).red_flag
    ]
    p95 = _p95(times)
    checks = [
        Check(
            "B1",
            "Red-flag recall (golden)",
            "100%",
            f"{caught}/{len(red)}" + (f" — missed {', '.join(missed)}" if missed else ""),
            caught == len(red),
        ),
        Check(
            "B1r",
            "Red-flag recall (blind probes, now regression)",
            "100%",
            f"{len(probes) - len(probe_missed)}/{len(probes)}"
            + (f" — missed {', '.join(probe_missed)}" if probe_missed else ""),
            not probe_missed,
        ),
        Check(
            "B3",
            "False alarms on non-emergencies",
            "≤ 20% (reported)",
            f"{len(false_alarms)}/{len(calm)}"
            + (f" — {', '.join(false_alarms)}" if false_alarms else ""),
            None,
        ),
        Check(
            "B4",
            "Language detection",
            "≥ 90%",
            f"{lang_ok}/{len(rows)}",
            lang_ok / len(rows) >= 0.9,
        ),
        Check("B12", "Red-flag check latency", "p95 < 50 ms", f"p95 {p95:.2f} ms", p95 < 50),
    ]
    return checks, {"red_flags": rows}


# ---- egress replay -----------------------------------------------------------------------


def _egress(session, guardrails: bool):
    payloads = build_payloads(session)
    patients = {
        p.patient_id: p
        for p in session.execute(
            select(Patient).where(Patient.patient_id.in_([x.patient_id for x in payloads]))
        ).scalars()
    }
    vendor = FakeModel({"received": True}, name="vendor")
    gateway = ModelGateway(
        {"vendor": vendor},
        {"large": Route("vendor", "fake-large")},
        {},
        Prices(Path("config/prices.yaml")),
        scrub_enabled=guardrails,
    )
    for p in payloads:
        gateway.complete(
            "large",
            system="Answer briefly.",
            prompt=p.text,
            schema=Ack,
            trace_id=uuid.uuid4().hex,
            patient=KnownIdentity.from_patient(patients[p.patient_id]),
        )
    sent = [r.prompt for r in vendor.received]
    leaks, kept, total, rows = [], 0, 0, []
    unlisted_total = unlisted_leaked = 0
    for p, text in zip(payloads, sent, strict=True):
        found = detect(p, text)
        leaks += found
        retained = [c for c in p.clinical if c in text]
        kept += len(retained)
        total += len(p.clinical)
        for item in p.planted:
            if item.unlisted:
                unlisted_total += 1
                unlisted_leaked += any(lk.value == item.value for lk in found)
        rows.append(
            {
                "id": p.id,
                "sent": text,
                "leaks": [vars(lk) for lk in found],
                "clinical_lost": [c for c in p.clinical if c not in text],
            }
        )
    retention = kept / total if total else 1.0
    checks = [
        Check(
            "B5",
            f"Identifiers leaving the boundary ({len(payloads)} payloads)",
            "0",
            f"{len(leaks)}" + (f" — e.g. {leaks[0].payload_id} {leaks[0].kind}" if leaks else ""),
            not leaks,
        ),
        Check(
            "B6",
            "Clinical content kept after scrubbing",
            "≥ 95%",
            f"{kept}/{total} ({retention:.1%})",
            retention >= 0.95,
        ),
        Check(
            "B5b",
            "Names not in the name list caught (NER and rules)",
            "reported",
            f"{unlisted_total - unlisted_leaked}/{unlisted_total}",
            None,
        ),
    ]
    return checks, {"egress": rows}


# ---- schema rejection --------------------------------------------------------------------


def _schemas():
    rows, rejected, repaired = [], 0, 0
    files = sorted((EVALS / "fixtures/malformed").glob("*.json"))
    for f in files:
        fixture = json.loads(f.read_text())
        gateway = ModelGateway(
            {"vendor": FakeModel(fixture["reply"], name="vendor")},
            {"small": Route("vendor", "fake-small")},
            {},
            Prices(Path("config/prices.yaml")),
        )
        try:
            gateway.complete(
                "small",
                system="Match a specialty.",
                prompt="test",
                schema=SpecialtyMatch,
                trace_id=uuid.uuid4().hex,
            )
            repaired += 1
            outcome = "accepted"
        except SchemaRejected:
            rejected += 1
            outcome = "rejected"
        rows.append({"fixture": f.name, "description": fixture["description"], "outcome": outcome})
    checks = [
        Check(
            "B7",
            "Malformed model output rejected",
            "100%, 0 repaired",
            f"{rejected}/{len(files)} rejected, {repaired} accepted",
            rejected == len(files) and repaired == 0,
        )
    ]
    return checks, {"schemas": rows}


# ---- symptom words survive scrubbing -------------------------------------------------------


def _symptoms_survive():
    """Patient words must reach the model. These cases hold no identifiers, so any change is damage:
    S1 measured lab values and medicines but not symptoms, and spaCy was eating them."""
    scrubber = Scrubber()
    cases = [c for n in ("golden", "match", "probe1", "probe2", "probe3") for c in _cases(n)]
    damaged = []
    for c in cases:
        text = c["input"]
        for variant in (text, text[0].upper() + text[1:], "Thanks. " + text[0].upper() + text[1:]):
            if scrubber.scrub(variant).text != variant:
                damaged.append(c["id"])
                break
    return [
        Check(
            "C22",
            "Symptom text unchanged by the scrubber",
            "≥ 98%",
            f"{len(cases) - len(damaged)}/{len(cases)}"
            + (f" — {', '.join(damaged[:5])}" if damaged else ""),
            (len(cases) - len(damaged)) / len(cases) >= 0.98,
        )
    ]


# ---- report ------------------------------------------------------------------------------


def _print(checks: list[Check], guardrails: bool, version: str, ok: bool) -> None:
    print(f"\nOffline evals — guardrails {'ON' if guardrails else 'OFF'} — rules {version}\n")
    w = max(len(c.name) for c in checks)
    print(f"{'':4}  {'Check':<{w}}  {'Target':<18}  {'Status':<6}  Result")
    for c in checks:
        print(f"{c.id:<4}  {c.name:<{w}}  {c.target:<18}  {c.status:<6}  {c.result}")
    print(f"\n{'ALL GATES PASS' if ok else 'GATE FAILURE'}\n")


def _write(checks, details, guardrails: bool, version: str, ok: bool) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = f"offline-{_today()}" + ("" if guardrails else "-guardrails-off")
    summary = {
        "stage": "S2",
        "date": _today(),
        "guardrails": guardrails,
        "rules_version": version,
        "all_gates_pass": ok,
        "checks": [vars(c) | {"status": c.status} for c in checks],
    }
    (REPORTS / f"{stem}.json").write_text(
        json.dumps(summary | {"details": details}, indent=2, ensure_ascii=False) + "\n"
    )
    lines = [
        f"# Offline eval report · {summary['date']}",
        "",
        f"Guardrails **{'on' if guardrails else 'off'}** · rules `{version}` · "
        f"**{'all gates pass' if ok else 'gate failure'}**",
        "",
        "| # | Check | Target | Status | Result |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {c.id} | {c.name} | {c.target} | {c.status} | {c.result} |" for c in checks]
    lines += ["", f"Details per case and payload: `{stem}.json`.", ""]
    (REPORTS / f"{stem}.md").write_text("\n".join(lines))
    print(f"Report: {REPORTS / stem}.md")


def _today() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()


def _cases(name: str) -> list[dict]:
    return [json.loads(line) for line in (EVALS / f"w1/{name}.jsonl").read_text().splitlines()]


def _p95(values: list[float]) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=20)[-1]


if __name__ == "__main__":
    sys.exit(main())
