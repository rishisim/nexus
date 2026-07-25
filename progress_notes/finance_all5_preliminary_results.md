# Finance Nexus All-Five Preliminary Results

Created: 2026-06-16

## Question

Can a finance-dedicated Nexus setup answer finance QA tasks better and at lower cost than ReAct?

## Protocol

- Model: `gemini-2.5-flash`
- Seed: `42`
- Sample size: 10 paired examples per dataset
- Frameworks: `react`, `nexus`
- Cost proxy: answer-generation LLM calls
- Accuracy proxy: finance-aware exact/numeric match heuristic
- Nexus variant: finance-specialized one-call adjudicator with deterministic evidence retrieval over local evidence packets

Important caveat: these are preliminary smoke tests, not final benchmark claims. The scorer is heuristic, samples are small, and ConvFinQA/FinDER need stronger dataset-specific adapters.

## Results

Aggregate artifact:

```text
results/finance/preliminary_all5_summary.json
```

Updated artifact after the first FinDER narrative-prompt iteration:

```text
results/finance/preliminary_all5_summary_v2.json
```

| Dataset | N | ReAct EM | Nexus EM | ReAct calls | Nexus calls | Claim status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| FinanceBench | 10 | 0.80 | 0.90 | 24 | 10 | supported_better_and_cheaper |
| FinDER | 10 | 0.50 | 0.30 | 21 | 10 | not_supported_yet |
| FinQA | 10 | 0.60 | 0.60 | 32 | 10 | not_supported_yet |
| TAT-QA | 10 | 0.90 | 0.90 | 21 | 10 | not_supported_yet |
| ConvFinQA | 10 | 0.10 | 0.20 | 52 | 10 | supported_better_and_cheaper |

Aggregate across all five:

| Framework | Correct | EM | Total calls | Correct per call |
| --- | ---: | ---: | ---: | ---: |
| ReAct | 29 / 50 | 0.58 | 150 | 0.193 |
| Finance Nexus | 29 / 50 | 0.58 | 50 | 0.580 |

## Interpretation

The broad version of the claim is not proven yet: Nexus did not beat ReAct on all five datasets, and aggregate accuracy is tied.

The cost-efficiency direction is promising:

- Nexus used exactly 1 answer call per example on all datasets.
- ReAct used 2.1-5.2 calls/example depending on dataset.
- Aggregate accuracy tied while total calls dropped from 150 to 50.
- On FinanceBench, Nexus was both more accurate and cheaper.
- On TAT-QA and FinQA, Nexus preserved accuracy while reducing calls sharply.

The main weakness is dataset adaptation:

- FinDER has long narrative/explanatory questions where the deterministic Scout often under-retrieves or answers `UNKNOWN`.
- ConvFinQA is a conversational benchmark; the quick adapter preserves context better now, but it still lacks explicit turn-state and prior-answer machinery.

## Recommendation

Invest in this direction, but do it as a staged research bet, not as a finished result.

Recommended next milestone:

1. Improve FinDER Scout/Architect with evidence-aware query expansion and no premature `UNKNOWN`.
2. Add a real ConvFinQA conversational state adapter that exposes prior turns and computed prior answers.
3. Re-run 50 examples each on FinanceBench, FinDER, FinQA, and TAT-QA.
4. Use an LLM judge or dataset-native evaluator for narrative answers, while keeping numeric exact checks for calculation tasks.

Decision:

- **Yes, continue investing** if the goal is cost-efficient finance QA over local retrieved evidence.
- **Do not yet claim a general five-dataset win**.
- Current claim should be: "Initial five-dataset pilot ties aggregate accuracy at one-third answer-call cost, with clear wins on FinanceBench and cost-preserving ties on FinQA/TAT-QA."

## Follow-Up Iteration

After inspecting FinDER misses, the main failure was not retrieval but overly conservative adjudication on narrative/implication questions. A dataset-aware narrative adjudicator prompt was added for FinDER and rerun on the same 10 seed-42 examples.

Updated all-five aggregate using the improved FinDER run:

| Framework | Correct | EM | Total calls | Correct per call |
| --- | ---: | ---: | ---: | ---: |
| ReAct | 28 / 50 | 0.56 | 152 | 0.184211 |
| Finance Nexus | 31 / 50 | 0.62 | 50 | 0.620000 |

Updated per-dataset read:

| Dataset | ReAct EM | Nexus EM | ReAct calls | Nexus calls | Read |
| --- | ---: | ---: | ---: | ---: | --- |
| FinanceBench | 0.80 | 0.90 | 24 | 10 | Nexus wins |
| FinDER | 0.40 | 0.50 | 23 | 10 | Nexus wins after narrative prompt |
| FinQA | 0.60 | 0.60 | 32 | 10 | Tie, Nexus cheaper |
| TAT-QA | 0.90 | 0.90 | 21 | 10 | Tie, Nexus cheaper |
| ConvFinQA | 0.10 | 0.20 | 52 | 10 | Nexus wins, but both weak |

This strengthens the investment case: after one targeted prompt/adjudicator iteration, the pilot shows both higher aggregate accuracy and substantially lower answer-call cost. The result is still preliminary because samples are small and the scoring heuristic is not a substitute for dataset-native evaluation.

## ConvFinQA Chunking Iteration

ConvFinQA misses showed a different failure mode: the relevant values were often present but buried beyond the first truncated evidence chunk. The generic evidence environment now splits long filing contexts into overlapping searchable chunks.

Updated artifact after FinDER narrative prompting plus ConvFinQA chunked retrieval:

```text
results/finance/preliminary_all5_summary_v3.json
```

Updated all-five aggregate:

| Framework | Correct | EM | Total calls | Correct per call |
| --- | ---: | ---: | ---: | ---: |
| ReAct | 32 / 50 | 0.64 | 137 | 0.233577 |
| Finance Nexus | 37 / 50 | 0.74 | 50 | 0.740000 |

Updated per-dataset read:

| Dataset | ReAct EM | Nexus EM | ReAct calls | Nexus calls | Read |
| --- | ---: | ---: | ---: | ---: | --- |
| FinanceBench | 0.80 | 0.90 | 24 | 10 | Nexus wins |
| FinDER | 0.40 | 0.50 | 23 | 10 | Nexus wins after narrative prompt |
| FinQA | 0.60 | 0.60 | 32 | 10 | Tie, Nexus cheaper |
| TAT-QA | 0.90 | 0.90 | 21 | 10 | Tie, Nexus cheaper |
| ConvFinQA | 0.50 | 0.80 | 37 | 10 | Nexus wins after chunked retrieval |

Research conclusion after this iteration: the direction is now strong enough to justify a larger controlled run. The next credible milestone is 50 examples per dataset with frozen prompts/adapters and a separate audit of the finance-aware scorer.

## Frozen 50-Example All-Five Run

Protocol artifact:

```text
src/agents/finance/protocols/all5_50_v1.json
```

Aggregate audit artifact:

```text
results/finance/preliminary_all5_summary_50_v1.json
```

Run setup:

- Model: `gemini-2.5-flash`
- Seed: `42`
- Sample size: 50 paired examples per dataset, 250 total
- Results tag: `all5-50-v1`
- Frameworks: `react`, `nexus`
- Cost proxy: answer-generation LLM calls
- Accuracy proxy: finance-aware exact/numeric match heuristic
- Nexus variant: deterministic evidence retrieval plus one LLM adjudicator call

The scorer audit found that the older numeric tolerance was too loose for ratio answers near zero: wrong-sign small decimals could be marked correct. The numeric tolerance was tightened before publishing the aggregate below, dropping Nexus from 186/250 to 182/250 while leaving ReAct at 165/250.

Corrected aggregate:

| Framework | Correct | EM | Total calls | Correct per call |
| --- | ---: | ---: | ---: | ---: |
| ReAct | 165 / 250 | 0.660 | 609 | 0.270936 |
| Finance Nexus | 182 / 250 | 0.728 | 250 | 0.728000 |

Paired disagreement audit:

| Bucket | Count |
| --- | ---: |
| Both correct | 151 |
| ReAct only correct | 14 |
| Nexus only correct | 31 |
| Both wrong | 54 |

Per-dataset corrected read:

| Dataset | N | ReAct EM | Nexus EM | ReAct calls | Nexus calls | Read |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| FinanceBench | 50 | 0.82 | 0.82 | 126 | 50 | Tie, Nexus cheaper |
| FinDER | 50 | 0.56 | 0.46 | 124 | 50 | ReAct wins accuracy; Nexus cheaper |
| FinQA | 50 | 0.52 | 0.70 | 113 | 50 | Nexus wins |
| TAT-QA | 50 | 0.90 | 0.96 | 101 | 50 | Nexus wins |
| ConvFinQA | 50 | 0.50 | 0.70 | 145 | 50 | Nexus wins |

Interpretation: the larger controlled run supports the aggregate better-and-cheaper claim under the local heuristic: Nexus answers 17 more of 250 examples correctly while using 359 fewer answer-generation calls. The evidence is strongest on numerical/table/conversational finance QA, weaker on FinDER's broad narrative implication questions. FinDER should not be represented as a win yet.

Next research steps:

1. Manually audit the 45 one-sided disagreements, especially FinDER narrative answers and small-ratio numeric cases.
2. Add dataset-native or judge-based scoring for FinDER before making narrative-RAG claims.
3. Add token accounting when the provider wrapper exposes it, so the cost result can move from call-count cost to estimated dollar cost.
4. Consider a dedicated table/conversation adapter for ConvFinQA/TAT-QA, since the current generic chunking already helps but is not task-native.

## Run Directories

```text
results/finance/financebench/seed42_gemini-2.5-flash_all5-prelim/
results/finance/finder/seed42_gemini-2.5-flash_all5-prelim/
results/finance/finqa/seed42_gemini-2.5-flash_all5-prelim/
results/finance/tatqa/seed42_gemini-2.5-flash_all5-prelim/
results/finance/convfinqa/seed42_gemini-2.5-flash_all5-prelim-fixed/
results/finance/financebench/seed42_gemini-2.5-flash_all5-50-v1/
results/finance/finder/seed42_gemini-2.5-flash_all5-50-v1/
results/finance/finqa/seed42_gemini-2.5-flash_all5-50-v1/
results/finance/tatqa/seed42_gemini-2.5-flash_all5-50-v1/
results/finance/convfinqa/seed42_gemini-2.5-flash_all5-50-v1/
```
