# REALM 2026 archival short-paper submission packet

Prepared 2026-07-20 for the direct OpenReview submission. This document is a
paste-ready draft, not a substitute for author/admin confirmation. Values under
“User-only administrative fields” must be completed by the submitting authors.

## Verified target

- Venue: REALM @ EMNLP 2026
- Track: archival short paper, direct submission
- OpenReview venue: `EMNLP 2026 Workshop REALM`
- Direct deadline: 2026-08-05, 23:59 Anywhere on Earth (UTC-12)
- OpenReview UTC equivalent: 2026-08-06, 11:59 UTC
- Required paper type: `Archival`
- Source: [REALM CFP](https://realm-workshop.github.io/call_for_papers/)
- Live form/schema: [OpenReview venue](https://openreview.net/group?id=EMNLP%2F2026%2FWorkshop%2FREALM),
  [submission invitation](https://api2.openreview.net/invitations?id=EMNLP%2F2026%2FWorkshop%2FREALM%2F-%2FSubmission)

## Paste-ready OpenReview fields

### Title

When Agentic Reasoning Fails to Pay Off: A Negative Result on Selective Routing in Financial Question Answering

This is the plain-Unicode metadata form of the title in `main.tex`; do not
paste the LaTeX line-break command into OpenReview.

### Abstract

Selective routing can improve an accuracy–cost frontier only if its expensive branch supplies enough unique correct answers. We test this prerequisite in a prospectively frozen comparison of one-call Static and bounded retrieval-first ReAct on 150 fresh financial-QA development items. Both arms use the same model, final-answer parser and scorer, retrieval interface, and evidence, context, and output ceilings; every ReAct row was verified to begin with Search and observe evidence. Static scored 0.342 versus ReAct's 0.257 (paired macro difference −0.085, 95% CI [−0.147, −0.025]). The exact complementarity matrix contained 23 both-correct, 21 Static-only, five ReAct-only, and 101 both-wrong cases, so an oracle could improve over the better branch by only 3.3 points. ReAct used more calls and time but fewer input tokens and dollars. An earlier routing study, which motivated this correction, likewise failed but had unequal answer and context contracts. Our result concerns bounded retrieval-first ReAct under controlled benchmark evidence, not agents generally. Expert complementarity and evaluation-contract fairness should be established before router optimization.

This is a plain-text rendering of `sections/abstract.tex`; the content and
numbers match the manuscript. It is 164 words under the repository's word
counting check and stays below the ACL 200-word limit.

### TL;DR

A prospective corrective development study found bounded ReAct less accurate than Static under matched answer contracts, leaving no evidence that a new router should be fit.

### Keywords

LLM agents, agent evaluation, financial question answering, model routing, selective prediction, ReAct, retrieval, cost-aware inference, negative results

### Paper type / archival choice

Archival

### Contribution statement

This paper makes three scoped contributions:

1. It documents a failed quality–cost criterion for selective routing and identifies
   measured expert complementarity as a prerequisite for a useful fallback.
2. It reports a fresh, prospectively frozen corrective development comparison
   that harmonizes the model, final-answer/parser/scorer path, retrieval API,
   and resource ceilings while explicitly measuring the remaining retrieved-
   dossier difference (Static averaged 2.87 retrievals versus ReAct's 1.04).
3. It provides an auditable negative result and a provider-free anonymous
   artifact that recomputes aggregate statistics and sanitized telemetry without
   exposing answers, raw traces, credentials, datasets, or the sealed final
   partition.

The paper does not claim independent preregistered confirmation, pure reasoning
over identical dossiers, a router trained/evaluated on V2, human adjudication,
or universal agentic failure.

### Limitations statement

The study measures orchestration over benchmark-provided evidence, not
end-to-end retrieval, complete filings, OCR, or missing evidence. All reported
samples are development evidence; the protected final partition was not executed
or scored. V2 was frozen before inference but designed after the original study
and a failed first corrective freeze, so it is prospective corrective evidence,
not an independent preregistered confirmation. The arms share model,
final-answer/parser/scorer path, retrieval API, and resource ceilings, but not
identical retrieved dossiers; this is an end-to-end retrieval-policy comparison.
Provider behavior, pricing, and latency may change, and stronger or differently
designed agents may behave differently. A prospective GPT-5.6 Luna/Terra
extension stopped on treatment-integrity failures before a complete Luna tier
or any Terra call; no partial outcomes were analyzed. The deterministic trace
audit is author review rather than independent human adjudication; its semantic
candidates remain unresolved. FinDER is
secondary because it lacks human-validated objective labels. No router is fit
or evaluated on V2; its oracle union is diagnostic only.

### Ethics statement

The work uses public benchmark datasets and model APIs for controlled financial
question-answering research. It does not involve human subjects, personal data,
or deployment to make financial decisions. The outputs are not investment,
accounting, or trading advice, and readers should not treat benchmark accuracy
as evidence of financial reliability. We discuss the risk that an agentic QA
system could be over-trusted and therefore keep the claims conditional on the
tested models, policies, evidence, and scoring contracts. Final-partition
identifiers were used only for overlap exclusion; no final example was rendered,
executed, or scored. No experimental provider calls were made during release QA,
and no human adjudication has been completed or represented as completed.

### AI-assistance disclosure

AI assistance was used to inspect repository documentation, design and execute
prospectively frozen development experiments, draft and edit the manuscript and
submission materials, and perform source-level consistency, compilation, and
artifact-validation checks. The protected final partition was not accessed
beyond identifier-only overlap exclusion, and AI assistance did not create
human labels or independent adjudication. The author reviewed the resulting
claims and retains responsibility for the manuscript, data provenance,
scientific conclusions, ethics answers, and final OpenReview submission.

### Reproducibility / artifact statement

An anonymous, provider-free artifact accompanies the source release where the
submission workflow permits supplementary material. It contains public
protocol inputs, aggregate analyses, model/price snapshots, prompt/scorer
snapshots, development-only manifests, and a sanitized 1,350-row metric and
telemetry ledger, including all 300 harmonized-v2 arm rows. Its offline
validator recomputes headline macros, complementarity counts, treatment
integrity, anonymity checks, and package hashes. It excludes benchmark data,
answers, raw traces, credentials, provider responses, final identifiers and
outcomes, and all build products; it cannot rerun a model or scorer without
withheld answer/gold text. The repository license is MIT, upstream benchmark
and provider terms remain applicable, and
`paper/realm2026/artifact/LICENSES.md` records the distribution boundary.

The live direct OpenReview schema currently exposes a required PDF field but no
dedicated artifact field. Do not add a public or author-identifying URL to the
anonymous paper; confirm with the venue whether an anonymous supplementary or
artifact upload is accepted.

## User-only administrative fields

Do not infer or fill these from the repository:

- **Authors and affiliations:** final author list/order, full names, exact
  affiliations/addresses, emails, OpenReview profile IDs, and corresponding
  author.
- **Conflicts:** institutional, advisor/advisee, collaboration, employment,
  and any venue-specific conflict declarations for every author.
- **Reviewer nomination:** at least one eligible author profile to serve as a
  reviewer, plus their confirmation that they can review.
- **Profile completion:** profile activation, institutional-email status,
  expertise/subject areas, Semantic Scholar/DBLP/ACL links, and any required
  reviewer registration.
- **Archival/admin decisions:** confirm `Archival`, that the work is original
  and not under review elsewhere, and the optional `cross_submission_to` value.
  For a true direct submission, use `None—direct submission` only after author
  confirmation.
- **Subject areas and keywords:** confirm the final area/subject-area choices
  if OpenReview presents fields beyond the current live schema; the keyword
  draft above is a recommendation, not an inferred author decision.
- **Preprint and supplementary uploads:** choose any preprint status and confirm
  whether an anonymous software/data/artifact upload is available or desired.
- **Licenses:** confirm acceptance of the OpenReview note license shown by the
  live schema (CC BY 4.0), the repository MIT license, and all upstream dataset
  and provider terms.
- **Ethics and AI-use attestation:** confirm the statements above against the
  authors' actual data collection, human involvement, tools, and venue form.
- **Final submission record:** after upload, privately save the OpenReview forum
  URL, submission number, receipt, exact PDF checksum, and the submitted-field
  export.

## Hard blockers before submission

1. The author-only fields above must be completed and checked by the authors.
2. The PDF/artifact/test validation block in the release checklist must pass;
   no release check may call a provider or access the final partition.
3. The final OpenReview form must preserve the manuscript's anonymous title,
   abstract, archival status, and scientific boundaries.
