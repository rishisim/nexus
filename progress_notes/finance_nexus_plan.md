# Finance Nexus Plan

Created: 2026-06-16

## Goal

Create a finance-dedicated Nexus lane that can test whether Nexus answers financial QA tasks better and at lower cost than ReAct.

The planned claim is deliberately gated: Nexus is "better and cheaper" only if paired runs show both higher task quality and lower mean LLM calls or token cost on the same examples.

## Dataset Shortlist

Primary five:

| Dataset | Why it belongs | First-pass use |
| --- | --- | --- |
| FinanceBench | Open-book QA over public companies with answer evidence. | Start here for an enterprise-style RAG benchmark. |
| FinDER | Expert query-evidence-answer triplets over 10-K filings with ambiguous analyst queries. | Use to stress retrieval and bridge-query planning. |
| FinQA | Expert-written financial report QA with structured and unstructured evidence plus gold reasoning programs. | Use for numerical reasoning and program-based error analysis. |
| TAT-QA | Table-plus-text financial report QA with diverse answer forms and numerical reasoning. | Use after table lookup support is stable. |
| ConvFinQA | Conversational financial numerical QA built from FinQA-style reasoning paths. | Use to test follow-up context and multi-turn state. |

Reserve:

| Dataset | Why reserve it |
| --- | --- |
| FinTextQA | Strong long-form finance QA dataset, but it needs source-attributed long-form evaluation rather than the current short-answer runner pattern. |

## Evaluation Design

For each dataset:

1. Build an adapter with `reset(idx)` and `step(action)`.
2. Run ReAct and Nexus on identical sampled indices.
3. Save outputs under `results/finance/<dataset>/seed<seed>_<model>/`.
4. Measure task quality and cost.
5. Report paired deltas, not independent aggregate runs.

Required summary fields:

```json
{
  "dataset": "financebench",
  "model": "gemini-2.5-flash",
  "seed": 42,
  "num_examples": 25,
  "react_accuracy": null,
  "nexus_accuracy": null,
  "react_mean_calls": null,
  "nexus_mean_calls": 3.0,
  "react_correct_per_call": null,
  "nexus_correct_per_call": null,
  "claim_status": "not_run"
}
```

## Implementation Notes

- Keep this lane under `src/agents/finance/`.
- Do not fork or modify existing dataset-specific agents until the first finance adapter is chosen.
- Prefer FinanceBench or FinDER first because they are the most direct tests of financial RAG.
- Add table-specific support before running TAT-QA broadly.
- Keep numerical answer normalization explicit for all finance datasets.

## Current Pilot Evidence

2026-06-16 FinanceBench smoke run with the generic 3-call Nexus core:

```bash
nexus_env/bin/python src/agents/finance/run_finance_experiments.py \
  --dataset financebench \
  --frameworks react nexus \
  --num-examples 1 \
  --seed 42
```

Result location:

```text
results/finance/financebench/seed42_gemini-2.5-flash/
```

After extending the same run to 25 paired examples and rescoring with the finance heuristic:

| Framework | Valid examples | EM | Mean answer calls | Correct per answer call |
| --- | ---: | ---: | ---: | ---: |
| ReAct | 25 | 0.80 | 2.44 | 0.327869 |
| Generic Nexus core | 25 | 0.88 | 3.00 | 0.293333 |

Claim status: `not_supported_yet`.

This showed a quality gain but not a cost gain. It is useful as a baseline against the unmodified shared Nexus agent.

2026-06-16 FinanceBench 25-example pilot with the finance-specialized Nexus mode:

```bash
nexus_env/bin/python src/agents/finance/run_finance_experiments.py \
  --dataset financebench \
  --frameworks react nexus \
  --num-examples 25 \
  --seed 42 \
  --results-tag finance-nexus-v1
```

Result location:

```text
results/finance/financebench/seed42_gemini-2.5-flash_finance-nexus-v1/
```

Pilot result:

| Framework | Valid examples | EM | Mean answer calls | Correct per answer call |
| --- | ---: | ---: | ---: | ---: |
| ReAct | 25 | 0.84 | 2.44 | 0.344262 |
| Finance-specialized Nexus | 25 | 0.92 | 1.00 | 0.920000 |

Claim status: `supported_better_and_cheaper`.

This supports the claim only for the current 25-example FinanceBench pilot, the current finance heuristic scorer, and answer-call accounting. It should not yet be phrased as a general finance result. The next step is to repeat on more FinanceBench examples or add FinDER as the second finance RAG benchmark.

## Sources Checked

- FinanceBench: https://github.com/patronus-ai/financebench
- FinDER: https://huggingface.co/datasets/Linq-AI-Research/FinDER
- FinQA: https://finqasite.github.io/
- TAT-QA: https://nextplusplus.github.io/TAT-QA/
- ConvFinQA: https://github.com/czyssrs/ConvFinQA
- FinTextQA: https://aclanthology.org/2024.acl-long.328/

## All-Five Preliminary

See `progress_notes/finance_all5_preliminary_results.md` for the first five-dataset pilot.
