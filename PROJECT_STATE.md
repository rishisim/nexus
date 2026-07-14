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
Static-only successes. The preregistered fallback escalated 70% of cases and
reduced exact accuracy from 0.395 (always static) to 0.295. The locked go/no-go
criterion failed.

## Locked research constraints

- The 900-example final manifest remains unopened.
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
> to a structured one-call workflow; a preregistered selector therefore routed
> too broadly, increasing cost and reducing accuracy. Agent routers should
> establish expert complementarity before learning when to escalate.

The paper must label every reported number as development-only and must not
claim universal agentic failure.

## High-value work remaining

1. Audit ReAct fairness and manually classify the 52 one-sided Static/ReAct
   disagreements plus a fixed sample of both-wrong cases.
2. Freeze and run a small cross-model replication that does not consume the
   sealed 900-example manifest.
3. Add paired uncertainty/effect-size analysis and a full calls/tokens/latency
   table.
4. Compress and rewrite the ACL draft around the negative result, not the failed
   selector proposal.
5. Produce an anonymous reproducibility bundle and complete ACL ethics,
   limitations, AI-use, and PDF-format checks.

## Key artifacts

- `paper/icaif2026/artifacts/development_summary.json`
- `paper/icaif2026/artifacts/router_training_report.json`
- `paper/icaif2026/main_track_decision.md`
- `progress_notes/icaif_2026_integration_log.md`
- `src/agents/finance/protocols/finance_icaif26_v2.json`
- `src/agents/finance/protocols/manifests/`
- `results/finance/*/finance_icaif26_v2_development_*`

## Validation baseline

The previous integration handoff reported 96 passing finance tests and successful
Gemini and OpenAI model-binding smoke checks. Rerun the local finance suite after
repository cleanup and before publishing this branch.
