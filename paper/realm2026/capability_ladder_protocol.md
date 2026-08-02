# REALM 2026 capability-ladder protocol

## Scientific question

Does bounded retrieval-first ReAct supply more complementary accuracy than the
one-call Static workflow as model capability increases from an efficient tier
to a stronger balanced tier?

This is a development-only capability study. It neither executes the sealed
900-example partition nor reopens any completed REALM experiment.

## Scientific distinction and shared source of truth

The completed harmonized-v2 study tested a structural correction with
GPT-4o-mini. This study changes the model capability tier while holding that
corrected method contract fixed. It therefore has a separate stable protocol
and runner named `realm26_capability_ladder`; it is not a replacement or a
third version of harmonized v2.

The shared source of truth remains:

- `realm26_harmonized_v2_prompts.py` for the strict Static and retrieval-first
  ReAct prompts;
- `realm26_harmonized_v2_methods.py` for Static, bounded ReAct, parsing,
  evidence/context ceilings, and malformed-output behavior;
- the existing finance scorer, retrieval environment, telemetry schema, and
  paired statistical utilities.

The capability-only request adapter exists to bind the two new OpenRouter
models without modifying any hash-bound harmonized-v2 file.

## Models and request contract

- Efficient tier: requested `openai/gpt-5.6-luna`, frozen canonical slug
  `openai/gpt-5.6-luna-20260709`.
- Stronger balanced tier: requested `openai/gpt-5.6-terra`, frozen canonical
  slug `openai/gpt-5.6-terra-20260709`.
- Static and ReAct use the same model within each tier.
- Both use `reasoning_effort=none`.
- Temperature and `top_p` are not sent.
- Routing is OpenAI-only with fallback disabled, required-parameter matching,
  and data collection denied.
- Any identity, endpoint, parameter, provider, price, or schema drift stops the
  study before a paid call.

## Frozen sample and exclusions

One 150-item sample is shared by both tiers: 50 FinQA, 50 TAT-QA, and 50
ConvFinQA items. Selection uses seed `20260801` after excluding identifiers,
contexts, and dialogues from the original development study, the sealed final
partition, the second-family study, harmonized v1, and harmonized v2. TAT-QA
contexts and ConvFinQA dialogues are excluded as complete groups.

The final manifests may be read only for identifier overlap exclusion. Their
examples are never loaded, rendered, copied, executed, or scored.

## Shared workflow contract

Both arms use the same strict JSON final-answer parser, canonical parsed-answer
scorer input, malformed-to-`UNKNOWN` behavior, one-attempt policy, retrieval
API, 3,000-word evidence ceiling, three-retrieval ceiling, 4,096-word per-call
context ceiling, and 384-token output ceiling.

Static makes exactly one model call. ReAct must begin with Search, observe
nonempty evidence, perform at least one retrieval and two model calls, and stay
within seven model steps. Valid outputs are immutable.

## Prospective Terra trigger

Luna runs to completion before any outcome analysis. Terra runs automatically
if and only if the lower bound of Luna's primary paired 95% bootstrap interval
for ReAct minus Static is less than or equal to zero. If that lower bound is
greater than zero, the study stops after Luna. Manual override is forbidden.

If triggered, Terra uses the identical manifest, prompts, methods, limits,
scoring, and analysis.

## Analysis plan

The primary quality statistic is the unweighted macro-average of FinQA exact
match, TAT-QA F1, and ConvFinQA exact match. Uncertainty is a paired,
dataset-stratified, 10,000-resample percentile bootstrap for ReAct minus
Static.

For each tier, report dataset and macro quality, the 2-by-2 exact-correctness
matrix, exact McNemar test, ReAct-only and Static-only frequencies, oracle-union
accuracy and headroom over the better branch, calls, retrievals, input/cached/
output/reasoning/total tokens, effective cost, and episode latency. If Terra is
triggered, paired Terra-minus-Luna changes are reported separately for each
workflow. They are secondary and do not replace the primary endpoint.

No router is fit on these outcomes. Router feasibility is interpreted from the
prospectively specified complementarity matrix and oracle headroom; this avoids
training and evaluating a selector on the same items.

## Budget and retained record

The hard caps are USD 5 for Luna and USD 15 for Terra. A conservative planning
reservation assumes two tokens per prompt word, the 384-token output ceiling,
one Static call and up to seven ReAct calls on every item, plus a 10% margin.
This reserves at most USD 1.385472 for Luna and USD 13.854720 for Terra.

Raw prompts, traces, per-example predictions, ledgers, logs, and intermediate
outputs remain under ignored `runs/realm26_capability_ladder/`. The retained
record is limited to this memo, the identifier/hash manifest, catalog snapshot,
test attestation, aggregate analysis, complementarity matrix, decision report,
artifact update, and checksums.

## Claims scope

The conclusions apply to bounded retrieval-first ReAct over controlled
financial-QA evidence under these prompts, retrieval policies, scorers, and
model tiers. They are development evidence, not a sealed-test estimate, a
universal claim about agents, or independent human validation.
