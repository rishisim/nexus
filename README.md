# Nexus

Nexus is a research codebase for comparing fixed-call, deterministic-first,
and iterative language-model workflows on evidence-grounded question answering.
It includes agents and experiment runners for financial QA, fact verification,
and multi-hop QA.

## Current research focus

The active study asks when iterative agentic reasoning is worth its accuracy,
token, latency, and dollar cost in controlled-evidence financial QA. It compares
Direct, CoT/PoT, Static Nexus, bounded ReAct, and a pre-generation selector on
FinanceBench, FinDER, FinQA, TAT-QA, and ConvFinQA.

The repaired 250-example development gate produced a negative result: CoT/PoT
formed the strongest observed quality-cost point, while ReAct and Selective
Nexus were dominated. The prespecified gate therefore stopped the study before
the disjoint 900-example final manifest was opened. These are development-only
findings, not confirmatory benchmark claims.

The active publication target is a four-page archival short paper at
[REALM 2026](https://realm-workshop.github.io/call_for_papers/). Paper status and
the submission plan live in [`paper/realm2026/`](paper/realm2026/).

## Repository map

```text
src/agents/finance/   Finance environments, methods, protocols, and runner
src/agents/nexus/     Shared Nexus agent implementation
src/shared/           Provider wrappers and telemetry
tests/finance/        Finance validity, scoring, protocol, and runner tests
results/finance/      Versioned development and smoke-run artifacts
paper/realm2026/      Active ACL-formatted REALM short-paper draft
paper/icaif2026/      Preserved predecessor draft and decision artifacts
progress_notes/       Research decisions and experiment logs
scripts/              Analysis, download, debug, and cleanup utilities
```

## Setup

Use a local virtual environment; environments and secrets are intentionally not
tracked.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Copy required provider credentials into an untracked `.env` file. See
[`SETUP.md`](SETUP.md) for dataset-specific setup.

## Validation

Run the finance research-validity suite before changing a protocol or paper
claim:

```bash
python -m pytest tests/finance -q
```

The final partition is deliberately sealed. Do not bypass the final-freeze
checks or modify research logic based on final-manifest outcomes. See
[`src/agents/finance/README.md`](src/agents/finance/README.md) for experiment
interfaces and [`PROJECT_STATE.md`](PROJECT_STATE.md) for the current handoff.

## Research lineage

This repository began from the public ReAct prompting implementation associated
with Yao et al. (ICLR 2023) and has since been extended with Nexus workflows,
additional datasets, telemetry, native scoring, and reproducible finance
protocols. See [`LICENSE`](LICENSE) for licensing information.
