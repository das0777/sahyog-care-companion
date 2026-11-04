# S3 · Test pack

| | |
|---|---|
| **Stage** | S3 W2 Ingest |
| **Branch** | `stage/s3-w2-ingest` |
| **Handed over** | 2026-10-30 |
| **Claude's result** | All gated checks pass; 255 tests and lint green. No outside model is called. **Read "How far to trust these numbers" first.** |

## How far to trust these numbers

**The main finding: about 1 number in 200 on a clean scan comes out wrong, and it can look entirely plausible.**

| Run on clean scans | Right | What went wrong |
|---|---|---|
| First run | 185/192: **failed the gate** | 1 wrong number (15.5 read as 15:5), 6 wrong units (`mIU/L` read as `mlU/L`) |
| After fixing both, fresh seed 7101 | 191/192 | **Creatinine 1.72 read as 172**, a dropped decimal |
| After fixing both, fresh seed 7102 | 191/192 | TSH 7.11 read as `TA` |
| Default seed, after fixing | 192/192 | Don't count this one: it's the run the fixes were made from |

The fresh seeds are the honest number. They pass the 98% gate, but a gate can't make the failure harmless: **a dropped decimal has no obvious sign that it's wrong.** S3 can't detect it, so it marks every scan-read chunk. S4 must tell the patient when a value came from a scan and point them to the original page.

**These are easy scans.** They're computer-printed reports turned into images, with clean fonts, a little skew or blur at most. No phone photos, shadows, creases, stamps, handwriting or real lab layouts. **Expect real reports to do worse by an unknown amount.** The only way to know is a few anonymised real scans from Sahyog. Claude also wrote both the sample reports and the code reading them. Your own PDF in step 3 is a small independent check.

**Prompt-injection filtering is weak against rewording.** All 15 planted instructions were caught, but only 2 of 4 reworded ones, even though Claude had seen them. Treat this as a first filter. S4's patient filter and citation check are the real defence, and S4 has to prove that.

## Claude's results

From a clean `make reset`, `make up` and `make seed`.

| # | Check | Target | Result |
|---|---|---|---|
| D1 | Text PDF stored and searchable | p95 < 60 s (gate) | **Pass**: 2.5 s |
| D2 | Scanned PDF, 5 pages | p95 < 60 s (gate) | **Pass**: 7–10 s across runs. About 3 s for one upload on the idle real worker |
| D3 | Values read from text PDFs | 100% (gate) | **Pass**: 176/176 |
| D4 | Values read from clean scans, exact digits and unit | ≥ 98% (gate) | **Pass**: 191/192 on each fresh seed. Failed its first run (above) |
| D4h | Values from Hindi scans | Reported | 8/8. Numbers beside Hindi labels only: Hindi sentences weren't tested |
| D5 | Degraded scans | Reported | Skew 20/20, blur 20/20 on fresh seeds. Low resolution about 19/20: Uric Acid 4.4 read as 44, or a unit lost |
| D6 | Medicine names from scans | ≥ 95% (gate) | **Pass**: 8/8, a small sample |
| D7 | Value on its right page | 100% (gate) | **Pass**: 324/324 |
| D8 | OCR chunks marked as OCR | 100% (gate) | **Pass**: 138/138 |
| D9 | Search finds the right chunk | ≥ 90% in top 8 (gate) | **Pass**: 38–39/40. Top 1: 32–34/40. Misses: "liver enzyme", and sometimes "three month sugar average" |
| D10 | Results from another patient | 0 (gate) | **Pass**: 0 in 90 searches |
| D11 | Bad files | All refused or failed, with a reason | **Pass**: 7/7 |
| D12 | Planted instructions kept out of search | All | **Pass**: 15/15. Reworded: 2/4 |
| D13 | Normal chunks wrongly quarantined | ≤ 2% | **Pass**: 0/116, on synthetic wording only |
| D14 | Wrong-patient reports held | All, and no correct one held | **Pass** |
| D15 | Worker killed mid-job | Finishes, no duplicates | **Pass**: real kill during a 40-page scan. Retried after 186 s, 40 chunks, no duplicates |
| D16 | Re-upload | No re-embedding, one document | **Pass** |
| D17 | Someone else's job | Same reply as a missing one, audited | **Pass** |
| D18 | Nothing leaves the boundary | 0 outside calls | **Pass**: ingest and search code can't import the gateway. Checked in the code, not by watching network traffic |
| D19 | Evals fail without guardrails | D10 and D12 fail | **Pass**: 396 leaks and 0/15, exit code 1 |
| D20 | Your own PDF | Right status, searchable | **Your check**: step 3 |
| D21 | Nothing earlier broke | Green | **Pass**: 255 tests, lint clean, `/health` all ok |

### Found and fixed during the build

1. **A worker crash.** The PDF library isn't thread-safe, and two workers using it at once took down the whole process, on the first eval run. Reads now take turns.
2. **OCR confusions**, as above. Fixed only where context is unambiguous: "15:5 g/dL" becomes 15.5, but "10:30 am" stays.
3. **False injection alarms.** Normal wording ("ignore mild symptoms… diet instructions") was flagged. A test caught it, and the pattern is now tighter.
4. **My first two kill tests proved nothing.** In one, the job finished before the kill. In the next, the wrong-patient check held the report, so no chunks existed to duplicate. The third is the one reported.
5. **Search test made harder.** With few chunks per patient, "top 8" passes by default, so one sample patient has 60 pages. The check still has generous odds, so top 1 is shown too.

## Your test script

Run from `~/Desktop/sahyog-care-companion`. The stack is running. **No model is called here, and nothing costs money.**

**1. Evals, about 1.5 minutes**

```bash
make eval
```

Expect a table ending in `ALL GATES PASS`.

**2. Upload a sample report and find it**

```bash
make upload file=evals/w2/generated/scan-lab-0.pdf patient=P0011
```

Expect a `job_id`. Copy it into this command in place of `JOB`. Within seconds, expect `"status":"indexed"`, with 5 pages read by OCR:

```bash
make doc-status job=JOB patient=P0011
```

Then search, which takes a few seconds as it loads the model. Expect results marked `OCR`, with the value on its page:

```bash
make search patient=P0011 q="HbA1c"
```

Now the same search as a different patient. Expect `0 results`:

```bash
make search patient=P0012 q="HbA1c"
```

**3. Your own PDF (D20)**

Use any PDF that holds no real patient's data, such as a made-up report or a letter you typed. Change the path:

```bash
make upload file=/path/to/your.pdf patient=P0001
```

Check it with `make doc-status`, then `make search` for a word in it. If it prints a name other than P0001's, or a different ABHA, expect `held`, which is correct. A scanned or photographed page is especially useful. Tell Claude if a value came out wrong.

**4. The checks that protect the patient**

A report belonging to someone else: expect `held`, with a reason.

```bash
make upload file=evals/w2/generated/identity-wrong-both.pdf patient=P0007
```

A planted instruction: expect `indexed` with `"chunks_quarantined":1`, and a ticket on the desk.

```bash
make upload file=evals/w2/generated/redteam-0-visible.pdf patient=P0002
```

```bash
make desk
```

A damaged file: expect a plain refusal straight away.

```bash
make upload file=evals/w2/generated/bad-corrupted.pdf patient=P0001
```

**5. Tests and lint**

```bash
make test
```

```bash
make lint
```

Expect `255 passed`, then `All checks passed!`.

## Known limitations

- **Wrong numbers on scans are not detected**, only marked as scan-read (above). S4 has to show this to the patient.
- Real scans are untested. Handwriting isn't supported.
- **Worker failures are slow and quiet.** A killed job waits out a 3-minute lease, so it misses the 60-second target, and `/health` doesn't include the worker. The status simply stays `queued`.
- **Hidden text is indexed unless it reads as an instruction.** White or tiny text a patient can't see can still reach answers in S4.
- The wrong-patient check relies on a labelled name or an ABHA. A different report layout could get past it. It also can't catch a report that names nobody.
- Chunks store identifiers, as designed. The gateway scrubs them when they go to a model in S4, and S2's limitation on names outside the list applies there too.
- No virus scanning, and no way yet to delete a patient's documents on request.
- `make seed` deletes uploaded documents' database rows but leaves their files in MinIO. Fine locally.
- Each process that searches holds about 2–3 GB of memory (estimated, not measured), and `make reset` deletes the 2.1 GB model. S3 added about 2.6 GB of disk: 2.1 GB for the model, and the image grew from about 890 MB to 1.35 GB.
- Timing comes from one upload at a time or two workers on this Mac, not a load test (S7).

## Your verdict

Reply **"S3 accepted"**, or list what failed by step number. Please mention any value that came out wrong from your own PDF.
