"""`make load`: the morning peak of 1,400 requests an hour, on the real stack and the real model.

Arrivals are random at the target rate and don't wait for earlier requests, as real traffic doesn't.
This measures this Mac with one API process, which says how the code behaves under this load, not
what production capacity is. Costs money: about $0.01 a request.
"""

import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid

import httpx

from sahyog.auth import Role, issue_token
from sahyog.observability import tiles

BASE = "http://localhost:8000"
TRIAGE = [
    "knee pain while climbing stairs",
    "itchy rash on my arm for a week",
    "pet mein jalan khane ke baad",
    "toothache for three days",
    "ear pain and reduced hearing",
    "दांत में दर्द है",
    "cough for two weeks",
    "feeling low and not sleeping well",
]
ASK = ["what was my fasting blood sugar", "my hba1c", "vitamin b12 kitna hai", "what is my tsh"]
SEEDED_DOC = ("evals/w2/generated/scan-lab-0.pdf", "P0011")
results: list[tuple[str, int, float]] = []


def headers(role: Role, who: str, *, idem: bool = False) -> dict:
    out = {"Authorization": f"Bearer {issue_token(role, who)}"}
    if idem:
        out["Idempotency-Key"] = uuid.uuid4().hex
    return out


async def timed(name: str, call) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        r = await call
        results.append((name, r.status_code, time.perf_counter() - started))
        return r
    except httpx.HTTPError:
        results.append((name, 0, time.perf_counter() - started))
        return None


async def triage(client, rng) -> None:
    who = f"P{rng.randint(100, 900):04d}"
    r = await timed(
        "triage",
        client.post(
            "/w1/triage",
            json={"text": rng.choice(TRIAGE)},
            headers=headers(Role.PATIENT, who, idem=True),
        ),
    )
    if r is None or r.status_code != 200:
        return
    body = r.json()
    if body.get("status") == "awaiting_choice" and rng.random() < 0.5:
        await timed(
            "book",
            client.post(
                f"/w1/{body['thread_id']}/resume",
                json={"slot_id": body["candidates"][0]["slot_id"]},
                headers=headers(Role.PATIENT, who, idem=True),
            ),
        )


async def ask(client, rng) -> None:
    await timed(
        "ask",
        client.post(
            "/w2/ask",
            json={"question": rng.choice(ASK), "patient_id": SEEDED_DOC[1]},
            headers=headers(Role.PATIENT, SEEDED_DOC[1]),
        ),
    )


async def desk(client, _) -> None:
    await timed("desk", client.get("/desk/queue", headers=headers(Role.DESK, "DESK01")))


async def run(minutes: float, rate: float) -> None:
    rng = random.Random(1400)
    gap = 3600 / rate
    deadline = time.monotonic() + minutes * 60
    tasks = []
    async with httpx.AsyncClient(base_url=BASE, timeout=90) as client:
        while time.monotonic() < deadline:
            roll = rng.random()
            job = triage if roll < 0.6 else ask if roll < 0.9 else desk
            tasks.append(asyncio.create_task(job(client, rng)))
            await asyncio.sleep(rng.expovariate(1 / gap))
        await asyncio.gather(*tasks)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--rate", type=float, default=1400)
    args = parser.parse_args(argv)
    before = tiles(hours=1)["cost_usd"]
    asyncio.run(run(args.minutes, args.rate))
    print(f"\n{len(results)} requests in {args.minutes} min, target {args.rate}/h\n")
    targets = {"triage": 4.0, "ask": 8.0, "book": 4.0, "desk": 4.0}
    ok = True
    for name, target in targets.items():
        rows = [r for r in results if r[0] == name]
        if len(rows) < 2:
            continue
        times = [r[2] for r in rows]
        p95 = statistics.quantiles(times, n=20)[-1]
        bad = sum(r[1] not in (200,) for r in rows)
        passed = p95 < target
        ok = ok and passed
        print(
            f"{name:<7} n={len(rows):<4} median {statistics.median(times):5.2f} s  "
            f"p95 {p95:5.2f} s  "
            f"target < {target:.0f} s  {'PASS' if passed else 'FAIL'}  non-200: {bad}"
        )
    codes: dict[int, int] = {}
    for _, code, _ in results:
        codes[code] = codes.get(code, 0) + 1
    print(f"\nStatus codes: {codes}")
    print(f"Model cost of this run: about ${tiles(hours=1)['cost_usd'] - before:.3f}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
