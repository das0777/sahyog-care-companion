# D3 · Assumptions register

Each row has an owner (a role), how it's validated, a fallback, and **what the build found**. Owners are roles at Sahyog. None has been confirmed by a real person, because D2 is still unanswered.

| # | Assumption | Owner | How it's validated | Fallback if it fails | What the build found |
|---|---|---|---|---|---|
| A1 | One slot maps to exactly one appointment | Head of front desk | Ask whether overbooking is practised | Model capacity per block | **Failed by design:** consultation length is unpredictable, so the build uses blocks with capacity and token numbers |
| A2 | Patients type symptoms in English, Hinglish or Hindi | Patient experience lead | Synthetic intakes in each style through matching | A language-detection node | Built with detection. Marathi isn't supported (S1 review) |
| A3 | A doctor reviews the draft during the consultation | Chief medical officer | Role-play five consultations | Queue drafts for end-of-session review | Not validated with a doctor. The draft waits at an interrupt either way |
| A4 | The nightly stock CSV is complete before clinics open | Pharmacy lead | File timestamps across a week | Show stock age; mark unknown when stale | Only a synthetic CSV was used. Not validated |
| A5 | De-identified text is enough for a good SOAP draft | Chief medical officer | Compare drafts with and without identifiers on 30 transcripts | Identified drafting in-region | The MVP drafted on scrubbed text, but quality wasn't compared |
| A6 | The HIS FHIR API answers a demographics read within 300 ms | IT integration lead | Time 50 calls | Cache per session | Not built (FHIR is optional). Demographics come from seeded tables |
| A7 | Speech to text is accurate enough for grounding | Chief medical officer | Real dictations with known content | Doctor reads the transcript first | **Failed in the MVP:** "Known diabetic" was heard as "NON diabetic". Grounding can't catch it, so the transcript is shown first. Gating signing is still open |
| A8 | About 1 in 200 scan-read numbers is wrong | Records lead | Real anonymised scans | A scan warning on every OCR value | Measured on synthetic scans only. The warning is built |
| A9 | Fixed rules catch emergencies; a model pass catches the rest | Chief medical officer | Phrasings written by someone independent (C3) | Send everything unclear to the desk | **Not validated:** C3 has never run. Rules alone caught 7/15 on the MVP's probe 3 |
| A10 | Only scrubbed text needs to leave the hospital | Privacy officer | Replay outbound payloads through a detector | An in-region model for all clinical text | The patient's own identifiers: 0 in the replay. Other people's names in free text can leak |
| A11 | Patient names may be printed with titles or initials | Records lead | Sample real report headers | Hold the report for the desk | Found in S3's review. Titles and initials are handled, and a surname alone holds the report |
| A12 | A model provider outside India may receive scrubbed text | Privacy officer | Contract and privacy review | An India-hosted model | Assumed for OpenRouter. The privacy review is pending |
