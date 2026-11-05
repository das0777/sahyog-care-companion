# Sahyog Care Companion · Executive memo

**To:** Sahyog's board · **From:** the delivery pod · **Date:** 5 November 2026

## The result

Sahyog has a working, reviewed assistant for all three of the board's mandates, ready for a supervised pilot, **not yet for patients.** Patients book by describing symptoms in English, Hinglish or Hindi, after an emergency check. They ask questions about their own reports and get answers that name the page. Doctors sign a draft note made from their dictation. On synthetic data, the first build measured no patient's data in another patient's answer (0 in 26 attack attempts), no invented medicine in a draft note (0 in 37), triage in about 4 seconds, and about **$0.017 of model cost per consultation**. What the board cares about most (calls avoided, time to book, and the doctor's time back) needs a pilot with real people to measure.

## The problem

There are 9,000 appointments a day across Pune and Hyderabad. 41% are booked by phone, 18% of patients don't arrive, 2.4 million report PDFs are scanned a year, and doctors spend 11 minutes per consultation typing.

## What we decided, and why

- **Code decides; the model only guesses.** Emergency rules run before any AI, and the patient filter is a database query. A prompt can be argued with, but a SQL filter can't.
- **A doctor signs every note.** A medicine, dose or "do not" the doctor didn't say becomes a question for the doctor, never an assumption.
- **Only scrubbed text leaves the hospital.** Names and IDs are removed before any outside model call, and reports are read on site.
- **Time blocks, not exact minutes.** A long visit is absorbed by its block, not passed on to every later patient.
- **Independent review of every change.** After a fast first build, we rebuilt it one stage at a time. Each stage was checked by an AI reviewer that hadn't written the code, and every finding was logged.

## What review found

The reviews caught defects the first build's own tests had passed: a front-desk double booking, a relative's report filed under the wrong patient, emergency wordings missed in Hindi, and unsaid doses reaching a doctor's note. All were fixed with tests. **The lesson:** an AI agent's tests check what it already thought of, so it needs a reviewer that didn't write the code.

## What's not ready

There's been no independent emergency-recall test, no calibrated answer judge and no clinician review yet. Live-model results are from the first build. The word checks behind the refusal of diagnosis questions catch about one in four new phrasings. There are no backups and no real load test.

## What we'd do differently

Protect the main branch so nothing merges before review passes: six of twelve changes merged early. Have people, not the build agent, write the held-out safety tests. Run with a model key from day one, so every number is this build's own.

## The ask

A four-week supervised pilot in one clinic, with front-desk staff watching every booking and doctors signing every note. Before it starts: a clinician's review of the rules and wording, emergency test phrases written by someone independent, and a privacy review of the model provider.
