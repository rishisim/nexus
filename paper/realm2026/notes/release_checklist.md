# REALM 2026 archival short paper release checklist

Status date: **2026-08-03**

Target: **REALM @ EMNLP 2026, direct archival short-paper submission**

Hard deadline: **2026-08-05, 23:59 Anywhere on Earth (UTC-12)**

Use the labels below when closing items:

- **[VERIFIED]** is required by a cited primary source or by a repository
  invariant and has been checked locally or against the live venue schema.
- **[RECOMMENDED]** is a prudent quality or timing buffer, not a stated venue
  requirement.
- **[USER ONLY]** cannot be inferred from this repository and must be confirmed
  by the submitting author(s).

## Source-verified venue requirements

- [x] **[VERIFIED]** The target is REALM @ EMNLP 2026, direct submission, archival
  short paper. The [REALM CFP](https://realm-workshop.github.io/call_for_papers/)
  says archival short papers are original unpublished focused contributions,
  including negative results, with up to four pages of content plus unlimited
  references and appendix.
- [x] **[VERIFIED]** The same CFP requires ACL 2026 style, PDF, anonymous
  authors/affiliations, no concurrent review elsewhere for archival papers,
  an ethics attestation, and one nominated author reviewer.
- [x] **[VERIFIED]** The CFP gives the direct deadline as August 5, 2026 at
  23:59 AoE and says all deadlines use UTC-12. The live
  [OpenReview venue](https://openreview.net/group?id=EMNLP%2F2026%2FWorkshop%2FREALM)
  represents it as August 6, 2026 at 11:59 UTC.
- [x] **[VERIFIED]** The live
  [OpenReview submission schema](https://api2.openreview.net/invitations?id=EMNLP%2F2026%2FWorkshop%2FREALM%2F-%2FSubmission)
  requires title, author profiles, keywords, abstract, PDF, Archival or
  Non-archival choice, and a reviewer nomination; it exposes optional
  cross-submission text and records CC BY 4.0 for the note.
- [x] **[VERIFIED]** [ACL formatting guidance](https://acl-org.github.io/ACLPUB/formatting.html)
  requires A4 PDF with embedded fonts, a maximum of four content pages for a
  review short paper, a plain-Unicode metadata rendering, an abstract no longer
  than 200 words, and Limitations after the conclusion before references.

## Date-aware execution plan

### 2026-07-20 — packet and source freeze

- [x] **[VERIFIED]** Read `AGENTS.md`, repository guidance, active paper docs,
  artifact README/license, adjudication boundary, and prior PR #8.
- [x] **[VERIFIED]** Confirm the official deadline independently; July 19 is
  not the REALM direct-submission deadline.
- [x] **[VERIFIED]** Create/update [`submission_packet.md`](../submission_packet.md)
  with paste-ready metadata and clearly separated author-only fields.
- [x] **[VERIFIED]** Preserve the scientific boundary: the three-tier
  capability study is prospectively frozen development evidence; the older V2
  study is supporting evidence; Static and ReAct use different retrieval
  policies over the same corpus; no router is fit/evaluated; the oracle is
  diagnostic; the final partition is unexecuted; author review is not
  independent adjudication.
- [x] **[VERIFIED]** Preserve the two hash-bound protocol Markdown files
  unchanged. Their historical local paths are excluded from the submission PDF
  and artifact; removing them would invalidate the frozen protocol hashes.

### 2026-07-21 to 2026-07-29 — author/admin completion

- [x] **[USER ONLY]** Confirm the final sole-author list/order and affiliation.
  The identity is intentionally not recorded in anonymous release materials;
  exact OpenReview profile ID/email and conflicts still need to be copied or
  checked in the submission form.
- [x] **[USER ONLY]** Confirm the sole author's OpenReview profile is active.
- [x] **[USER ONLY]** Nominate the sole author as reviewer and confirm
  willingness/availability.
- [x] **[USER ONLY]** Confirm `Archival`, no concurrent review elsewhere, and
  no cross-submission (`cross_submission_to`: “None—direct submission”).
- [ ] **[USER ONLY]** Confirm subject-area/keyword choices, any preprint status,
  and whether the venue offers a supplementary software/data upload. The live
  direct schema currently exposes a PDF field but no artifact field.
- [ ] **[USER ONLY]** Confirm acceptance of the OpenReview CC BY 4.0 note
  license and the repository MIT license for the provider-free artifact; retain
  upstream benchmark/provider terms as documented in
  `paper/realm2026/artifact/LICENSES.md`.
- [x] **[USER ONLY]** Confirm the AI-assistance disclosure in the packet is
  complete and truthful for all authors and satisfies any venue-specific form.

### 2026-07-30 to 2026-08-02 — content and release QA

- [x] **[VERIFIED]** Run the anonymous artifact validator from the repository
  root: `python3 paper/realm2026/artifact/validate_artifact.py`.
- [x] **[VERIFIED]** Confirm the artifact remains provider-free, development-only,
  answer/trace-free, excludes the sealed final partition, and has matching
  `manifest.json`/`checksums.sha256`.
- [x] **[VERIFIED]** Run the full maintained finance test suite and record the
  exact pass/fail count and any pre-existing warnings. Do not execute provider
  calls or the final partition.
- [x] **[VERIFIED]** Compile with the prescribed LaTeX skill command and inspect
  the rendered PDF page by page. Recheck title/abstract parity, citations,
  anonymity, Limitations placement, and that every scientific number is
  development-only.
- [x] **[VERIFIED]** Check `pdfinfo` for A4 and page count, `pdffonts` for
  embedded fonts, extracted text for identity/local-path strings, and logs for
  overfull boxes or unresolved references.
- [x] **[RECOMMENDED]** Run a second PDF view/print check in grayscale and keep
  a one-page validation log with exact commands and outputs.

## Current validation snapshot (2026-08-03)

These results are from the current task branch and should be rerun after any
manuscript, artifact, or frozen-source change:

- [x] **[VERIFIED]** Artifact: `python3
  paper/realm2026/artifact/validate_artifact.py` passed with exactly **34
  tracked artifact files, 1,350 sanitized score rows, and 900 capability audit
  pairs**. It recomputed both capability runs' exact matrices,
  Clopper--Pearson intervals, continuous headroom, paired bootstrap intervals,
  macro quality, per-dataset operating points, integrity, and anonymity checks.
- [x] **[VERIFIED]** Tests: `PYTHONPATH=. python3 -m pytest -q tests/finance`
  passed **242 tests** with no warnings or failures.
- [x] **[VERIFIED]** Analysis replay: the completed three-tier ledger reproduced
  its committed aggregate and decision memo byte for byte. The capability
  headroom/stability audit also reproduced its JSON, memo, and all 900 sanitized
  pairs byte for byte, with fingerprint
  `sha256:f4d40f3b39acf465a1271ccda962fc34edd8d8a3221acee3bb664b5eb842ce72`.
- [x] **[VERIFIED]** LaTeX: the prescribed skill selected TeX Live
  `/Library/TeX/texbin/latexmk`, exited 0, and produced a **5-page, 169,772-byte**
  PDF. The skill correctly bypassed Tectonic because bibliography tooling is
  present. TeXCount reports **178 abstract words**, below the 200-word limit.
- [x] **[VERIFIED]** PDF geometry/metadata: `pdfinfo` reports **5 pages** and
  **595.276 x 841.890 pt (A4)**; Author, Subject, and Title are blank; Creator
  is `LaTeX with hyperref`; no identity string is present.
- [x] **[VERIFIED]** Fonts: `pdffonts` reports **12 embedded fonts**, all with
  `emb=yes`; no overfull boxes or undefined citations/references were found.
  The log contains 5 underfull-box warnings, which do not change page count
  or clip content.
- [x] **[VERIFIED]** Citation/source audit: **14 cited keys**, **18 bibliography
  keys**, **0 missing citation keys**. The four unused bibliography entries do
  not create unresolved references.
- [x] **[VERIFIED]** Visual inspection: all five rendered pages were inspected;
  the anonymous ACL review line is present, the complementarity/efficiency table
  is grayscale-readable, research content and Limitations end on content page 4,
  and References begin on page 5. A separate grayscale rendering of the main
  result page was inspected.
- [x] **[VERIFIED]** The anonymous PDF text and validated artifact contain no
  author identity, private/deanonymizing URL, local path, raw secret, final
  outcome, or final example. The capability snapshot contains only curated
  aggregate outcomes and process/budget provenance, with no prompts, answers,
  traces, or partial-freeze outcomes. Hash-bound protocol files passed their
  integrity tests and were not edited after inference. The requested vocabulary
  audit also passed; manuscript prose has no stylistic compound hyphens outside
  canonical names and mathematical signs.
- [x] **[VERIFIED]** Ghostscript rendered all PDF pages without an integrity
  error. The final PDF SHA-256 is
  `3568bddba3a120a94f57f5926374cf54e4fff35a7e9c9b22360e7c870bf9f24a`.

### 2026-08-03 — internal content freeze

- [ ] **[RECOMMENDED]** Freeze the manuscript, packet, artifact, and checklist
  after one final author review. Any later edit reruns the complete QA block.
- [ ] **[USER ONLY]** Reconfirm that no author-identifying repository, local path,
  private URL, acknowledgement, or non-anonymous supplementary link is present.
- [ ] **[USER ONLY]** Reconfirm that the ethics answer covers benchmark/data
  provenance, financial-QA misuse risk, lack of human subjects, lack of human
  adjudication, and non-deployment/non-advice use.

### 2026-08-04 — submission buffer

- [ ] **[RECOMMENDED]** Submit at least one day before the hard deadline, then
  download the submitted PDF and verify that OpenReview displays the intended
  title, abstract, keywords, archival choice, and author list.
- [ ] **[USER ONLY]** Save the OpenReview forum URL, submission number, receipt
  email, and the exact final PDF checksum in the private author record.

### 2026-08-05 — hard deadline

- [ ] **[VERIFIED]** If not already submitted, upload the PDF and complete the
  required fields before **23:59 AoE (UTC-12)**. OpenReview's UTC equivalent is
  **2026-08-06 11:59 UTC**.

## Local validation commands

Run from the repository root. These commands are provider-free unless a command
is explicitly marked otherwise; none of the release checks authorizes model
calls or final-partition access.

```bash
python3 paper/realm2026/artifact/validate_artifact.py
python3 -m pytest -q tests/finance
```

Compile using the LaTeX skill from its plugin root. Replace the angle-bracket
placeholders with the local plugin and repository paths at execution time; do
not commit those machine-specific paths:

```bash
python3 <latex-skill-root>/scripts/compile_latex.py \
  <repo-root>/paper/realm2026/main.tex \
  --output-directory <repo-root>/paper/realm2026/build \
  --json
```

Then inspect `paper/realm2026/build/main.pdf` with `pdfinfo`, `pdffonts`,
`pdftotext`, and a page-rendering/viewer pass. The build directory is ignored
and must not be staged.
