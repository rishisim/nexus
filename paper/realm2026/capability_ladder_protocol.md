# REALM 2026 three-tier robustness protocol

## Scientific question

Does bounded retrieval-first ReAct remain less accurate and weakly
complementary than one-call Static when both workflows use stronger models and
a compact response contract that removes the earlier implementation failure?

This is a development-only robustness study. It does not execute the protected
final partition or modify the completed pilot and harmonized studies.

## Models and fairness contract

The mandatory tiers are:

- control: requested and canonical `openai/gpt-4o-mini`;
- Luna: requested `openai/gpt-5.6-luna`, canonical
  `openai/gpt-5.6-luna-20260709`;
- Terra: requested `openai/gpt-5.6-terra`, canonical
  `openai/gpt-5.6-terra-20260709`.

The live standard-OpenAI endpoint catalogs were queried before any study item
was selected. Their common supported request parameters include `max_tokens`,
`seed`, `structured_outputs`, `tools`, and `tool_choice`. All tiers use the same
OpenAI-only route, no fallbacks, required-parameter matching, denied data
collection, seed `20260802`, 384-token output ceiling, and no temperature or
`top_p` field.

One exception was authorized prospectively by the author. GPT-4o-mini has no
reasoning channel or advertised reasoning parameter, so that inapplicable field
is omitted for the control. Luna and Terra explicitly send
`reasoning_effort=none`. The request body is otherwise identical after model ID
normalization.

## Compact action contract

Every model must make exactly one call to the same strict function tool. Its
arguments use exactly the fields `action`, `argument`, and `answer` under a
schema with `additionalProperties:false`:

- Static: `Finish` only;
- first ReAct turn: `Search` only;
- later ReAct turns: `Search`, `Lookup`, or `Finish`.

Retrieval actions require a nonempty argument and an empty answer. Finish
requires an empty argument and a nonempty answer. Argument and answer are each
bounded to 1,024 characters by the shared prompt and fail-closed parser. The
provider's common strict-schema subset does not implement string-length
keywords consistently across all three tiers, so the identical local parser
enforces those bounds. The step-specific Static and first-Search schemas also
constrain the inactive field to the empty string. A complete arguments object
is required; assistant text, a second tool call, trailing arguments, a second
object, extra fields, malformed JSON, refusal, any completion reason other than
`tool_calls`, or missing telemetry stops the prospective study. No prefix is
salvaged and there is no retry.

The `thought` field used in earlier attempts is absent from the prompt, schema,
parser, and stored action contract.

## Pre-freeze synthetic probes

Before selecting study examples, the exact provider path was probed with
synthetic non-benchmark prompts for all three action schemas and all three
tiers. An initial pre-freeze probe attempt identified an unsupported
string-length schema keyword after three successful control probes. That
attempt is conservatively charged at USD 0.001213663, including the successful
calls and the unresolved Luna maximum reservation. The schema was changed only
within this allowed pre-freeze phase: string bounds remain identical and
fail-closed in the local parser, while the provider schema uses the common
supported subset.

The subsequent nine probes for the first public freeze all passed. That freeze
then stopped prospectively after 23 successful episodes when Terra's first
ReAct Search produced a schema-shaped object that violated the stricter local
field semantics. The response content was not retained, no outcome was scored
or analyzed, and the four touched examples were added to the exclusion set.
Completed calls cost USD 0.022864446; the unresolved failed call is charged at
its full USD 0.0124344 reservation.

Before constructing the replacement manifest, a fresh set of nine more
realistic synthetic prompts tested the revised shared contract. All nine
passed. That second public freeze then stopped after five successful episodes:
Luna returned non-single JSON through the strict response-format content
channel. No outcome was scored or analyzed, its one touched TAT-QA item was
excluded, completed calls cost USD 0.00574915275, and the unresolved call is
charged at its USD 0.00124344 maximum.

Because two frozen runs exposed different content-channel failures, the shared
transport was prospectively changed to one required strict function-tool call,
using the common `tools` and `tool_choice` parameters. A third set of nine
synthetic probes tested the exact tool transport across every tier and action
schema. All passed with provider `OpenAI`, finish reason `tool_calls`, exactly
one tool, no assistant text, correct model identity, zero reasoning tokens,
complete token/cost telemetry, and the intended reasoning-parameter policy.
These probes cost USD 0.0009945045, bringing successful-probe spend to USD
0.00271458. No benchmark identifier, context, dialogue, answer, or score was
used by any probe.

## Fresh development manifest

The frozen sample contains 50 FinQA, 50 TAT-QA, and 50 ConvFinQA examples. It
uses seed `20260802` after excluding identifier metadata from the original
development partition, protected final partition, second-family study,
harmonized v1, and harmonized v2. It also excludes 17 FinQA identifiers touched
by the five earlier failed freezes and the three ConvFinQA plus two TAT-QA
identifiers touched by the two stopped public freezes. Protected-final data is used
only for identifier overlap exclusion; its contexts, dialogues, answers, and
targets are never loaded or scored. The replacement manifest fingerprint is
`sha256:9ce99b9a38d51d2b900ffd7df81f4dc08e548d7a8def0dede68037a1c4b90934`.

The same 150 examples and order are used for every tier. ConvFinQA selection
retains one turn per wholly fresh dialogue. The manifest stores only identifiers,
hashes, selection metadata, and the frozen schedule.

## Counterbalanced execution

Schedule seed `2026080203` fixes the full order before inference. The 150 items
are deterministically shuffled. Each of the six model-order permutations occurs
exactly 25 times. Within each tier, Static runs first on 75 items and ReAct runs
first on 75 items. All 900 episodes are mandatory; model- or result-dependent
skipping is forbidden.

The runner prints process identifiers only and does not calculate correctness,
aggregate outcomes, or model comparisons while inference is in progress. One
provider or integrity failure stops the freeze. Any repair would require a new
prospective manifest and schedule.

## Shared workflow contract

All tiers use the same examples, prompts, compact answer contract, scorer,
malformed-output rule, retrieval environment, three-retrieval limit, seven-call
ReAct limit, 3,000-word evidence limit, 4,096-word context limit, and 384-token
output limit. A shared 8,192-byte prompt ceiling also applies; because a BPE
token represents at least one input byte, this provides a model-independent
upper bound of 8,192 input tokens for budget reservation. The byte limit is
applied identically after the word limit.

Static deterministically retrieves under the same evidence budget and makes
one model call. ReAct must begin with Search, observe nonempty evidence, perform
at least one retrieval and two model calls, and remain within seven calls.

## Preregistered analysis

No outcomes are analyzed until a process-only completion record establishes
that all three tiers finished all scheduled episodes. For each tier, report:

- FinQA exact match, TAT-QA F1, and ConvFinQA exact match;
- the unweighted three-dataset macro score for Static and ReAct;
- a dataset-stratified paired 10,000-resample percentile bootstrap for
  ReAct minus Static;
- the exact 2-by-2 complementarity matrix, McNemar result, ReAct-only and
  Static-only frequencies, oracle-union accuracy, and oracle headroom;
- calls, retrievals, latency, input/cached/output/reasoning/total tokens, and
  provider cost.

The preregistered interaction is a dataset-stratified paired bootstrap of the
difference between tier-specific ReAct-minus-Static deltas. It is reported for
Luna minus control, Terra minus control, and Terra minus Luna. No router is fit
on these outcomes.

## Budget and retained record

The conservative charge before the replacement study is USD 0.059017211:
USD 0.01279752925 for five earlier failed attempts, USD 0.04229143875 for the
two stopped public freezes, USD 0.001213663 for the failed pre-freeze probe
attempt, and USD 0.00271458 for successful probes. The complete study reserves at most
USD 18.499536, including a 10% margin and a 9,000-input-token reservation that
covers the prompt plus compact schema. The cumulative maximum is USD
18.558553211, leaving USD 1.441446789 below the USD 20 cap.

Raw prompts, per-example predictions, traces, ledgers, and logs remain under
ignored `runs/realm26_capability_ladder/`. The tracked record is limited to the
protocol, manifest and schedule, catalog snapshot, tests and attestations,
sanitized stopped-freeze history, aggregate result tables, compact decision
report, and sanitized paper artifact.

## Claims scope

The result concerns bounded retrieval-first ReAct over controlled financial-QA
evidence under these prompts, retrieval policies, scorers, and model tiers. It
is development evidence, not a protected-final estimate or a universal claim
that iterative agents are inferior.
