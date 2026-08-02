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

The first replacement smoke exposed a separate response-format ambiguity:
Luna returned two valid action objects in one turn (Search followed by Finish),
which the strict one-object parser correctly rejected as malformed. The next
prospective freeze adds only an explicit one-action-per-turn instruction. The
answer contract, first-action Search requirement, retrieval limits, evidence,
scoring, and all completed harmonized-v2 files remain unchanged. This
capability-specific adapter is hash-bound and applied identically to Luna and
Terra.

The clarification passed its counted smoke but later produced another
multi-object first turn. The final freeze therefore uses the standard OpenAI
endpoint's advertised strict structured-output facility: Static is constrained
to one `Finish` object, the first ReAct turn to one `Search` object, and later
ReAct turns to one of `Search`, `Lookup`, or `Finish`. The model still chooses
the query, subsequent actions, and answer; only the already specified action
grammar is enforced. Three called FinQA items were replaced prospectively, and
the remaining 147 items were carried forward without outcome inspection.

OpenRouter then returned two schema-valid `Search` objects in a single response,
despite accepting strict structured-output parameters. The final parser applies
the standard streaming convention of executing the first complete JSON object
and ignoring trailing response text. This preserves one action per environment
turn without changing the model-selected first query. The called item was
replaced; 149 never-called items from that freeze were carried forward.

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

The first counted Luna smoke attempt at public commit `3b4698e` stopped after
one provider call because OpenRouter returned the requested alias in its
response-model field while the initial freeze expected the dated catalog slug.
No answer, score, correctness, or aggregate outcome was inspected or retained.
The replacement freeze preserves the 149 never-called items and replaces only
the consumed FinQA identifier (`finqa41`) using seed `20260802`. Rebuilding the
sample must first reproduce the superseded manifest fingerprint and then apply
that outcome-independent replacement. Excluding the entire superseded manifest
would make a new balanced sample impossible because no wholly fresh TAT-QA
context remains. The failed call's maximum reservation still counts toward the
authorized budget.

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

## Prospective tier execution

Luna and Terra are both required. They run in that order on the identical
manifest, prompts, methods, limits, scoring, and analysis contract. No outcome
or aggregate is inspected until both tiers are complete; skipping Terra based
on Luna's result is forbidden.

## Analysis plan

The primary quality statistic is the unweighted macro-average of FinQA exact
match, TAT-QA F1, and ConvFinQA exact match. Uncertainty is a paired,
dataset-stratified, 10,000-resample percentile bootstrap for ReAct minus
Static.

For each tier, report dataset and macro quality, the 2-by-2 exact-correctness
matrix, exact McNemar test, ReAct-only and Static-only frequencies, oracle-union
accuracy and headroom over the better branch, calls, retrievals, input/cached/
output/reasoning/total tokens, effective cost, and episode latency. Paired
Terra-minus-Luna changes are reported separately for each
workflow. They are secondary and do not replace the primary endpoint.

No router is fit on these outcomes. Router feasibility is interpreted from the
prospectively specified complementarity matrix and oracle headroom; this avoids
training and evaluating a selector on the same items.

## Budget and retained record

The final replacement-run caps are USD 4.99586992075 for Luna and USD 15 for
Terra. The prior-attempt allowance is USD 0.00413007925: the USD 0.00115456
maximum reservation from the alias-binding failure plus USD 0.0005714775 of
recorded provider spend from the first multi-action process failure and USD
0.00176861025 from the later unconstrained-decoding run and USD 0.0006354315
from the multi-object structured-output smoke. Together the
combined authorization is exactly USD 20. A conservative planning
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
