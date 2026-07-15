# REALM 2026 paired statistics memo

This memo and its generated tables use only the locked `development` result directories
for `google/gemini-2.5-flash` and tag `dev-20260709`. The sealed final partition was not opened.

## Scope and denominators

- Raw input: 5 datasets × 5 systems × 50 paired development examples.
- Primary quality macro: unweighted mean of FinQA execution accuracy, TAT-QA official F1, and ConvFinQA execution accuracy (50 paired examples per dataset; 150 example rows per system).
- Router complementarity: 200 paired examples across FinanceBench, FinQA, TAT-QA, and ConvFinQA, using exact-match correctness as in the locked router analysis.
- Efficiency: `llm_call_count` is model/answer-call count; retrieval operations are reported separately. Cost uses provider cost when present, otherwise estimated cost. Latency is per-example end-to-end latency; median and P95 use successful rows with available latency.
- Bootstrap: percentile paired bootstrap with 10,000 resamples and seed 20260709; primary macro resamples each dataset stratum independently and averages the three stratum means.

## Recomputed headline values

| System | Primary macro | USD/example |
|---|---:|---:|
| Direct | 0.4138 | $0.000343 |
| CoT/PoT | 0.4323 | $0.000819 |
| Static Nexus | 0.4304 | $0.001010 |
| ReAct | 0.2993 | $0.001479 |
| Selective Nexus | 0.3675 | $0.001322 |

Static exact accuracy: 79/200 (0.395); one-sided successes: 42 Static-only versus 10 ReAct-only; oracle union: 0.445; oracle headroom over static: 0.050.
The observed selective rerun escalated 0.700 of cases and reached 0.295 exact accuracy at $0.001431/example.

## Interpretation boundary

These are method-selection observations on development data, not confirmatory inference or a held-out test estimate. The paired intervals and exact McNemar results quantify uncertainty conditional on this frozen development sample; they do not restore independence after method selection, correct for all exploratory comparisons, or support population-level claims. The results describe controlled/evidence-conditioned reasoning and do not establish end-to-end retrieval or universal agentic failure.

## Verification

The script independently recomputed the existing development summary: `passed`.
