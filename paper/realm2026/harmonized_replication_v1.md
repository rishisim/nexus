# REALM 2026 prompt/context-harmonized corrective replication

This is a development-only corrective study. It is separate from, and does not
reopen or replace, the original documented selector gate. No final-partition
example was executed, scored, or inspected; final-manifest identifiers were
used only to exclude overlap.

## Frozen design

- Public pre-result commit: `95690654f6724315f5465db0e0d3d9a97db95abc`.
- Sample: 150 fresh development items (50 each from FinQA, TAT-QA, and
  ConvFinQA), disjoint from the original 250, the 75-item second-family study,
  and the 900 final identifiers.
- Binding: `openai/gpt-4o-mini-2024-07-18`, OpenAI-only through OpenRouter, temperature
  zero, one attempt, no provider fallback.
- Harmonization: identical strict JSON finish contract, canonical scorer input,
  malformed-to-UNKNOWN fallback, 3,000-word cumulative evidence ceiling, three
  evidence operations, 4,096-word per-call context ceiling, and 384 output
  tokens per call. Static remains one call; ReAct remains bounded iterative.
- Provider spend: USD 0.072822 under the USD 5 cap.

## Development result

Static macro dataset-native quality was 0.3057; ReAct was
0.0000. The paired dataset-stratified ReAct-minus-Static estimate
was -0.3057 (95% percentile interval -0.3736 to
-0.2395). Exact complementarity counts were: both correct
0, Static-only 39, ReAct-only
0, and both wrong 111 (exact
McNemar p=3.63798e-12).

The frozen directional interpretation is
`static_advantage`.

Static averaged 1.000 model calls and USD
0.000434 per item; ReAct averaged
1.000 calls and USD 0.000051.

These are development-only findings and support no claim about the sealed final
partition or a universal advantage of static or agentic reasoning.
