# REALM 2026 prompt/context-harmonized v2 corrective replication

This is a fresh-sample development-only v2 corrective study. It is separate
from the v1 manipulation-check failure and does not reopen or replace the
original documented selector gate. No final-partition example was executed,
scored, or inspected; final-manifest identifiers were used only to exclude
overlap.

## Frozen design

- Public pre-result commit: `a823f884ee5b187e1732be5273776115f41e3501`.
- Sample: 150 fresh development items (50 each from FinQA, TAT-QA, and
  ConvFinQA), disjoint from the original 250, the 75-item second-family study,
  all 150 v1 items, and the 900 final identifiers.
- Binding: `openai/gpt-4o-mini-2024-07-18`, OpenAI-only through OpenRouter, temperature
  zero, one attempt, no provider fallback.
- Harmonization: identical strict JSON finish contract, canonical scorer input,
  malformed-to-UNKNOWN fallback, 3,000-word cumulative evidence ceiling, three
  evidence operations, 4,096-word per-call context ceiling, and 384 output
  tokens per call. Static remains one call; ReAct remains bounded iterative.
- Treatment integrity: every ReAct row began with a model-selected Search,
  observed evidence, and used at least two model calls. All 150 ReAct rows and
  all 150 one-call Static rows passed their prospectively frozen process checks.
- Provider spend: USD 0.113443 under the USD 5 cap.

## Development result

Static macro dataset-native quality was 0.3421; ReAct was
0.2572. The paired dataset-stratified ReAct-minus-Static estimate
was -0.0849 (95% percentile interval -0.1467 to
-0.0252). Exact complementarity counts were: both correct
23, Static-only 21, ReAct-only
5, and both wrong 101 (exact
McNemar p=0.00249392).

The frozen directional interpretation is
`static_advantage`.

Static averaged 1.000 model calls and USD
0.000452 per item; ReAct averaged
2.040 calls and USD 0.000304.

These are development-only findings and support no claim about the sealed final
partition or a universal advantage of static or agentic reasoning.
