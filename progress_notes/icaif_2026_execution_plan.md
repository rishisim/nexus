# ICAIF 2026 Main-Track Execution Plan

Created: 2026-07-09  
Submission deadline: 2026-08-02, 23:59 AOE  
Internal research-complete deadline: 2026-07-15  
Target: ACM ICAIF 2026 main conference

## Submission Constraints

- Eight pages total in ACM `sigconf` format, including figures and references.
- No supplementary material or appendices.
- Double-blind submission; author-identifying repository links and prose must be removed.
- No rebuttal period, so the submitted paper must answer likely validity objections directly.
- At least one author must be able to present in person in Milan if accepted.

## Paper Decision

### Working title

**When Should Financial QA Be Agentic? Selective Orchestration for Accuracy-Cost Efficient Financial Reasoning**

### Core claim

A deterministic-first financial QA workflow with calibrated escalation can match or improve the quality of uniformly iterative agents while using fewer model tokens, dollars, and wall-clock time.

### Scope

The main evaluation isolates the reasoning and orchestration layer under controlled evidence access. It does not make an end-to-end RAG claim. FinanceBench evidence and FinDER references are treated as oracle evidence, and this setting is stated explicitly. A full-corpus retrieval experiment is a stretch validation, not a prerequisite for the core paper.

### Research questions

1. Does deterministic-first orchestration improve the quality-cost frontier over direct prompting and ReAct?
2. Which financial question types benefit from iterative agency, and which are harmed by unnecessary reasoning?
3. Can a frozen risk gate selectively escalate difficult cases without recreating ReAct's cost?
4. Are the findings stable across datasets, model families, and official scoring protocols?

### Intended contributions

1. A hybrid deterministic-agentic workflow for financial QA with selective escalation.
2. A leakage-audited, held-out evaluation spanning numerical, tabular, conversational, and narrative financial QA.
3. A provider-level efficiency analysis using tokens, dollars, latency, and retrieval/tool operations.
4. A manually validated failure taxonomy explaining when additional agency helps.

## Non-Negotiable Validity Repairs

- [ ] Mark all existing 250-example runs as development evidence only.
- [ ] Create fresh final-evaluation IDs that exclude every preliminary and 50-example pilot ID.
- [ ] Remove TAT-QA gold `derivation` and `scale` from model-visible evidence.
- [ ] Remove FinanceBench `justification` from model-visible evidence.
- [ ] Prevent answers, reasoning programs, answer types, or other target-derived fields from entering prompts.
- [ ] Add automated prompt/evidence leakage tests for every dataset adapter.
- [ ] Use dataset-native scorers for numerical/table/conversational datasets.
- [ ] Freeze a narrative-scoring rubric for FinDER and validate it against blinded human labels.
- [ ] Freeze prompts, thresholds, IDs, dataset revisions, model versions, and scorer versions before final runs.
- [ ] Never tune prompts, routing thresholds, or scoring rules after examining final-test outputs.

## Method to Implement

### Static structured workflow

1. Parse entities, periods, metrics, units, and requested answer type from the question.
2. Select and deduplicate relevant evidence deterministically.
3. Assemble a compact evidence dossier.
4. Use one LLM adjudication call.
5. Apply deterministic answer-format, unit, sign, and arithmetic checks.

### Selective escalation

The first-pass workflow emits a risk score from development-frozen signals:

- missing entity/period/metric coverage;
- weak retrieval-score margin or conflicting evidence;
- narrative or implication-seeking language;
- answer/evidence numeric inconsistency;
- missing requested unit, sign, or percentage scale;
- `UNKNOWN`, malformed, or unsupported answer.

Cases above a frozen threshold escalate to an iterative retrieval/reasoning pass. Report the full accuracy-cost curve across thresholds, plus the selected operating point and an oracle-routing upper bound.

## Evaluation Matrix

### Final examples

- FinanceBench: every public example not used during development, expected 140.
- FinDER: 200 fresh, stratified held-out examples.
- FinQA: 200 fresh validation examples.
- TAT-QA: 200 fresh validation examples after leakage removal.
- ConvFinQA: 200 fresh validation examples, grouped to avoid dialogue leakage.
- Primary total: approximately 940 untouched examples.

If API budget and runtime permit, extend FinQA, TAT-QA, and ConvFinQA to their complete official evaluation splits.

### Systems

1. Direct one-call evidence-conditioned answer.
2. One-call structured/CoT reader at the same output budget.
3. ReAct with the same evidence and tools.
4. Static one-call Finance Nexus.
5. Selective Finance Nexus.
6. Oracle router for headroom analysis, not as a deployable baseline.

### Models

- Primary economical instruction model: full evaluation.
- Second independent model family: at least 50 fresh examples per dataset; expand if results disagree.
- Record exact provider model identifiers and evaluation dates.

### Quality metrics

- Dataset-native exact match or execution accuracy.
- Narrative correctness under the frozen FinDER rubric.
- Macro-average across datasets, alongside every per-dataset result.
- Paired bootstrap 95% confidence intervals.
- Exact McNemar tests for paired correctness, with multiplicity-aware interpretation.
- Human agreement and judge-vs-human confusion matrix for narrative answers.

### Efficiency metrics

- Input, cached, reasoning, and output tokens.
- Model calls and retrieval/tool calls.
- Per-example dollar cost using a dated pricing manifest.
- Median and P95 end-to-end latency.
- Accuracy at equal cost and cost at equal accuracy.
- Pareto-frontier plots over routing thresholds.

## Failure Analysis

Blindly annotate all one-sided disagreements and a stratified sample of both-wrong cases:

1. evidence selection or truncation;
2. arithmetic/program execution;
3. unit, scale, percentage, or sign;
4. entity or period mismatch;
5. conversational-state failure;
6. narrative inference or ambiguity;
7. unsupported/hallucinated answer;
8. formatting or nontermination;
9. scorer false positive or false negative.

Use at least two annotators for the narrative and scorer-sensitive subset, resolve disagreements, and report agreement.

## Seven-Day Schedule

### Thursday, July 9 — lock the paper and protocol

- [ ] Create the anonymous ACM manuscript scaffold and bibliography.
- [ ] Write the title, abstract skeleton, research questions, contributions, and eight-page outline.
- [ ] Create protocol v2 with disjoint development/final IDs.
- [ ] Specify the exact evaluation matrix and API budget.
- [ ] Convert the current findings into clearly labeled development evidence.
- [ ] Draft related-work rows for financial QA, agentic QA, selective reasoning, and efficiency evaluation.

Exit criterion: a reviewer-readable paper skeleton and an immutable final-evaluation manifest.

### Friday, July 10 — repair validity and instrumentation

- [ ] Remove leaked metadata and add leakage tests.
- [ ] Integrate official/native scorers.
- [ ] Capture token usage, price, latency, model ID, and request metadata.
- [ ] Add deterministic answer validation and unit/sign handling tests.
- [ ] Run a small development smoke test across all datasets and systems.

Exit criterion: no known leakage and complete cost records for every call.

### Saturday, July 11 — build and freeze selective escalation

- [ ] Implement risk features and the escalation path.
- [ ] Tune thresholds using development examples only.
- [ ] Produce development accuracy-cost curves.
- [ ] Freeze all prompts, thresholds, and code used for final evaluation.
- [ ] Write the method and experimental-protocol sections.

Exit criterion: one frozen selective operating point plus a threshold sweep specification.

### Sunday, July 12 — run the primary final evaluation

- [ ] Execute all primary-model systems on the untouched evaluation manifest.
- [ ] Monitor failures without changing prompts, thresholds, or scoring.
- [ ] Re-run only documented infrastructure/API failures.
- [ ] Generate the first native-score and cost tables.

Exit criterion: complete primary-model result files with no research-logic reruns.

### Monday, July 13 — replicate and ablate

- [ ] Run the second model family replication.
- [ ] Run component ablations: no structured selection, no answer validator, and no escalation.
- [ ] Compute oracle-router headroom and routing calibration.
- [ ] Draft the main results section.

Exit criterion: evidence that the result is architectural rather than one prompt/model artifact.

### Tuesday, July 14 — statistics and manual audit

- [ ] Compute paired tests and confidence intervals.
- [ ] Complete blinded disagreement annotation.
- [ ] Validate the FinDER scorer against human labels.
- [ ] Generate the final accuracy-cost frontier and failure-analysis figure.
- [ ] Draft limitations and threats to validity.

Exit criterion: every headline claim traceable to a frozen artifact and uncertainty estimate.

### Wednesday, July 15 — complete submission-ready draft v1

- [ ] Finish all eight pages, including references and figures.
- [ ] Remove author-identifying text and metadata.
- [ ] Compile and visually inspect the PDF.
- [ ] Run an internal reviewer checklist for novelty, validity, clarity, reproducibility, and finance relevance.
- [ ] Make the main-vs-workshop decision from the evidence gates below.

Exit criterion: anonymous, compliant, readable PDF and reproducibility bundle.

## Main-Track Evidence Gate

Proceed with the main-track paper when all are true:

- no known leakage or development/final overlap;
- approximately 940 or more untouched examples;
- native metrics plus human-validated FinDER scoring;
- real token, dollar, and latency accounting;
- direct, ReAct, static Nexus, and selective Nexus comparisons;
- selective Nexus is Pareto-competitive: statistically supported quality improvement, or quality within one percentage point of the best system with at least 30% lower dollar cost;
- no unexplained large regression on FinDER or another task family;
- at least one second-model replication and meaningful ablations;
- every claim and caveat fits within the self-contained eight-page paper.

If these conditions are not met, retain the work as a workshop submission focused on early evidence and protocol lessons rather than overstating a universal win.

## Eight-Page Allocation

| Section | Approximate pages |
| --- | ---: |
| Abstract and introduction | 0.9 |
| Related work | 0.5 |
| Method | 1.3 |
| Experimental protocol | 1.2 |
| Main results | 1.4 |
| Routing and failure analysis | 0.8 |
| Limitations and conclusion | 0.4 |
| References | 1.5 |

Prefer one method diagram, one main results table, one accuracy-cost figure, and one compact failure/routing table. Put secondary numeric results in a compact in-paper table because supplementary material is prohibited.

## Buffer Before Submission

Use July 16 through August 1 for independent review, larger replications, prose compression, citation verification, anonymization checks, and CMT submission rehearsal. Do not spend this buffer changing the final protocol after seeing results.
