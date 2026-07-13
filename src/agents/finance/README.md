# Finance Nexus Lane

This folder is the staging area for finance-focused Nexus experiments. The goal is to test whether the fixed-call Nexus pipeline can answer financial QA tasks more accurately and more cheaply than step-by-step ReAct baselines.

## Research Claim

Working claim:

> On finance QA datasets that require retrieval, evidence selection, and numerical reasoning over filings or financial text, Nexus should improve answer quality at lower inference cost by replacing open-ended iterative ReAct loops with a fixed Scout -> Architect -> Adjudicator workflow.

This is a hypothesis, not yet a result. Treat it as proven only after paired runs on the same sampled examples, model, temperature, and evidence environment.

## Why Finance Fits Nexus

Finance QA is a good test bed because many failures are retrieval and grounding failures, not pure arithmetic failures. The Nexus structure maps cleanly onto that bottleneck:

- Scout: identify companies, filing sections, metrics, reporting periods, and accounting concepts.
- Architect: find missing bridge evidence, such as definitions, prior-year values, segment tables, or filing notes.
- Adjudicator: produce the final answer with evidence-grounded reasoning.

The core Nexus agent currently uses exactly 3 LLM calls per question. ReAct baselines use variable calls as they search, lookup, think, and finish, so every finance run should report both raw accuracy and accuracy per LLM call.

## Candidate Datasets

The primary shortlist is tracked in `datasets.yaml`.

Recommended first-pass order:

1. FinanceBench - best public fit for open-book financial QA and enterprise-style RAG.
2. FinDER - best fit for ambiguous real analyst queries over 10-K filings.
3. FinQA - compact numerical reasoning with structured and unstructured financial-report evidence.
4. TAT-QA - table-plus-text numerical reasoning over real financial reports.
5. ConvFinQA - conversational follow-up questions built from financial numerical reasoning.

Reserve candidate:

- FinTextQA - useful if we want long-form, source-attributed finance answers, but it is less aligned with the current short-answer runner pattern.

## Experiment Gates

Gate A - dataset adapter:

- Load a deterministic sample split.
- Expose `reset(idx)` and `step(action)` with `search[...]`, `lookup[...]`, and `finish[...]`.
- Return gold answer, evidence, and task metadata in `info`.

Gate B - paired baseline:

- Run ReAct and Nexus on the exact same indices.
- Keep model, temperature, context budget, evidence corpus, and retries identical.
- Save `react.json`, `nexus.json`, `summary.json`, `config.json`, and `processed_indices.json` under `results/finance/<dataset>/seed<seed>_<model>/`.

Gate C - cost accounting:

- Report `n_calls` per example for both frameworks.
- If token usage is available from the provider wrapper, also report input tokens, output tokens, and estimated dollar cost.
- Otherwise label cost as call-count cost, not dollar cost.

Gate D - claim discipline:

- Primary metric: answer accuracy or task-native F1/EM.
- Secondary metric: cost-normalized quality, such as correct answers per LLM call.
- Claim "better and cheaper" only if Nexus beats ReAct on both quality and cost on the paired sample.

## Current Files

Current implementation and planning files:

```text
src/agents/finance/
├── README.md
├── datasets.yaml
├── dataset_catalog.py
├── finance_env.py
├── finance_prompts.py
├── finance_utils.py
├── nexus_wrapper.py
├── prompts/
│   └── finance_nexus.json
├── react_agent.py
└── run_finance_experiments.py
```

FinanceBench is the first runnable adapter. The other four primary datasets are cataloged and can be prepared into the same results shape while their adapters are added.

## Frozen Protocols

The current larger all-five protocol is tracked in:

```text
src/agents/finance/protocols/all5_50_v1.json
```

This protocol freezes the v3 adapter/prompt setup for a 50-example-per-dataset paired run. It still treats cost as answer-call cost and accuracy as the local finance-aware heuristic scorer, so results should be framed as controlled preliminary evidence rather than an official benchmark score.

## Commands

Prepare paired-run directories for every primary dataset without making LLM calls:

```bash
nexus_env/bin/python src/agents/finance/run_finance_experiments.py \
  --dataset all \
  --num-examples 25 \
  --prepare-only
```

Run a small paired FinanceBench pilot:

```bash
nexus_env/bin/python src/agents/finance/run_finance_experiments.py \
  --dataset financebench \
  --frameworks react nexus \
  --num-examples 5 \
  --seed 42
```

Run an isolated 25-example finance-specialized Nexus pilot:

```bash
nexus_env/bin/python src/agents/finance/run_finance_experiments.py \
  --dataset financebench \
  --frameworks react nexus \
  --num-examples 25 \
  --seed 42 \
  --results-tag finance-nexus-v1
```

Refresh the summary and better/cheaper claim status from existing result files:

```bash
nexus_env/bin/python src/agents/finance/run_finance_experiments.py \
  --dataset financebench \
  --summarize-only
```

Audit and aggregate the frozen all-five 50-example run:

```bash
nexus_env/bin/python src/agents/finance/audit_finance_results.py \
  --results-tag all5-50-v1
```
