# REALM 2026 fairness and failure-taxonomy audit

Status: **development-only, deterministic Codex audit; not human validation**.
This memo does not change official scores, the router, the protocol, saved
results, or the active manuscript. It uses no provider calls and does not load
the sealed final partition or any final-manifest examples.

## Executive finding

The comparison is controlled on the most important foundations: all four
systems use the same evidence packets and environment implementation, all saved
rows requested and resolved `google/gemini-2.5-flash`, all calls used the shared
retry implementation, the same framework-blind dataset scorer was applied
after generation, and every audited development call has a telemetry record.

It is not an equal-compute or equal-prompt comparison, by design. Direct and
CoT/PoT make one search and one model call; Static Nexus makes up to three
deterministic searches and one model call; ReAct receives up to seven model
calls and chooses searches/lookups adaptively. More importantly for the
failure analysis, the one-call prompts explicitly require a short final-answer
line, whereas the ReAct prompt does not require a short or number-only
`Finish[...]` value. The conservative scorer rejects multi-number or verbose
answers. The output-contract difference therefore interacts with exact score.

The audit reproduces the official 52 one-sided exact-score disagreements: 42
Static-only and 10 ReAct-only. A deterministic, recall-oriented rule flags 28
of the 52 (53.8%) as **scorer-sensitive candidates** because the scored-wrong
answer visibly contains the normalized reference span, the reference number,
or a close rounded/scale-normalized form. This includes **all 10 ReAct-only
cases** and **18 of 42 Static-only cases**. These are not corrected answers and
not human judgments; units, scale, extra claims, ambiguity, and rounding still
need review. The official 42/10 counts remain unchanged.

Among the other 24 Static-only cases, the wrong ReAct trace shows 18 explicit
abstentions after retrieval, one finish without retrieval, one adapter-forced
`UNKNOWN` after seven model steps, one submitted but unevaluated arithmetic
expression, and three residual answer mismatches requiring judgment. Thus the
saved evidence supports a strong claim about ReAct abstention behavior, but not
yet a strong causal claim that 42 cases reflect inferior reasoning or retrieval.

## Fairness audit

| Dimension | Assessment | Evidence and implication |
| --- | --- | --- |
| Evidence source | Comparable | The protocol disables external retrieval and calculators. Every method uses the same dataset adapter and controlled packet. This is orchestration over controlled evidence, not end-to-end retrieval. |
| Retrieval API | Shared API, different policy | `Search` and `Lookup` have shared environment semantics. Direct/CoT use one `Search`; Static builds up to three deterministic queries; ReAct adaptively uses `Search`/`Lookup`. Across all 250 development examples, saved retrieval operations total 250 for Direct, 250 for CoT, 702 for Static, and 509 for ReAct. |
| Model binding | Comparable | All 1,000 audited rows (five datasets × four systems × 50 examples) requested and resolved `google/gemini-2.5-flash`. The runner refuses a method that cannot accept `model_id`. |
| Sampling/model-internal reasoning | Comparable | Calls are single-trace, giving temperature 0; Gemini internal thinking is disabled by the protocol/provider request. |
| Prompts | Method-specific, consequential asymmetry | Direct/CoT/Static require `Answer: [short answer]`; ReAct only defines `Finish[answer]`. Trace review shows verbose final answers are disproportionately exposed to strict parsing. |
| Model-call/output limits | Intentionally unequal | Direct/CoT/Static receive one call with a 768-output-token ceiling. ReAct receives up to seven calls with a 512-token ceiling each and averaged 3.032 calls/example over all five datasets. This is appropriate for comparing the configured systems, not for an equal-compute claim. |
| Evidence/context budget | Not equivalent | One-call dossiers are truncated to 4,096 whitespace tokens before prompt construction. ReAct appends observations to a growing transcript during inference and truncates only the separately saved dossier after the episode. No common input-context ceiling is enforced. Aggregate input-token telemetry exists, but provider-side context truncation cannot be reconstructed. |
| Retries | Comparable | The shared implementation allows five attempts only for connection/timeout/408/409/429/5xx failures. Every audited row has `retry_count = 0`; valid outputs were never regenerated. |
| Scorer | Same scorer, prompt interaction | The runner applies the same dataset-native scorer independent of framework. Numeric parsing deliberately requires one unambiguous final number, and strict span matching rejects added prose. This protects against accidental gold-number mentions but makes the answer contract part of measured performance. |
| Telemetry | Call-complete, method-diagnostic gaps | Per-call tokens, costs, latency, retries, backend, model IDs, and raw traces have 100% call-record coverage. Runner serialization drops method-layer `n_badcalls`, `dossier_truncated`, and an explicit termination-reason field. |
| Malformed output/nontermination | Asymmetric fallback | Missing ReAct actions are converted immediately to `Finish[UNKNOWN]`; seven-step exhaustion adds `Finish[UNKNOWN]`. A one-call output missing `Answer:` instead falls back to its last non-empty line. Both are final valid-output handling, not retryable failures, but they are not equivalent. |
| Provenance freeze | Incomplete | The protocol says `foundation_unfrozen` and leaves prompt/scorer artifact hashes null. The shared run directory's `config.json` was updated by the later Selective run, although `run_history.json` preserves the earlier four-framework execution. The audit therefore hashes every source/result input it uses. |

Implementation anchors are `method_prompts.py` (answer contracts),
`finance_methods.py::_run_one_call_method`, `finance_methods.py::run_react`,
`run_finance_experiments.py::_success_record`,
`finance_scoring.py::parse_numeric_answer`, and
`src/shared/llm.py::llm_with_metadata`.

## Trace audit and taxonomy

The artifact contains every one-sided disagreement and a frozen sample of 20
both-wrong cases (five per objective dataset). Both-wrong examples are ranked
by ascending
`SHA-256("realm2026-both-wrong-v1:<dataset>:<example_id>")`, with `example_id`
as the deterministic tie-breaker. The population has 111 both-wrong examples:
27 FinanceBench, 30 FinQA, 25 TAT-QA, and 29 ConvFinQA.

Each row records dataset/example ID, official exact-correctness pattern,
ground truth, both final answers, call/retrieval/retry counts, action sequence,
search queries when recoverable, trace excerpt and SHA-256, category,
confidence, ambiguity, and a manual-review flag.

The categories deliberately describe observable surface signals:

- `forced_nontermination`: seven ReAct model calls followed by the adapter's
  synthetic `Finish[UNKNOWN]`.
- `premature_finish_no_retrieval`: ReAct finished with no saved search/lookup.
- `abstained_after_retrieval`: the submitted answer explicitly abstained after
  at least one retrieval.
- `unexecuted_calculation`: the submitted answer is an unevaluated expression.
- `scorer_sensitive_candidate`: a rejected answer contains a reference
  span/value or close rounded form; this always requires manual review and
  never changes the score.
- `substantive_answer_mismatch`: a rejected, non-abstaining answer for which no
  narrower deterministic signal fires; causal attribution requires review.
- `mixed_or_ambiguous`: the two both-wrong systems expose different signals.

One-sided counts are:

| Official pattern | Scorer-sensitive candidate | Abstention after retrieval | Premature/no retrieval | Forced limit | Unevaluated expression | Residual mismatch |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Static-only (ReAct scored wrong) | 18 | 18 | 1 | 1 | 1 | 3 |
| ReAct-only (Static scored wrong) | 10 | 0 | 0 | 0 | 0 | 0 |

The 20-item both-wrong sample contains five scorer-sensitive candidates, four
residual substantive mismatches, and eleven mixed/ambiguous cases. Because of
those categories, all 20 sampled both-wrong rows remain in the manual queue.

## Minimum true author/human review

The deterministic mechanics are sufficient to reproduce 21 one-sided surface
signals: 18 post-retrieval abstentions, one no-retrieval finish, one forced
step-limit termination, and one unevaluated expression. No human review is
needed merely to verify that those trace events occurred.

The minimum remaining review for a paper-ready disagreement taxonomy is **51
items**:

- 28 one-sided scorer-sensitive candidates: determine semantic correctness,
  unit/scale validity, whether extra prose changes the answer, and whether the
  official score should be accompanied by a sensitivity analysis.
- 3 one-sided residual mismatches: distinguish evidence selection, arithmetic,
  period/unit, and other reasoning failures from the full trace.
- all 20 frozen both-wrong examples: five scorer-sensitive, four residual, and
  eleven mixed cases.

If the paper wants causal labels for the 21 mechanical/behavioral cases (for
example, why ReAct abstained despite retrieval), those also require author
review; the deterministic label alone supports only the observed event.
Blinded dual review with disagreement resolution would be preferable for any
reported semantic reclassification. Codex-produced categories must not be
described as human validation.

## Paper-ready wording (pending the review above)

> On the official development exact scores, Static Nexus and bounded ReAct
> disagreed one-sidedly on 52 of 200 objective examples (42 Static-only versus
> 10 ReAct-only). A deterministic trace audit found that 28/52 scored-wrong
> outputs visibly contained the reference span/value or a close rounded form,
> including all ten ReAct-only cases and 18 Static-only cases. We retain the
> official scores and treat these only as scorer-sensitive candidates pending
> author adjudication. Among the remaining 24 Static-only cases, ReAct
> explicitly abstained after retrieval in 18, finished without retrieval in
> one, exhausted its seven-step bound in one, submitted an unevaluated
> expression in one, and had three residual mismatches. The observed gap thus
> combines orchestration behavior with answer-contract/scorer interaction and
> should not be attributed wholly to retrieval or reasoning quality.

## Exact limitations

1. This is a post hoc analysis of method-selection/development outcomes, not a
   held-out evaluation.
2. The taxonomy is deterministic and Codex-produced. It is neither human
   validation nor an independent semantic correctness study.
3. “Scorer-sensitive candidate” is an intentionally over-inclusive review
   trigger. Reference-value presence can reflect an operand, a wrong unit, an
   unsupported statement, or an otherwise incorrect answer.
4. Official scores are unchanged. No claim about revised accuracy or revised
   complementarity is warranted before author adjudication under a frozen rule.
5. The both-wrong results cover a deterministic 20/111 sample, not the entire
   both-wrong population.
6. Missing persisted `n_badcalls`, dossier-truncation state, and termination
   reason prevent exact reconstruction of every malformed-action path.
7. ReAct's inference transcript and the one-call dossier do not share an
   enforced context budget, so the comparison cannot be called equal-context.
8. Null prompt/scorer hashes and a later-overwritten config file weaken
   provenance, although source/result hashes and run history make this audit
   reproducible from the present repository state.
9. FinanceBench's strict score is a sensitivity measure rather than validated
   semantic evaluation, and FinDER remains excluded from correctness patterns.
10. Nothing here supports a universal claim that agentic reasoning fails; the
    evidence is limited to this model, these development examples, these
    prompts, and controlled-evidence financial QA.

## Reproduction

```bash
python3 -m src.agents.finance.audit_realm_fairness
python3 -m src.agents.finance.audit_realm_fairness --check
python3 -m pytest tests/finance/test_realm_fairness_audit.py -q
python3 -m pytest tests/finance -q
```

Machine-readable outputs:

- `paper/realm2026/artifacts/fairness_audit.json`
- `paper/realm2026/artifacts/fairness_audit.csv`
