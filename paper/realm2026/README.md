# REALM 2026 archival short paper

## Locked venue target

- Venue: [REALM 2026 at EMNLP](https://realm-workshop.github.io/)
- Track: archival short paper (ACL Anthology proceedings)
- Direct deadline: **August 5, 2026, 23:59 AoE (UTC-12)**
- Review length: four pages of content, plus unlimited references and appendix
- Camera-ready allowance: five pages of content
- Format: official ACL 2026 style, anonymous and double blind
- Workshop: October 29, 2026, hybrid

The July 19 deadline is for the separate non-archival COLM Workshop on Efficient
Reasoning, not REALM.

## Working title and thesis

**When Agentic Reasoning Fails to Pay Off: A Preregistered Negative Result in
Financial Question Answering**

The paper should argue one precise point: a router cannot recover useful
accuracy-cost trade-offs when its expensive expert has little complementary
accuracy. Under controlled evidence, bounded ReAct produced only 10 unique
successes among 200 objective routing examples, while Static Nexus produced 42;
the preregistered fallback therefore escalated too broadly and hurt both quality
and cost.

## Current evidence boundary

- Reported results are development-only (250 examples; five systems).
- The 900-example final manifest is unopened and remains sealed.
- FinanceBench and FinDER do not enter the three-dataset primary macro.
- FinDER has no human-validated objective score and remains secondary.
- The experiment isolates orchestration over controlled evidence; it makes no
  end-to-end retrieval claim.

## Acceptance-focused work plan

### Must complete

1. Reframe every section around the negative result and the complementarity
   precondition; remove proposal-style language that implies the selector works.
2. Audit baseline fairness and explain why bounded ReAct underperforms rather
   than leaving reviewers to infer an implementation defect.
3. Classify the 52 one-sided Static/ReAct disagreements and a frozen sample of
   both-wrong cases using a reproducible failure taxonomy.
4. Report paired effect sizes/uncertainty and full calls, tokens, cost, median
   latency, and P95 latency.
5. Fit all essential method, evidence, and analysis into four ACL content pages;
   keep Limitations after the conclusion and before references.
6. Provide an anonymous reproducibility bundle with exact prompts, manifests,
   scorer versions, model snapshots, and trace hashes.

### Highest-value addition

Freeze a small cross-family replication outside the sealed 900-example manifest.
The replication should test the qualitative ordering of one-call reasoning and
bounded ReAct, not retune the failed selector. Its sample, metrics, and stopping
rule must be fixed before any calls are made.

### Internal schedule

- July 14-15: repository cleanup, story lock, ACL scaffold, protocol for any
  replication.
- July 16-20: fairness audit, failure taxonomy, and cross-model replication.
- July 21-24: paired analysis, tables, and first complete four-page draft.
- July 25-29: hostile methodological reviews and rewrite.
- July 30-August 2: anonymous artifact, citation/ethics checks, visual QA.
- August 3: internal content freeze.
- August 4: submit with one-day buffer before the August 5 AoE deadline.

## Build

The vendored `acl.sty` and `acl_natbib.bst` come from the official
`acl-org/acl-style-files` repository at commit
`d5adc823ff0f80f98c80405ca0ab66c68e684409`; only trailing whitespace in the
bibliography style was normalized.

From this directory:

```bash
latexmk -pdf -output-directory=build main.tex
```

Before submission, verify four content pages, A4 paper size, embedded fonts,
anonymity, readable grayscale figures, and absence of links to deanonymizing
resources.

Current scaffold status: the PDF compiles as five physical pages. The research
content and conclusion end on page 3; Limitations and references occupy pages
4-5 and do not count toward REALM's four-page content allowance. The unused
fourth content page is reserved for the fairness audit, failure taxonomy, and
cross-model evidence rather than additional method exposition.
