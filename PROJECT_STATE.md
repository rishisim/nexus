# Project State

> Last updated: 2026-07-14

## Active objective

Prepare a strong four-page **archival short paper** for REALM 2026 at EMNLP.

- Working branch: `realm26/archival-short-paper`
- Direct-submission deadline: **2026-08-05, 23:59 AoE (UTC-12)**
- Review format: anonymous ACL 2026 style
- Active manuscript: `paper/realm2026/`
- Predecessor manuscript and gate artifacts: `paper/icaif2026/`

The July 19 deadline discussed in earlier planning belongs to the separate,
non-archival COLM Workshop on Efficient Reasoning. It is not the REALM
deadline.

## Scientific status

Protocol `finance_icaif26_v2` repaired leakage, added dataset-native scoring,
bound model identifiers to requests, recorded tokens/cost/latency, and created
deterministic development/final manifests.

The full development sweep contains 1,250 system-example results: five systems
on 50 examples from each of five datasets. All runs completed without provider
failures. On the three objective primary datasets:

| System | Development macro | USD/example |
| --- | ---: | ---: |
| CoT/PoT | **0.4323** | 0.000819 |
| Static Nexus | 0.4304 | 0.001010 |
| Direct | 0.4138 | 0.000343 |
| Selective Nexus | 0.3675 | 0.001322 |
| ReAct | 0.2993 | 0.001479 |

Only 10 of 200 objective routing examples were ReAct-only successes, versus 42
Static-only successes. The documented fallback escalated 70% of cases and
reduced exact accuracy from 0.395 (always static) to 0.295. The documented
go/no-go criterion failed. A prospectively frozen 75-item replication on
`openai/gpt-4o-mini-2024-07-18` repeated the configured-system ordering:
Static scored 0.3093 versus ReAct's 0.0683, with 19 versus one unique exact
success.

A deterministic trace audit flagged 28 of the original 52 one-sided cases as
scorer-sensitive candidates. This is not human adjudication and does not change
the official scores; it shows that the method-specific answer contracts and
context budgets must be treated as part of the result.

## Locked research constraints

- The 900-example final manifest remains unexecuted and unscored. Identifier
  metadata was used only to enforce replication disjointness.
- Do not run `--partition final` until a new, independently frozen protocol
  explicitly passes its own development gate.
- Do not tune on the existing 250 outcomes and then describe them as evaluation.
- Describe the setting as controlled/evidence-conditioned reasoning, not
  end-to-end retrieval or RAG.
- Keep FinDER secondary unless narrative correctness receives human validation.
- Treat deterministic parser/ranker/builder stages as workflow components, not
  autonomous agents.

## Current paper claim

The defensible short-paper claim is a focused negative result:

> Under controlled evidence, a bounded ReAct expert was rarely complementary
> to a structured one-call workflow; its documented fallback therefore routed
> too broadly, increasing cost and reducing accuracy. A frozen second-family
> replication repeated the configured ordering, while a trace audit exposed
> answer-contract and scorer sensitivity. Agent routers should establish both
> measured complementarity and evaluation-contract fairness before learning
> when to escalate.

The paper must label every reported number as development-only and must not
claim universal agentic failure.

## Completed acceptance work

1. Ran the deterministic ReAct/Static fairness audit and produced a frozen
   author-review queue.
2. Froze and completed a 75-item second-family replication without executing
   the final partition.
3. Added paired bootstrap intervals, complementarity counts, and full
   calls/tokens/cost/latency artifacts.
4. Reframed the ACL draft around the negative result and its evaluation-contract
   qualification.
5. Built a provider-free anonymous artifact with integrity and anonymity checks.

## High-value work remaining

1. Complete true author adjudication of the 51 queued fairness cases; do not use
   the deterministic candidate flags as semantic labels.
2. If budget and time permit, freeze a prompt-harmonized, context-matched rerun
   on fresh development evidence to separate workflow effects from answer
   contract effects.
3. Conduct hostile methodological and clarity reviews, resolve all manuscript
   claims against artifacts, and finish ACL ethics/AI-use/admin fields.
4. Perform final four-page, anonymity, citation, font, and rendered-PDF QA before
   the August 5 submission.

## Key artifacts

- `paper/icaif2026/artifacts/development_summary.json`
- `paper/icaif2026/artifacts/router_training_report.json`
- `paper/realm2026/artifacts/paired_statistics.json`
- `paper/realm2026/artifacts/fairness_audit.json`
- `paper/realm2026/artifacts/second_family_replication_v1.json`
- `paper/realm2026/notes/fairness_audit.md`
- `paper/realm2026/artifact/`
- `paper/icaif2026/main_track_decision.md`
- `progress_notes/icaif_2026_integration_log.md`
- `src/agents/finance/protocols/finance_icaif26_v2.json`
- `src/agents/finance/protocols/manifests/`
- `results/finance/*/finance_icaif26_v2_development_*`

## Validation baseline

The task branches individually reported 104--125 passing finance tests and
successful artifact/PDF checks. Rerun the integrated local finance suite,
analysis validators, artifact validator, and LaTeX/PDF checks before publishing
this branch.
