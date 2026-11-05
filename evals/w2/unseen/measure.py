"""Run S4's word checks on an unseen set and report caught / false-block rates.

Usage (inside the app container): python /novel/measure.py /novel/novel.jsonl
Questions go to asks_for_advice_on_records (True = sent to a person).
Answers go to clinical_answer (True = blocked).
"""
import json
import sys
from collections import defaultdict

from sahyog.safety.wording import asks_for_advice_on_records, clinical_answer

path = sys.argv[1] if len(sys.argv) > 1 else "/novel/novel.jsonl"
rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]

stats = defaultdict(lambda: [0, 0])  # (kind, expect, lang) -> [flagged, total]
misses = []
for r in rows:
    fn = asks_for_advice_on_records if r["kind"] == "question" else clinical_answer
    flagged = bool(fn(r["text"]))
    for lang in (r["lang"], "all"):
        s = stats[(r["kind"], r["expect"], lang)]
        s[0] += flagged
        s[1] += 1
    should_flag = r["expect"] in ("refuse", "block")
    if flagged != should_flag:
        misses.append((r["kind"], r["expect"], r["lang"], r["text"]))

label = {
    ("question", "refuse"): "questions caught (sent to a person)",
    ("question", "allow"): "read-back questions falsely refused",
    ("answer", "block"): "clinical answers caught (blocked)",
    ("answer", "pass"): "read-back answers falsely blocked",
}
print(f"{'measure':40} {'en':>7} {'hinglish':>9} {'hi':>7} {'all':>9}")
for (kind, expect), name in label.items():
    cells = []
    for lang in ("en", "hinglish", "hi", "all"):
        f, t = stats[(kind, expect, lang)]
        cells.append(f"{f}/{t}" if t else "-")
    f, t = stats[(kind, expect, "all")]
    print(f"{name:40} {cells[0]:>7} {cells[1]:>9} {cells[2]:>7} {cells[3]:>5} ({100*f/t:.0f}%)")
print("\nWrong calls:")
for m in misses:
    print("  ", m)
