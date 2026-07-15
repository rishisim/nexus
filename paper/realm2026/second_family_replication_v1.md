# REALM 2026 second-family replication memo

This is a prospectively frozen, publicly timestamped replication of the Static
Nexus versus bounded-ReAct branch comparison. It is not a preregistration and
does not tune or reevaluate the failed selector. The prior study remains
prespecified/protocol-locked.

## Frozen design

- Model: `openai/gpt-4o-mini-2024-07-18` through the OpenAI endpoint on OpenRouter,
  with provider fallback disabled, temperature 0, and exact binding checks.
- Sample: 75 new development-evidence items (25 each from FinQA, TAT-QA, and
  ConvFinQA), disjoint from both the older 250-item development sample and the
  sealed 900-item final partition.
- Systems: Static Nexus and seven-step bounded ReAct only.
- Public pre-result freeze: verified; the identity-bearing commit identifier is
  omitted from double-blind review materials.
- Total provider spend: USD 0.124660 under the USD
  15 hard cap.

## Result

Static Nexus macro quality was 0.3093; bounded ReAct was
0.0683. Static-only exact successes numbered
19, versus 1 ReAct-only
successes. Static Nexus averaged 1.000 calls and USD
0.000511 per item; bounded ReAct averaged
5.827 calls and USD 0.001151.

The prospectively frozen qualitative transfer criterion was met. The four locked checks were: quality=true,
unique-success ordering=true,
call ordering=true, and
cost ordering=true.

These 75 examples remain development evidence. They do not unseal or estimate
performance on the 900-example final partition, and they do not support a
universal claim about agentic reasoning.


## Analysis implementation correction

The prospectively frozen v1 analysis executable stopped before producing an
artifact because it treated the planned `execution_accuracy` label as a literal
serialized key. The existing scorer serializes that same FinQA/ConvFinQA binary
endpoint as `exact_match`. Version 1.1 applies only this mechanical alias and
reuses the frozen computations unchanged. No provider call, result, sample,
metric definition, hypothesis, threshold, or stopping rule changed.
