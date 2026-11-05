# Unseen rewordings for S4's word checks

Written by the independent AI reviewer of pull request #18, **before reading** `sahyog/safety/wording.py` or its tests: 25 questions that should go to a person, 10 read-back questions that should be answered, 25 answers that should be blocked and 10 plain read-back answers that should pass, in English, Hinglish and Hindi. Nothing here was used to tune the checks.

```bash
python evals/w2/unseen/measure.py evals/w2/unseen/novel.jsonl
```

Claude wrote this set too, so it's unseen but not independent. A set written by a person would be the stronger test.
