# D2 · Discovery questions

Ten questions, each tied to the decision its answer unlocks. At most three are taken from the pack's page 9 (marked †).

**Status: drafted, not posted.** The pack accepts D2 when the questions are posted in the client thread and the faculty answer in role within one working day. That hasn't happened. The build went ahead on the pack's RFP addendum (page 5) and on assumptions in `docs/assumptions.md`. **To do:** the owner posts these questions, and each answer goes into the assumptions register.

| # | Question | Unlocks | Answer |
|---|---|---|---|
| 1 † | What must happen when a patient reports chest pain at night? | The red-flag list and the out-of-hours escalation path | Pending |
| 2 † | What would make the CMO switch this off in week one? | The first guardrail and the pilot's stop rule | Pending |
| 3 † | What is the budget per consultation for AI services? | Model routing; whether $0.017 a consultation (MVP) fits | Pending |
| 4 | Do clinics overbook today, and how many patients fit in an hour at each OPD? | Block capacity per doctor (the build assumes blocks with tokens) | Pending |
| 5 | Which emergency phrasings does the front desk hear most, in which languages? | An independent red-flag test set (C3 has never run) | Pending |
| 6 | Do lab reports print the patient's name with a title, initials or a relative's name ("W/o", "S/o")? | The wrong-patient check's rules | Pending |
| 7 | Is the patient's name held in Devanagari as well as Latin in the HIS? | Whether `name_local` comes from the HIS or must be captured | Pending |
| 8 | Who in the clinic answers a held or quarantined report, and how fast? | The desk queue's owners and SLA | Pending |
| 9 | Must a doctor confirm they read the transcript before signing? | Whether the review screen gates signing (an open risk from S5 and S6) | Pending |
| 10 | Which model providers has the privacy office approved for de-identified text, and on what terms? | OpenRouter versus an India-hosted model (ADR 0005) | Pending |
