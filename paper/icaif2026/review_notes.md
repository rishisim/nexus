# ICAIF 2026 Development-Gate Review

## Recommendation: do not submit this version to the main conference

The locked development gate failed. The correct decision is to preserve the unopened 900-example final manifest and either submit a narrowly framed workshop/protocol negative result or redesign the method for a later main-track study. Running the final set now would violate the paper's own go/no-go rule and turn the untouched benchmark into another tuning set.

This recommendation is about the current evidence, not the general topic. Selective computation for financial QA remains a strong ICAIF question, and the controlled-evidence protocol is valuable. The present router, however, is neither accurate nor cost-efficient enough to justify confirmatory evaluation.

## Frozen development facts

Source: `paper/icaif2026/artifacts/development_summary.json`, tag `dev-20260709`.

| System | Primary development macro | US$/example |
| --- | ---: | ---: |
| Direct | 0.4138 | 0.000343 |
| CoT/PoT | 0.432333 | 0.000819 |
| Static Nexus | 0.4304 | 0.001010 |
| ReAct | 0.299267 | 0.001479 |
| Selective Nexus | 0.367533 | 0.001322 |

Router gate:

- 200 objectively labeled examples; FinDER excluded because it lacks human-validated objective labels.
- 10 ReAct-only benefit cases.
- At least one cross-validation fold had fewer than five usable benefits, so the preregistered rule fallback fired.
- Frozen fallback thresholds: lexical coverage below 0.666667 or retrieval margin in the lowest quartile (1.0), together with the registered narrative/implication cue.
- The rule escalated 70% of cases.
- Offline saved-branch estimate: 0.280 exact accuracy. The fresh selective
  rerun achieved 0.295 versus 0.395 for always static.
- Observed selective mean cost on the 200-example router set: US$0.001431.

## Why the main-track gate failed

- Selective Nexus is 0.0648 below the best development macro, not within the allowed one-point band.
- Selective Nexus costs more than CoT/PoT, so it cannot satisfy the required 30% cost reduction.
- Static Nexus does not supply the conditional pivot: CoT/PoT is slightly more accurate and cheaper.
- ReAct is the lowest-quality and highest-cost primary system, so routing 70% of cases to it predictably harms the fallback.
- The benefit class is too sparse for the planned logistic selector: only 10 of 200 objective cases are ReAct-only successes, versus 42 Static-only successes.
- No cross-family replication, final paired inference, semantic FinDER validation, or component ablation can rescue the locked gate because those steps were conditional on passing it.

## What is still publishable as a workshop/protocol report

- A negative result showing that uniformly iterative ReAct and broad escalation can be dominated by simpler one-call reasoning under controlled evidence.
- A transparent example of preregistered stopping that protects an untouched benchmark rather than spending a larger test set on a failed method.
- A leakage-audited five-dataset development protocol with provider-level cost and latency instrumentation.
- Evidence that “agentic difficulty” is a rare asymmetric label in this development set, making naive balanced routing unstable.
- A concrete redesign agenda: first demonstrate a complementary iterative expert, then train a gate on new development evidence.

The workshop paper must call all numbers development-only, avoid significance language, and state that the 900-example manifest was not opened. It must not imply a five-dataset narrative result because FinDER has no objective or human-validated correctness labels here.

## Hostile reviewer checks for the workshop version

- [ ] The abstract says “development gate” and “negative result,” not “evaluation” or “held-out improvement.”
- [ ] The quality--cost figure and both tables are labeled development-only.
- [ ] No text reports the 900-example manifest as completed, evaluated, or inspected.
- [ ] No claim generalizes from this model and these 250 development examples to all financial agents.
- [ ] The static, Direct, and CoT/PoT evidence/dossier budgets are described precisely enough to assess fairness.
- [ ] The reason FinDER is excluded from router labels and the primary macro is prominent.
- [ ] The rule fallback is reproduced exactly; it is not retrospectively repaired in prose.
- [ ] Dollar figures retain the dated price snapshot and raw token counts remain available for repricing.
- [ ] The old TAT-QA leakage is acknowledged as historical development contamination and never reused as confirmatory evidence.
- [ ] The repository bundle makes it impossible to confuse `dev-20260709` with a final result tag.

## Requirements before a later main-track attempt

1. Keep the existing 900-example manifest sealed.
2. Assemble a genuinely new development pool; do not retune on the 250 outcomes reported here.
3. Improve or replace the iterative expert until it demonstrates meaningful complementary accuracy on the new pool.
4. Redesign the gate for rare benefits, with calibration and leave-one-dataset-out checks where feasible.
5. Freeze a new go/no-go rule before evaluating the redesign.
6. Open the existing final manifest only after that new gate passes.
7. Then complete cross-family replication, paired inference, ablations, and any human validation needed for narrative claims.

## Venue decision

**Current version: workshop or internal negative-results report.** The protocol discipline is worth sharing, but the empirical contribution is not main-track ready.

**Later redesigned version: potential ICAIF main conference.** The topic remains well aligned with AI agents, financial NLP, robustness, and efficient workflows, provided the new method passes an independent gate and the untouched final evaluation supports the claim.
