# Demo script

About 10 minutes. Open `http://localhost:8000/`. Everything uses synthetic data. Run `make seed` first for a clean queue.

## 1. Patient books (2 minutes)

Sign in as **Patient, P0011**, on **Find a doctor**.

1. Type `ghutne mein dard hai seedhi chadne par, 3 mahine se`. It suggests Orthopaedics and three doctors, as time blocks rather than exact minutes.
2. Pick one. You get a token and a message in Hinglish.

**Say:** it never quotes an exact minute, because nobody can predict consultation length.

## 2. An emergency (1 minute)

Type `my father suddenly cannot speak and his face is drooping`.

**Say:** fixed rules caught this before any model saw it. No doctors are offered, and the desk has a ticket.

## 3. Unsure (1 minute)

Type `I feel weak`. It asks one question. Answer `still not good`, and it hands off to the desk.

## 4. Reports (2 minutes)

First, in a terminal:

```bash
make upload file=evals/w2/generated/scan-lab-0.pdf patient=P0011
```

On **My reports**, ask `what was my fasting blood sugar`. Each sentence names its page, and a warning appears because the page was scanned.

Ask `Do I have diabetes?`. It's refused and passed to a person.

**Say:** the patient filter is in the database query, so no question or poisoned report can widen it.

## 5. Family consent (1 minute)

Sign in as **Family caregiver, CG0011**, patient `P0011`, and ask the same question: it answers. Sign in as **CG0041**, patient `P0041`: refused, because that consent expired.

## 6. Doctor's note (2 minutes)

Sign in as **Doctor**, with the id of the doctor P0011 booked. Find it with:

```bash
make psql
```

```sql
select s.doctor_id from appointment a join slot s using (slot_id) where a.patient_id = 'P0011';
```

Pick the patient, then type:

`Patient: My sugars have been high. Doctor: Fasting sugar 180 today. Type 2 diabetes, poorly controlled. Continue metformin 500 mg twice daily and start a low dose statin. Review in three months.`

1. The review opens with what was heard. Each line shows the words it came from, and metformin shows its stock.
2. The statin is a **gap**: the doctor said a class, not a drug. Try **Sign note**, and it's refused.
3. Type `Atorvastatin`, `10 mg`, and sign. The note is saved, with a hash, and can't change.

**Say:** the model never fills a molecule the doctor didn't say, and that's enforced in code.

## 7. Front desk (1 minute)

Sign in as **Front desk, DESK01**. Red flags are first, then oldest first, each with its reason, owner and how long it has waited. Cancel the assistant's booking with a reason, and the action is audited.

## What not to claim

Don't say it's safe for patients or accurate on real reports. See `docs/FINAL-REPORT.md`.
