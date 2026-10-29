# S1 · Test pack

| | |
|---|---|
| **Stage** | S1 Safety core and eval harness |
| **Branch** | `stage/s1-safety` |
| **Handed over** | 2026-10-30 |
| **Claude's result** | All gated checks pass; 161 tests and lint green. **Read "The finding that matters" first.** |

## The finding that matters

The red-flag gate catches 100% of the golden cases, but **that number is not evidence of real-world recall**. Claude wrote both the cases and the rules. To test that honestly, Claude wrote two sets of 15 emergency phrasings the rules had never seen, committed each before changing any rule, and measured them:

| Set | When measured | Caught |
|---|---|---|
| Golden (13 red flags) | Rules v.1 | 13/13 |
| Blind probe 1 | Rules v.1, first run | **8/15** |
| Blind probe 2 (held out until measured) | Rules v.2, after probe 1's misses were fixed | **5/15 (33%)** |

So a phrase-list gate generalises poorly to how people actually describe emergencies: kerosene, a snake bite, grey lips, a purple rash that doesn't fade, "ending it all". The misses from both probes are now fixed with general rules (v.3), and both sets are regression cases. **But the next unseen phrasing will be missed at a similar rate.**

Honesty note on the method: while fixing probe 1, Claude first added phrases that echoed probe 2's wording. Claude caught this before measuring probe 2, removed every addition probe 1 didn't call for, and only then ran probe 2. The 5/15 is from that clean run.

What this means for the design:

- The rule gate is a **floor**, not the net. It stays first because it is instant, explainable and never cancelled by a model.
- S2 must add the model second pass (it can only add flags) and measure the combined gate on a **fresh held-out set written by someone other than Claude**. Your own phrasings in step 3 below are the first such set.
- Before any real use, a clinician should write or review the red-flag phrasings, not just the rules.

## Claude's results

From a clean `make reset`, `make up`, `make seed`, then `make eval`, `make test` and `make lint`.

| # | Check | Target | Result |
|---|---|---|---|
| B1 | Red-flag recall, golden | 100% (gate) | **Pass**: 13/13 |
| B1r | Red-flag recall, both blind probes (now regression) | 100% (gate) | **Pass**: 30/30 after fixes. Before fixes: 8/15 and 5/15 (above) |
| B2 | Red flags you type yourself | Every one | **Your check**: step 3 |
| B3 | False alarms on golden non-emergencies | ≤ 20%, reported | 1/17 (6%): w1-017 "no chest pain, just a cough", by design |
| B4 | Language detection | ≥ 90% (gate) | **Pass**: 30/30 |
| B5 | Identifiers leaving the boundary, 200 payloads | 0 (gate) | **Pass**: 0 |
| B5b | Third-party names not in any name list | reported | 26/26 caught |
| B6 | Clinical content kept after scrubbing | ≥ 95% (gate) | **Pass**: 350/350 |
| B7 | Malformed model output | 100% rejected, 0 repaired (gate) | **Pass**: 12/12 rejected |
| B8 | Model cannot remove a flag | Flag stays | **Pass**: `test_model_can_add_a_flag_but_never_remove_one` |
| B9 | Fallback | Timeout → retry → fallback, same trace id | **Pass**: `test_timeout_is_retried_once_then_the_fallback_answers_with_the_same_trace` |
| B10 | No vendor SDK outside the gateway | 0 imports | **Pass**: AST test plus ruff rule `TID251` |
| B11 | Evals fail without the guardrails | B1 and B5 fail | **Pass**: B1 0/13, B1r 0/30, B5 875 leaks, exit code 1 |
| B12 | Red-flag check speed | p95 < 50 ms | **Pass**: about 10 ms |
| B13 | Nothing earlier broke | S0 checks green | **Pass**: 161 tests (35 from S0), lint clean, `/health` all ok |

### Other things found and fixed during the build

1. **Typo matching misfired on everyday Hinglish.** "karna chahta" (I want to do) matched the self-harm phrase "marna chahta". Phrases one letter away from everyday words are now exact-only (marked `=` in the rules).
2. **spaCy read Hinglish and doses as names.** "mera naam", "kumar hai" and "mcg le" were tagged as people. Hindi function words and units are now trimmed off detected names.
3. **North-East and South Indian names leaked.** Names such as "Phurba Lepcha" and "Thangam Muthiah" got past both spaCy and the Indian name list: 7 leaks on the first full replay. Two structural rules fixed this: capitalised words after a relationship word, and capitalised pairs mid-sentence. The replay now also has wordings with no relationship word, so the fix isn't matched to the templates.
4. **A name rule swallowed "HbA1c".** After "Dr.", the rule ran past the full stop. Names now stop at a sentence end.
5. **The replay's hardest case wasn't running.** A bug meant no out-of-list names were planted (0/0). Fixed before the numbers above.
6. **Lint config in the container was stale.** `pyproject.toml` was baked into the image. It is now mounted.

## Your test script

Run from `~/Desktop/sahyog-care-companion`. The stack is already running; if not, run `make up` and then `make seed` first.

**1. The eval report (B1–B7, B12)**

```bash
make eval
```

Expect a table ending in `ALL GATES PASS`, with B1 13/13, B1r 30/30, B5 0 and B7 12/12. The report is written to `evals/reports/s1-2026-10-30.md`.

**2. The evals catch missing guardrails (B11)**

```bash
make eval GUARDRAILS=off
```

Expect `GATE FAILURE`, with B1 0/13 and B5 in the hundreds, and make exits with an error.

**3. Your own red flags (B2): the real test**

Change these freely, and add your own in English, Hinglish or Hindi, the way a worried patient or relative would type:

```bash
make redflag text="mere papa ko seene mein bahut dard hai aur pasina aa raha hai"
```

```bash
make redflag text="my wife fainted and now she is not talking properly"
```

```bash
make redflag text="ache in left arm and breathless" age=62
```

Expect `RED FLAG -> emergency desk`, with the rule and the words it matched. Please note every miss: each one becomes a regression case, and the misses together are the honest recall number for S2.

Also try something harmless, which should give `no red flag`:

```bash
make redflag text="knee pain while climbing stairs"
```

**4. What leaves the boundary (B5, B6)**

```bash
make scrub text="Urvashi Kulkarni, DOB 1942-12-19, phone 55225 79937, ABHA 31-2545-1234-5678. HbA1c 7.2% on 12/03/2026. Her son Rohit Patil will come." patient=P0001
```

Expect the names and phone as placeholders, the date of birth as `80–89 years`, and `HbA1c 7.2% on 12/03/2026` unchanged. P0001's real ABHA is a different number, so this ABHA is caught by its pattern. The placeholder list printed under the result is shown only by this local command; the gateway never logs or sends it.

**5. Tests, lint, and S0 still working (B8–B10, B13)**

```bash
make test
```

```bash
make lint
```

```bash
curl -s localhost:8000/health
```

Expect `161 passed`, then `All checks passed!`, then all four services `ok`.

**6. Optional: one real model call**

Only if you want to: put `LLM_PROVIDER=anthropic` and your key in `.env` yourself, then:

```bash
docker compose up -d --wait api
```

```bash
make llm-smoke
```

Expect a specialty JSON such as `SP12`, the model used, its token counts and cost, and `attempts ['ok']`. This sends one sentence with no personal data. S1 is complete without this step.

## Known limitations

- **Red-flag recall on unseen phrasing is low** (above). This is the main open risk, carried into S2.
- Negation never cancels a flag, by design, so "no chest pain" goes to the emergency desk.
- A lone first name at the start of a sentence, with no surname, no cue word and not in the name list, can get through ("Meena came in…"). The patient's own name is always removed, because it comes from their record.
- Devanagari names of third parties are not detected. The patient's own name is.
- Proper nouns written as capitalised pairs (for example "Sahyog Kothrud") are sometimes removed. That is safe, but it loses location detail.
- The replay draws some third-party names from the same pool as the Indian name list, which flatters B5. B5b (names outside any list) is the stricter number.
- The Anthropic and Ollama adapters are tested against stubbed HTTP only. A real call happens only through the optional step 6. Ollama itself is not installed.
- The API image grew to about 890 MB with spaCy and Presidio. That is fine locally; a slimmer production image is an S7 task.
- The rules are not clinically reviewed (`reviewed_by: null`).

## Your verdict

Reply **"S1 accepted"**, or list what failed by step number, including any red flag from step 3 that was missed.
