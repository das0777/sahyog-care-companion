# S5 · Test pack

| | |
|---|---|
| **Stage** | S5 W3 Consultation scribe |
| **Branch** | `stage/s5-w3` |
| **Status** | Built without a per-stage verdict, at the user's request. Reviewed with the final combined test pack |

## Findings that matter

1. **Speech to text can flip the meaning.** On a synthetic voice, "Known diabetic" came back as "**NON** diabetic", "poorly controlled" as "POLYCANTRAL", and "metformin" as "MET FORM IN". Hindi was poor: key words heard 1/3. Overall 9/14 key words. Grounding can't catch this, because it checks against the transcript and the transcript is what's wrong. **The doctor must read the transcript.** The screen shows it, but nothing forces it. Real voices and accents are untested.
2. **Medicine precision missed its gate on the one measured run:** 93%. "Oral steroids" wasn't recognised as a class because of the plural, so it came through as a medicine, and a gap was lost (G4 4/5). Fixed in code with a test. The run isn't repeated, so **the recorded numbers stay as they are.** The same case passes in the test now, though no live re-measure was made.
3. **The test cases are Claude's**, and short clean dictations. No real consultations.

## Claude's results

Live runs used OpenRouter with frozen prompts `11b9bc24510d0221`, recorded in `evals/w3/measurements.jsonl`.

| # | Check | Target | Result |
|---|---|---|---|
| G1 | Draft after transcript, p95 | < 20 s (gate) | **Pass**: 7.0 s over 24 runs, one at a time |
| G2 | Drafts valid, A and P grounded | 100% (gate) | **Pass**: 15/15 |
| G3 | Invented molecules | 0 (gate) | **Pass**: 0 |
| G4 | Class without molecule stays a gap | 100% (gate) | **Fail on the measured run**: 4/5. Fixed after |
| G5 | SOAP terms in the right field | ≥ 85% (gate) | **Pass**: 70/79, 89%. A term check, not a true F1 as the doc's title said: it measures recall of expected words |
| G6 | Medicine precision | 100% (gate) | **Fail on the measured run**: 93%. Fixed after. Recall 100% |
| G7 | Nothing stored before signing | 0 (gate) | **Pass** |
| G8 | Reject redrafts; sign refuses gaps | Tests | **Pass** |
| G9 | Every medicine has a stock line and age | 100% (gate) | **Pass**: 15/15 |
| G10 | Editing a signed note | 423, and the database refuses | **Pass** |
| G11 | Audio deleted within 24 h, audited | Test | **Pass**, with a stubbed object store and a backdated row. The sweep hasn't run a real day |
| G12 | Identifiers reaching the model | 0 (gate) | **Pass** on scripted replies |
| G13 | Speech to text | Reported | 9/14 key words: see above |
| G14 | Only the owning doctor can act; audited | Tests | **Pass** |
| G15 | Evals fail without guardrails | Fails | **Pass** |

The grounding code raised no flags in the live run: the model invented nothing there. So the checks are proven only with a scripted model that invents drugs, not by catching a real model doing so.

## Known limitations

- **No speaker separation.** In unlabelled audio, a patient's words count as the doctor's, so "I take aspirin" could become a medicine.
- A topical or as-needed medicine with no dose counts as a gap. The doctor must type something to sign.
- Stock matches molecule and strength, and only finds what's in the CSV. Brand names such as Crocin come back `unknown`.
- A plan's drug check uses a finite list of about 45 molecules. The span check is the main defence.
- The outside model sees scrubbed text. The spec's in-region option isn't installed.
- A stock reservation is recorded but never reduces the CSV's quantity.
- Note amendment isn't built: a signed note can't change, and no new version can be made yet.
- The worker holds about 500 MB more for the speech model.
