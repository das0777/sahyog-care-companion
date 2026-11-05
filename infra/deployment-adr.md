# D6 · Deployment decision

**Status:** proposed for the steering review. Nothing is deployed. It builds on `docs/adr/0005-hybrid-deployment.md`.

**Gate 2 answers aren't available:** the D2 questions haven't been posted. This rescoring uses the pack's RFP addendum (page 5), which says only de-identified text may leave, audio is deleted within 24 hours, and the peak is 9,000 a day and 1,400 an hour, plus what the build showed.

## The matrix, rescored

| Criterion | On-premise | Private cloud, India | Public cloud + public LLM | **Hybrid** |
|---|---|---|---|---|
| Identified data stays in India | Strong | Strong | **Weak.** Fails the addendum outright | Strong for the patient's own identifiers: the build scrubs at one gateway and refuses identified system prompts. **Other people's names in free text leak today** |
| Access to current models | Weak. The Ollama adapter was never verified on a server | Fair | Strong | Strong, for de-identified calls |
| Operations burden | Weak | Fair | Strong | Fair: two estates |
| Cost at 9,000 a day | Fair | Fair | Fair | Fair. Model cost was about $0.017 a consultation in the MVP; infrastructure is unpriced |
| Time to first value | Weak | Fair | Strong | Fair: the demo exists; hardening takes weeks |
| Audit and control | Strong | Strong | Fair | Strong on identified data: append-only audit, triggers |

## Decision: hybrid

Identified data, OCR, embeddings, speech to text and the scrubber's placeholder map stay in an India-region private estate. Only scrubbed text reaches an outside model, through the one gateway. Public cloud fails the residency rule. On-premise gives up current models for no residency gain over an India-region estate.

## What would make us switch

- **To private cloud only**, with an India-hosted model for everything: if the privacy office rejects any outside provider (D2 question 10), or if a provider's terms don't give zero retention. The Ollama adapter is the starting point.
- **To on-premise:** if a regulator or the board requires that clinical text never leaves the hospital's own premises, even in-region.
- **Away from the current provider:** if de-identification can't be made reliable for other people's names in free text. It leaks today (see `AI-COLLABORATION.md`).

## Not yet proved

- a load test on real infrastructure
- backups and restore within 4 hours
- OIDC sign-in in place of the dev login
- an egress allowlist at the network
- the provider contract
