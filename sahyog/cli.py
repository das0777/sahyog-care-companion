"""Developer commands: `python -m sahyog.cli seed` and `python -m sahyog.cli token`."""

import argparse
import json
import sys

from sahyog.auth import Role, issue_token
from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.seed.generate import seed


def _seed(_: argparse.Namespace) -> None:
    settings = get_settings()
    with get_sessionmaker()() as session, session.begin():
        result = seed(session, random_seed=settings.seed_random_seed, tz=settings.timezone)
    width = max(len(k) for k in result.counts)
    for table, n in result.counts.items():
        print(f"{table:<{width}}  {n:>7,}")
    print(f"{'fingerprint':<{width}}  {result.fingerprint}")


def _token(args: argparse.Namespace) -> None:
    print(issue_token(Role(args.role), args.id))


def _redflag(args: argparse.Namespace) -> None:
    from sahyog.safety.red_flags import RedFlagEngine

    with get_sessionmaker()() as session:
        engine = RedFlagEngine.from_db(session)
    d = engine.check(args.text, age_years=args.age)
    print(f"language   {d.language}")
    print(f"decision   {'RED FLAG -> emergency desk' if d.red_flag else 'no red flag'}")
    for f in d.fired:
        print(f"rule       {f.rule_id} ({f.kind}): {f.label}")
        print(f"  matched  {', '.join(f.matched)}")
    print(f"rules      {d.rules_version}   ({d.elapsed_ms:.1f} ms)")


def _scrub(args: argparse.Namespace) -> None:
    from sahyog.models import Patient
    from sahyog.safety.deid import KnownIdentity, Scrubber

    patient = None
    if args.patient:
        with get_sessionmaker()() as session:
            row = session.get(Patient, args.patient)
            if row is None:
                sys.exit(f"no patient {args.patient}")
            patient = KnownIdentity.from_patient(row)
    result = Scrubber().scrub(args.text, patient=patient)
    print(f"scrubbed   {result.text}")
    print(f"found      {result.counts or 'nothing'}")
    # Local command only: the map is shown here for checking, never logged or sent anywhere
    for placeholder, original in result.mapping.items():
        print(f"  {placeholder:<12} = {original}")


def _llm_smoke(_: argparse.Namespace) -> None:
    import uuid

    from sahyog.llm.gateway import build_gateway
    from sahyog.llm.schemas import SpecialtyMatch

    settings = get_settings()
    if not settings.has_real_model:
        sys.exit("No real model is set up. Run `make set-key`, then rerun")
    result = build_gateway(settings).complete(
        "small",
        system="Pick the medical specialty id for the symptoms. SP12 is Orthopaedics, "
        "SP11 is Dermatology, SP01 is General Medicine. Reply only with the JSON asked for.",
        prompt="Knee pain while climbing stairs for three months.",
        schema=SpecialtyMatch,
        trace_id=uuid.uuid4().hex,
    )
    r = result.record
    print(result.output.model_dump())
    print(
        f"{r.provider}/{r.model}  in {r.input_tokens} out {r.output_tokens} tokens  "
        f"${r.cost_usd:.6f}  attempts {[a.outcome for a in r.attempts]}"
    )


def _chat(args: argparse.Namespace) -> None:
    import uuid

    import httpx

    settings = get_settings()
    api = httpx.Client(
        base_url="http://localhost:8000",
        headers={"Authorization": f"Bearer {issue_token(Role.PATIENT, args.patient)}"},
        timeout=120,
    )
    print(f"Patient {args.patient}, model provider: {settings.llm_provider}. Ctrl-D to stop.")
    if settings.llm_provider == "fake":
        print("FAKE MODEL: keyword replies. These prove the paths, not real accuracy.")
    try:
        reply = api.post(
            "/w1/triage",
            json={"text": input("\nWhat is wrong? > ")},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        while True:
            body = reply.json()
            if reply.status_code >= 400 and "status" not in body:
                sys.exit(f"HTTP {reply.status_code}: {body}")
            print(f"\n[{body['status']}]")
            if body.get("notice"):
                print(body["notice"])
            if body["status"] == "clarify":
                value = {"answer": input(f"{body['question']} > ")}
            elif body["status"] == "awaiting_choice":
                print(f"Specialty: {body['specialty']['name']}")
                for i, c in enumerate(body["candidates"], 1):
                    print(
                        f"  {i}. {c['doctor_name']}, {c['clinic']} ({c['city']})  "
                        f"{c['block_start']}  {c['places_left']} places left"
                    )
                number = int(input("Pick a number > "))
                value = {"slot_id": body["candidates"][number - 1]["slot_id"]}
            else:
                print(body.get("message", ""))
                for k in ("token_no", "block_start", "block_end", "ticket_id"):
                    if body.get(k):
                        print(f"  {k}: {body[k]}")
                return
            reply = api.post(
                f"/w1/{body['thread_id']}/resume",
                json=value,
                headers={"Idempotency-Key": uuid.uuid4().hex},
            )
    except EOFError:
        print()


def _desk(_: argparse.Namespace) -> None:
    import httpx

    rows = (
        httpx.get(
            "http://localhost:8000/desk/queue",
            headers={"Authorization": f"Bearer {issue_token(Role.DESK, 'DESK01')}"},
            timeout=30,
        )
        .raise_for_status()
        .json()
    )
    print(f"{len(rows)} open\n")
    for t in rows:
        minutes = t["age_seconds"] // 60
        print(
            f"P{t['priority']} {t['kind']:<17} {minutes:>5} min  owner {t['owner'] or '-':<8} "
            f"{t['patient_id'] or '-':<6} {t['ticket_id']}"
        )
        print(f"   {t['reason']}")


def _search(args: argparse.Namespace) -> None:
    from sahyog.auth import AuthContext, new_trace_id
    from sahyog.ingest.embedding import get_embedder
    from sahyog.records.search import retrieve_records

    ctx = AuthContext(args.patient, Role.PATIENT, "self_access", new_trace_id())
    hits = retrieve_records(ctx, args.patient, args.q, embedder=get_embedder(), k=args.k)
    print(f"{len(hits)} results for {args.patient}\n")
    for h in hits:
        mark = f"OCR {h.ocr_confidence:.0f}%" if h.source == "ocr" else "text"
        print(f"doc {h.doc_id}  page {h.page}  {mark}  score {h.score:.3f}")
        print("   " + h.text[:300].replace("\n", " | "))


def _ask(args: argparse.Namespace) -> None:
    import httpx

    role, actor = (Role.CAREGIVER, args.as_id) if args.as_id else (Role.PATIENT, args.patient)
    with httpx.stream(
        "POST",
        "http://localhost:8000/w2/ask",
        json={"question": args.q, "patient_id": args.patient},
        headers={"Authorization": f"Bearer {issue_token(role, actor)}"},
        timeout=120,
    ) as r:
        if r.status_code == 403:
            print("403: not permitted to read these records. No data returned.")
            return
        for line in r.iter_lines():
            if not line.startswith("data: ") or line == "data: {}":
                continue
            body = json.loads(line.removeprefix("data: "))
            print(f"[{body['status']}]\n{body['answer']}")
            for c in body["citations"]:
                print(f"  source: document {c['doc_id']}, page {c['page']} ({c['source']})")
            if body.get("ticket_id"):
                print(f"  desk ticket: {body['ticket_id']}")


def _dictate(args: argparse.Namespace) -> None:
    """Books an appointment if needed, opens an encounter, sends the dictation, prints the draft."""
    import time
    import uuid
    from pathlib import Path

    import httpx
    from sqlalchemy import select

    from sahyog.models import Appointment, Slot
    from sahyog.scheduling.service import reserve_slot

    doctor = "D0001"
    with get_sessionmaker().begin() as session:
        slot = session.execute(
            select(Slot).where(Slot.doctor_id == doctor).order_by(Slot.starts_at).limit(1)
        ).scalar()
        booked = session.execute(
            select(Appointment).where(Appointment.slot_id == slot.slot_id).limit(1)
        ).scalar()
        appt_id = (
            booked.appt_id
            if booked
            else reserve_slot(
                session,
                slot_id=slot.slot_id,
                patient_id="P0100",
                idem_key=f"demo-{uuid.uuid4().hex}",
                booked_by="demo",
            ).appt_id
        )
    api = httpx.Client(
        base_url="http://localhost:8000",
        headers={"Authorization": f"Bearer {issue_token(Role.DOCTOR, doctor)}"},
        timeout=120,
    )
    encounter = api.post("/w3/encounters", json={"appt_id": str(appt_id)}).json()["encounter_id"]
    if args.file:
        path = Path(args.file)
        with path.open("rb") as f:
            reply = api.post(f"/w3/encounters/{encounter}/audio", files={"file": (path.name, f)})
    else:
        reply = api.post(f"/w3/encounters/{encounter}/transcript", json={"transcript": args.text})
    thread = reply.raise_for_status().json()["thread_id"]
    for _ in range(240):
        draft = api.get(f"/w3/{thread}/draft").json()
        if draft["status"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    print(json.dumps(draft, indent=1, ensure_ascii=False))


def _ops(_: argparse.Namespace) -> None:
    from sahyog.observability import cost_per_consultation, tiles

    print(json.dumps({"tiles": tiles(), "cost": cost_per_consultation()}, indent=1))


def _stock_csv(args: argparse.Namespace) -> None:
    import csv
    from pathlib import Path

    from sqlalchemy import select

    from sahyog.models import MedicineStock

    fields = ["medicine_id", "clinic_id", "name", "composition", "qty", "as_of"]
    with get_sessionmaker()() as session, Path(get_settings().stock_csv).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        rows = session.execute(select(MedicineStock)).scalars()
        for row in rows:
            writer.writerow({k: getattr(row, k) for k in fields})
    print(f"wrote {get_settings().stock_csv}")


def _purge(args: argparse.Namespace) -> None:
    from sahyog.graphs.purge import purge

    print(purge(days=args.days))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sahyog")
    sub = parser.add_subparsers(required=True)

    p_seed = sub.add_parser("seed", help="Load deterministic synthetic data")
    p_seed.set_defaults(fn=_seed)

    p_token = sub.add_parser("token", help="Issue a local dev token")
    p_token.add_argument("--role", required=True, choices=[r.value for r in Role])
    p_token.add_argument("--id", required=True, help="Actor id, e.g. P0001, D0001, DESK01")
    p_token.set_defaults(fn=_token)

    p_flag = sub.add_parser("redflag", help="Run the red-flag gate on one message")
    p_flag.add_argument("--text", required=True)
    p_flag.add_argument("--age", type=int, default=None, help="Age from the patient profile")
    p_flag.set_defaults(fn=_redflag)

    p_scrub = sub.add_parser("scrub", help="Show what the egress scrubber sends out")
    p_scrub.add_argument("--text", required=True)
    p_scrub.add_argument("--patient", default=None, help="Patient id, e.g. P0001")
    p_scrub.set_defaults(fn=_scrub)

    p_smoke = sub.add_parser("llm-smoke", help="One real model call through the gateway")
    p_smoke.set_defaults(fn=_llm_smoke)

    p_search = sub.add_parser("search", help="Search one patient's records")
    p_search.add_argument("--patient", required=True)
    p_search.add_argument("--q", required=True)
    p_search.add_argument("--k", type=int, default=8)
    p_search.set_defaults(fn=_search)

    p_ask = sub.add_parser("ask", help="Ask about a patient's reports, over HTTP")
    p_ask.add_argument("--patient", required=True)
    p_ask.add_argument("--q", required=True)
    p_ask.add_argument("--as", dest="as_id", default=None, help="Caregiver id, e.g. CG0011")
    p_ask.set_defaults(fn=_ask)

    p_dictate = sub.add_parser("dictate", help="Run one dictation to its draft, over HTTP")
    p_dictate.add_argument("--text", default=None)
    p_dictate.add_argument("--file", default=None)
    p_dictate.set_defaults(fn=_dictate)

    p_ops = sub.add_parser("ops", help="Operations tiles and cost per consultation")
    p_ops.set_defaults(fn=_ops)

    p_stock = sub.add_parser("stock-csv", help="Export today's stock as the CSV the scribe reads")
    p_stock.set_defaults(fn=_stock_csv)

    p_purge = sub.add_parser("purge-threads", help="Delete W1 thread state past its expiry")
    p_purge.add_argument("--days", type=int, default=30)
    p_purge.set_defaults(fn=_purge)

    p_chat = sub.add_parser("chat", help="A whole W1 conversation in the terminal, over HTTP")
    p_chat.add_argument("--patient", required=True)
    p_chat.set_defaults(fn=_chat)

    p_desk = sub.add_parser("desk", help="Print the front-desk queue, over HTTP")
    p_desk.set_defaults(fn=_desk)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
