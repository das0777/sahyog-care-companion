# ADR 0004: OpenRouter as the provider, and traces in Postgres

**Status:** Accepted with S7, pending user review · **Date:** 2026-10-30

## Context

The specification names direct model access through a gateway, and Langfuse for traces. During the build, the user's available account was OpenRouter, and Docker on the development Mac has 8 GB of memory.

## Decisions

1. **Model calls go through OpenRouter** by the user's choice, using the same Claude models at the same listed prices. Requests ask for endpoints that honour the schema and don't collect prompts. The direct Anthropic adapter stays and is selected by one setting.
2. **The vendor can be changed by settings alone** (E6.4). All three dev sets passed on `google/gemini-2.5-flash` with no code or prompt change. That's dev cases only, tuned on Claude, and it doesn't include the frozen test sets.
3. **Traces go to a Postgres table, not Langfuse.** Langfuse's current self-hosted form needs ClickHouse, Redis and object storage alongside it. Each model call writes one row: workflow, model, tokens, cost, latency, outcome, and what was scrubbed. It holds no prompt or reply text. A Langfuse exporter can replace `record_span` without touching a graph. **This departs from the spec and is the user's to overrule.**

## Consequences

- OpenRouter is a further party handling scrubbed text. It needs privacy review before real use, and India-only processing isn't provided by this route. For real identified workloads, ADR 0005 applies.
- There are spans for model calls only, not for each graph node and tool as the spec asks. Tool and node timing isn't traced.
- Trace rows have no retention job yet.
