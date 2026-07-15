# REALM 2026 prompt/context-harmonized corrective replication protocol

Status: prospectively frozen before inference. This is a development-only
corrective study. It is scientifically and procedurally separate from the
original documented selector gate: it does not reopen, replace, or retroactively
change that gate or the 75-item second-family replication.

## Question and estimand

The study compares one-call Static financial QA against bounded iterative ReAct
after removing the acceptance-critical prompt and context asymmetries identified
by the fairness audit. The primary estimand is ReAct minus Static in the
unweighted macro of the dataset-native serialized metrics: exact match for
FinQA and ConvFinQA, and F1 for TAT-QA.

## Sample and partition isolation

The deterministic manifest contains 150 fresh development items: 50 per
dataset. Seed `20260715` is applied only after excluding identifiers from:

1. all 250 original development items (50 in each of five datasets),
2. all 75 items in the second-family replication, and
3. all 900 sealed-final identifiers (100 FinanceBench and 200 per other
   dataset).

Only FinQA, TAT-QA, and ConvFinQA are used, so 275 identifiers are excluded per
included dataset. ConvFinQA also excludes every dialogue represented in any
reserved set. TAT-QA excludes an entire source context if any question in that
context has a reserved identifier. The lazy offline adapter uses Arrow list
offsets for TAT-QA context mapping and dereferences only eligible development
rows. Final examples are never rendered, executed, scored, hashed as content,
or inspected. Final-manifest indices, example IDs, and dialogue IDs/hashes are
used only for overlap exclusion.

## Harmonized treatment contract

Both systems use the same frozen model and provider route, temperature, retry
policy, answer schema, parser, scorer input, evidence ceiling, retrieval ceiling,
per-call context ceiling, and output ceiling.

- Model: `openai/gpt-4o-mini-2024-07-18` through OpenRouter with `only=[OpenAI]`,
  `allow_fallbacks=false`, `require_parameters=true`, and data collection denied.
- Sampling: temperature 0, top-p 1, one attempt, no fallback.
- Answer schema: exactly one JSON object. A final answer is
  `{"thought":"...","action":"Finish","answer":"short answer"}`.
- Malformed policy: invalid JSON, an invalid action, or a missing required field
  becomes canonical `UNKNOWN` immediately, identically in both arms, with no
  repair or retry.
- Scoring: only the canonical parsed `answer` string is passed to the same
  framework-blind dataset scorer, with target scale/type supplied only after
  `Finish` on the scorer side.
- Evidence: at most 3,000 whitespace words enter model-visible evidence per
  item, truncated before prompt construction.
- Retrieval: at most three Search/Lookup operations per item.
- Context: every provider prompt is at most 4,096 whitespace words, with frozen
  instructions/question retained and recent ReAct history fitted only in the
  remaining allowance.
- Output: at most 384 tokens per call in both arms.

The treatment difference is preserved. Static deterministically issues up to
three structured searches and then makes exactly one model call. ReAct makes up
to seven sequential model calls, adaptively choosing Search, Lookup, or Finish,
while staying within the shared evidence, retrieval, context, and output limits.
Total calls, provider input/output tokens, cost, provider-call latency, and
episode wall time are outcomes, not forced equal.

## Inference and complementarity analysis

The frozen analysis reports per-dataset native quality, an unweighted macro,
and 10,000-resample paired percentile intervals. The primary interval is
dataset-stratified so every resample preserves pairing and the macro estimand.
ReAct-minus-Static paired intervals are also reported for calls, retrieval
operations, total tokens, cost, and episode wall time. Complementarity is
reported with both-correct, Static-only, ReAct-only, and both-wrong counts, exact
two-sided McNemar inference, oracle-union accuracy, and success-set Jaccard
overlap. No result-contingent metric aliasing or post-run analysis change is
permitted. The serialized primary fields are frozen as
`native_scores.exact_match` for FinQA/ConvFinQA and `native_scores.f1` for
TAT-QA. Complementarity always uses binary `native_scores.exact_match`. The
directional interpretation is frozen: Static advantage if the primary
ReAct-minus-Static 95% interval is wholly below zero, ReAct advantage if wholly
above zero, and inconclusive otherwise.

## Execution guards and spend

The hard provider-spend cap is exactly USD 5, including smoke calls. Every call
receives a conservative persistent reservation before dispatch. Duplicate call
keys, unresolved reservations, a charge above its reservation, or a next call
that could exceed the cap stop the study. The first provider, model-binding,
telemetry, dataset, or integrity failure stops the study; guards are never
weakened to continue.

Before any inference call, the executor requires all frozen artifact hashes to
match, the test attestation to report success, the worktree to contain no
non-result changes, and the exact current commit to equal the public remote tip
of `origin/realm26/prompt-context-harmonized-replication`. A two-arm smoke checks
binding and telemetry without printing or summarizing outcomes. The full phase
cannot start without the smoke marker.

Frozen commands (using the project environment):

```bash
PY=/Users/rishisim/Documents/research/nexus/nexus_env/bin/python
$PY -m pytest -q
$PY -m src.agents.finance.run_realm26_harmonized_replication --preflight-only
$PY -m src.agents.finance.run_realm26_harmonized_replication --phase smoke
$PY -m src.agents.finance.run_realm26_harmonized_replication --phase full
$PY -m src.agents.finance.analyze_realm26_harmonized_replication \
  --results-root results/finance/realm26_harmonized_static_react_v1_openai-gpt-4o-mini-2024-07-18 \
  --output paper/realm2026/artifacts/harmonized_replication_v1.json \
  --memo paper/realm2026/harmonized_replication_v1.md
```

If credentials or any guard are unavailable, execution stops with that exact
command and blocker. The frozen protocol and manifest remain the deliverable;
no alternative provider, model, sample, prompt, retry, budget, or guard is
substituted.
