# REALM 2026 prompt/context-harmonized corrective replication v2

Status: prospectively frozen before any v2 inference call. This is a fresh-
sample, development-only study. It is scientifically and procedurally separate
from both the original selector gate and harmonized v1.

## Why v2 exists

Harmonized v1 is retained unchanged as a diagnostic. Its ReAct arm selected
`Finish[UNKNOWN]` before retrieving evidence on every item, so all 150 ReAct
rows had one model call, zero retrieval operations, and zero observed evidence.
That is a manipulation-check failure, not credible directional evidence about
iterative ReAct. V1 is not rerun, repaired, or selectively overwritten.

V2 makes one structural correction prospectively: the ReAct model's first
action must be `Search`. A successful ReAct row must therefore begin with a
model-selected Search, observe nonempty evidence, use at least one retrieval
operation, make at least two model calls, and end with validly parsed JSON. Any
violation stops the study. All other model, prompt-budget, parser, scorer,
provider, retry, retrieval, and analysis choices remain fixed.

## Question and estimand

The study compares one-call Static financial QA against bounded iterative ReAct
after harmonizing answer, context, evidence, and output contracts and verifying
that the ReAct treatment actually executes. The primary estimand is ReAct minus
Static in the unweighted macro of the dataset-native serialized metrics: exact
match for FinQA and ConvFinQA, and F1 for TAT-QA.

## Fresh sample and partition isolation

The deterministic manifest contains 150 new development items: 50 each from
FinQA, TAT-QA, and ConvFinQA. Seed `20260720` is applied only after excluding,
for each included dataset:

1. the 50 original-development items,
2. the 25 second-family items,
3. all 50 harmonized-v1 items, and
4. all 200 sealed-final identifiers.

Thus 325 identifiers are excluded per included dataset before sampling. V2 has
no item overlap with v1. ConvFinQA also excludes every dialogue represented in
any reserved set. TAT-QA excludes an entire source context if any question in
that context has a reserved identifier. The lazy offline adapter dereferences
only eligible development rows. Final examples are never rendered, executed,
scored, content-hashed, or inspected; final indices and identifiers are used
only for overlap exclusion.

## Frozen treatment contract

Both systems use the same frozen model and provider route, temperature, retry
policy, answer schema, parser, scorer input, evidence ceiling, retrieval
ceiling, per-call context ceiling, and output ceiling.

- Model: `openai/gpt-4o-mini-2024-07-18` through OpenRouter with
  `only=[OpenAI]`, `allow_fallbacks=false`, `require_parameters=true`, and data
  collection denied.
- Sampling: temperature 0, top-p 1, one attempt, no fallback.
- Answer schema: exactly one JSON object. A final answer is
  `{"thought":"...","action":"Finish","answer":"short answer"}`.
- Malformed policy: invalid JSON, an invalid action, or a missing required field
  becomes canonical `UNKNOWN` with no repair or retry. In ReAct, an invalid
  first action additionally fails the frozen treatment-integrity guard.
- Scoring: only the canonical parsed `answer` string is passed to the same
  framework-blind dataset scorer, with target scale/type supplied only after
  `Finish` on the scorer side.
- Evidence: at most 3,000 whitespace words of model-visible evidence per item.
- Retrieval: at most three Search/Lookup operations per item.
- Context: every provider prompt is at most 4,096 whitespace words.
- Output: at most 384 tokens per call in both arms.

Static deterministically issues up to three structured searches and then makes
exactly one model call. ReAct makes up to seven sequential model calls. Its
first model action must be Search; after observing evidence it adaptively
chooses Search, Lookup, or Finish within the shared limits. Total calls, tokens,
cost, provider-call latency, and episode wall time remain measured outcomes.

## Smoke manipulation check

The smoke phase runs both arms on the first frozen FinQA item. Before the full
run, the controller reads only process metadata and requires:

- exactly one Static model call;
- ReAct's first model action equal to `Search`;
- at least one ReAct retrieval operation and at least one observed evidence
  word;
- at least two ReAct model calls; and
- ReAct parse status `ok`.

The smoke check must not read, print, compare, or summarize either answer or
score. If any process check fails, no smoke marker is written and the full run
is forbidden. The same ReAct process checks are enforced independently on all
150 full-run rows.

## Frozen analysis

The analysis reports per-dataset native quality, an unweighted macro, and
10,000-resample paired percentile intervals. The primary interval is dataset-
stratified. ReAct-minus-Static paired intervals are also reported for model
calls, retrieval operations, total tokens, cost, and episode wall time.
Complementarity is reported with both-correct, Static-only, ReAct-only, and
both-wrong counts, exact two-sided McNemar inference, oracle-union accuracy, and
success-set Jaccard overlap. Directional interpretation is frozen: Static
advantage if the primary interval is wholly below zero, ReAct advantage if it
is wholly above zero, and inconclusive otherwise.

## Integrity and spend guards

The hard provider-spend cap is exactly USD 5 including smoke calls. Every call
receives a persistent conservative reservation before dispatch. Duplicate call
keys, unresolved reservations, a charge above its reservation, or a next call
that could exceed the cap stop the study. The first provider, model-binding,
telemetry, dataset, artifact, public-push, sample-overlap, or treatment-
integrity failure also stops the study; guards are never weakened to continue.

Before inference, the executor requires all frozen artifact hashes to match,
the test attestation to report success, the worktree to contain no non-result
changes, and the exact current commit to equal the public tip of
`origin/realm26/harmonized-replication-v2`.

Frozen commands (using the project environment):

```bash
PY=/Users/rishisim/Documents/research/nexus/nexus_env/bin/python
$PY -m pytest -q
$PY -m src.agents.finance.run_realm26_harmonized_v2_replication --preflight-only
$PY -m src.agents.finance.run_realm26_harmonized_v2_replication --phase smoke
$PY -m src.agents.finance.run_realm26_harmonized_v2_replication --phase full
$PY -m src.agents.finance.analyze_realm26_harmonized_v2_replication \
  --results-root results/finance/realm26_harmonized_static_react_v2_openai-gpt-4o-mini-2024-07-18 \
  --output paper/realm2026/artifacts/harmonized_replication_v2.json \
  --memo paper/realm2026/harmonized_replication_v2.md
```

If any guard or credential is unavailable, execution stops without substituting
another provider, model, sample, prompt, retry, budget, or analysis.
