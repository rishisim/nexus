# Capability-ladder seed-stability protocol

## Question and status

This post-hoc process check asks whether the completed capability-ladder result
is stable to one different provider request seed. It is not a new endpoint, a
fresh-sample confirmation, or a nonzero-reasoning ablation. The original
outcomes motivated this check, so the paper and artifact must label it post hoc.

No replication outcome may be inspected or scored until all 900 scheduled
episodes finish and the process-completion record passes.

## Fixed comparison

The replication reuses the exact original 150-item development manifest and
counterbalanced order. It executes both Static and bounded retrieval-first
ReAct for all three mandatory tiers: GPT-4o-mini, GPT-5.6 Luna, and GPT-5.6
Terra. The protected held-out evaluation split remains untouched.

Everything except the request seed is inherited unchanged from the public
capability-ladder protocol: model aliases and dated catalog identities, OpenAI-
only provider routing, no fallback or provider data collection, strict
function-tool schemas, prompts, scorers, retrieval API and ceilings, output and
context ceilings, reasoning disabled, one attempt per call, and all stop rules.
The original request seed is `20260802`; the replication seed is `20260803`.
Sampling parameters remain omitted, so the check measures stability under the
same provider-default sampling contract rather than claiming deterministic
decoding.

## Frozen analysis

After both runs are complete, report them side by side rather than pooling them
as independent samples. For each run and tier, report:

- Static and ReAct native macro quality;
- the exact B/S/R/N complementarity matrix;
- exact oracle headroom over the empirically better arm with a two-sided 95%
  Clopper--Pearson interval for the corresponding rare one-sided cell;
- F1-inclusive continuous oracle headroom, defined as the dataset-macro mean of
  the per-item maximum native quality minus the better single-arm macro, with a
  dataset-stratified paired 10,000-resample percentile interval; and
- per-dataset quality and continuous headroom, including TAT-QA as the operating
  point furthest from the exact-match floor.

The stability report records all changes in arm ordering and headroom counts;
there is no result-dependent pass threshold. The continuous analysis seed is
`20260804`.

## Budget and stopping

All earlier attempts, probes, and the completed main study cost
US$1.007179811. At the live frozen prices, reserving every allowed replication
call plus the original conservative margin costs at most US$18.499536, for a
cumulative worst case of US$19.506715811 under the authorized US$20 cap.

Any provider drift, malformed action, missing telemetry, length cutoff, budget
breach, or treatment-integrity failure stops the whole replication without
retry. Partial outcomes remain unscored. A repair would require another public
freeze; it may not be made during this run.
