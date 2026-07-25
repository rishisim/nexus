# Finance QA Research Lane

This package implements the controlled-evidence financial QA study used by the
REALM 2026 short-paper project.

## Systems

- `direct`: one evidence search and one concise answer call.
- `cot`: the same single-search dossier with explicit calculation/reasoning.
- `nexus`: deterministic multi-query evidence assembly plus one adjudication
  call (Static Nexus).
- `react`: bounded iterative search/lookup/finish, up to seven model steps.
- `selective`: a deterministic pre-generation gate chooses Static Nexus or
  ReAct.

All systems use the same controlled evidence corpus and shared retrieval
implementation. This isolates orchestration; it is not an end-to-end RAG test.

## Protocol status

`protocols/finance_icaif26_v2.json` defines the repaired protocol and references
deterministic manifests for FinanceBench, FinDER, FinQA, TAT-QA, and ConvFinQA.
The 250-example development partition has been run. Its go/no-go gate failed,
and the 900-example final partition remains unexecuted and unscored. Identifier
metadata was used only to keep a separate 75-item replication disjoint.

`protocols/realm26_second_family_v1.json` defines that prospectively frozen
replication on `openai/gpt-4o-mini-2024-07-18`. All 150 Static/ReAct rows
completed. Static scored 0.3093 versus ReAct's 0.0683 on the frozen primary
macro; these remain development observations, not final-partition estimates.

Do not bypass the protocol's final-freeze refusal. Any redesigned study needs a
new protocol version, a new independent development pool, and a frozen gate
before final evaluation.

## Main interfaces

```text
finance_env.py                  Leakage-safe controlled-evidence adapters
finance_methods.py              Direct, CoT/PoT, Static, ReAct, Selective
finance_scoring.py              Dataset-native and strict scorers
finance_statistics.py           Paired intervals and tests
analyze_realm_statistics.py     Original paired and efficiency artifacts
audit_realm_fairness.py         Deterministic trace audit and review queue
realm26_replication_protocol.py Frozen replication manifest/protocol checks
run_realm26_replication.py      Provider-bound replication runner
analyze_realm26_replication_v1_1.py  Frozen replication analysis
protocol_v2.py                  Manifests, fingerprints, and freeze checks
run_finance_experiments.py      Resumable multi-framework runner
selective_router.py             Pre-generation features and frozen router
analyze_finance_development.py  Gate analysis and paper artifacts
```

## Validation

From the repository root:

```bash
python -m pytest tests/finance -q
```

The suite covers leakage controls, native scoring, manifest disjointness and
determinism, model binding, telemetry, resume behavior, and router features.

## Development artifacts

- Results: `results/finance/<dataset>/finance_icaif26_v2_development_*`
- Summary: `paper/icaif2026/artifacts/development_summary.json`
- Router report: `paper/icaif2026/artifacts/router_training_report.json`
- Decision log: `paper/icaif2026/main_track_decision.md`
- Paired analysis: `paper/realm2026/artifacts/paired_statistics.json`
- Fairness audit: `paper/realm2026/artifacts/fairness_audit.json`
- Replication: `paper/realm2026/artifacts/second_family_replication_v1.json`

The results are method-selection/development observations. They must not be
reported as held-out or confirmatory estimates.
