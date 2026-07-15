# REALM 2026 archival short paper

## Locked venue target

- Venue: [REALM 2026 at EMNLP](https://realm-workshop.github.io/)
- Track: archival short paper (ACL Anthology proceedings)
- Direct deadline: **August 5, 2026, 23:59 AoE (UTC-12)**
- Review length: four pages of content, plus unlimited references and appendix
- Camera-ready allowance: five pages of content
- Format: official ACL 2026 style, anonymous and double blind
- Workshop: October 29, 2026, hybrid

The July 19 date discussed earlier is not the REALM deadline. The official REALM
site currently lists August 5 for direct submissions.

## Working title and thesis

**When Agentic Reasoning Fails to Pay Off: A Negative Result on Selective
Routing in Financial Question Answering**

The paper should argue one precise point: a router cannot recover useful
accuracy-cost trade-offs when its expensive expert has little measured
complementary accuracy. Under controlled evidence, bounded ReAct produced only
10 unique official successes among 200 objective routing examples, while Static
Nexus produced 42; the documented fallback therefore escalated too broadly and
hurt both quality and cost. A frozen second-family replication repeated the
configured ordering, while a trace audit exposed answer-contract and scorer
sensitivity that qualifies the official complementarity counts.

## Current evidence boundary

- Reported results are development-only: the original 250-example, five-system
  study and a separate 75-item, two-system replication.
- The 900-example final manifest is unexecuted and unscored. Identifier metadata
  was used only to enforce disjointness.
- FinanceBench and FinDER do not enter the three-dataset primary macro.
- FinDER has no human-validated objective score and remains secondary.
- The experiment isolates orchestration over controlled evidence; it makes no
  end-to-end retrieval claim.
- Use `documented`, `recorded`, or `protocol-defined` for the original study,
  not `prespecified`, `locked`, or `preregistered`. Its first public Git commit
  contains both protocol and results, so it does not establish a verifiable
  pre-result freeze. The second-family replication may be called
  `prospectively frozen` because its protocol commit predates provider calls.

## Acceptance-focused work plan

### Completed

1. Reframed the paper around the negative result and complementarity
   precondition.
2. Audited baseline fairness and created a reproducible, frozen review queue.
3. Reported paired uncertainty, complementarity, and efficiency statistics.
4. Prospectively froze and completed the second-family replication.
5. Added the essential evidence to the four-page ACL manuscript.
6. Built an anonymous, provider-free reproducibility and integrity bundle.

### Highest-value remaining work

Complete human author adjudication of the 51 frozen fairness cases. If time and
budget permit, separately freeze a prompt-harmonized and context-matched rerun
on fresh development evidence; do not retune on the current outcomes.

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

Integrated status: the PDF is five physical A4 pages, with the research content
and conclusion ending on content page 4. Limitations begin on page 4 after the
conclusion, and references continue through page 5. Recheck these boundaries
after every substantive edit.
