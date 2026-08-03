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
site currently lists August 5 for direct submissions. The live OpenReview venue
configuration expresses the same deadline as August 6, 2026 at 11:59 UTC,
which is August 5 at 23:59 Anywhere on Earth (UTC-12).

## Official requirement verification

Checked 2026-07-20 against primary sources:

- [REALM 2026 call for papers](https://realm-workshop.github.io/call_for_papers/):
  archival short papers are original unpublished focused contributions, may
  include negative results, have up to four pages of content plus unlimited
  references and appendix, must use ACL 2026 style, be PDF, anonymous, and not
  be under review elsewhere during the REALM review period. It also states the
  direct deadline as August 5, 2026 at 23:59 AoE, asks authors to attest to
  ethics, and asks each submission to nominate one author as a reviewer.
- [REALM OpenReview venue](https://openreview.net/group?id=EMNLP%2F2026%2FWorkshop%2FREALM)
  and its [live submission invitation schema](https://api2.openreview.net/invitations?id=EMNLP%2F2026%2FWorkshop%2FREALM%2F-%2FSubmission):
  the direct form currently requires title, author profiles, comma-separated
  keywords, abstract, PDF, an Archival/Non-archival choice, and at least one
  nominated reviewer; it also exposes an optional cross-submission field.
  The schema records the OpenReview note license as CC BY 4.0.
- [ACL paper formatting guidelines](https://acl-org.github.io/ACLPUB/formatting.html):
  review short papers have at most four content pages plus unlimited references,
  must use A4 PDF with embedded fonts, abstracts are at most 200 words, metadata
  should be plain Unicode, and Limitations must follow the conclusion and
  precede references without a page break.

The paste-ready values and the fields that require author decisions are in
[`submission_packet.md`](submission_packet.md). The executable release gate is
in [`notes/release_checklist.md`](notes/release_checklist.md).

## Working title and thesis

**Capability Is Not Complementarity: A Routing Feasibility Study in Financial
Question Answering**

The paper argues one precise point: model capability and expert complementarity
are different prerequisites. In the prospectively frozen three-tier main study,
Static significantly beat ReAct for control and Luna, while Terra reached
parity and produced a positive cross-tier interaction. Yet ReAct supplied only
two, one, and two unique exact successes among 150 items. Native-quality
oracle-headroom point estimates are 1.0--1.7 points (95% upper limits at most
3.8), while exact-match estimates are at most 1.3 points (upper limits below
4.8). A post-hoc same-manifest, different-seed check retains low headroom. The
harmonized-v2 comparison and original selector study remain supporting and
pilot evidence.

## Current evidence boundary

- Reported results are development-only: the 150-item, three-tier capability
  ladder; the original 250-example, five-system study; a separate 75-item
  replication; and a 150-item harmonized v2.
- The protected final manifest is unexecuted and unscored. Identifier metadata
  was used only to enforce disjointness.
- The successful capability freeze completed all 900 paired episodes after two
  earlier public freezes stopped on action-transport failures. No partial
  outcomes from the stopped freezes were analyzed, and their touched items were
  excluded from each replacement manifest.
- A post-hoc stability check reused exactly those development items and changed
  only the request seed. It completed all 900 episodes and is reported
  side-by-side rather than pooled or described as a fresh-sample replication.
- Temperature and top-p were omitted in both runs, so provider defaults applied
  and deterministic generation is not claimed.
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

1. Reframed the paper around the distinction between capability and
   complementarity.
2. Audited baseline fairness and created a reproducible, frozen review queue.
3. Reported paired uncertainty, complementarity, and efficiency statistics.
4. Prospectively froze and completed the second-family replication.
5. Added the essential evidence to the four-page ACL manuscript.
6. Built an anonymous, provider-free reproducibility and integrity bundle.
7. Preserved a failed harmonized-v1 manipulation check as a diagnostic, then
   prospectively froze and completed a fresh-sample v2 with verified ReAct
   treatment delivery.
8. Prospectively froze and completed the mandatory GPT-4o-mini/Luna/Terra
   capability ladder under a shared strict function-tool contract.
9. Completed a same-manifest different-seed stability check, added exact and
   native-quality headroom intervals, and made them offline-recomputable in the
   anonymous artifact.

### Highest-value remaining work

The scientific manuscript and anonymous artifact are integrated. Keep author
adjudication explicitly secondary and unresolved, avoid retuning on current
outcomes, and complete only the submission/admin checklist and final OpenReview
upload review.

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

The source includes `realm-lineno-compat.sty`, a version-gated workaround for
the two-column ruler regression in `lineno` v5.7 shipped by current TeX Live
2026. It is a no-op with `lineno` v5.8 and later and leaves the official ACL
style file unchanged.

Before submission, verify four content pages, A4 paper size, embedded fonts,
anonymity, readable grayscale figures, and absence of links to deanonymizing
resources.

Integrated status: the PDF is five physical A4 pages, with the research content
and Limitations ending on content page 4. References begin on page 5. Recheck
these boundaries after every substantive edit.
