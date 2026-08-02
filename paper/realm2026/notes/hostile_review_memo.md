# Hostile-review memo: methodology, reproducibility, and anonymity

The artifact is intentionally narrower than a full rerunnable experiment.
That is a feature for this submission: a reviewer can verify the exact
recorded development statistics, a sanitized per-example score ledger,
protocol, prompts, scorers, router, model catalog,
price table, development manifests, and hashes without any provider call or
access to the sealed partition.

Likely objections and current answers:

1. **“V2 did not really equalize evidence.”** Correct: it equalized the model,
   final-answer contract, parser/scorer path, retrieval API, and ceilings, but
   not the retrieved dossier. Static averaged 2.87 retrieval operations and
   ReAct 1.04. The manuscript now states that the estimate compares end-to-end
   retrieval policies, not pure reasoning over identical evidence.
2. **“The corrective study is being sold as confirmatory.”** V2 was publicly
   frozen before inference and uses fresh rows, but its design followed the
   original study and a failed first corrective freeze. The paper now calls it
   prospective corrective development evidence, not an independent
   preregistered confirmation.
3. **“The paper claims a repaired router without evaluating one.”** It does not.
   V2 tests the prerequisite of expert complementarity; no new router is fit or
   evaluated, and the oracle union is labeled a diagnostic upper bound.
4. **“A bootstrap interval is being described as definitive significance.”**
   The manuscript now reports the frozen paired interval and says that it
   excludes zero, while retaining the development-only and policy-conditional
   scope.
5. **“The result cannot be independently recomputed from raw rows.”** The
   headline macro and complementarity counts can now be recomputed from a
   whitelisted 1,350-row metric/telemetry ledger. The scorer itself cannot be
   rerun because benchmark answers and model responses remain excluded. This
   is an explicit privacy/licensing boundary, not end-to-end reproducibility.
6. **“The price claim is stale or provider-dependent.”** The dated fallback
   table and the resolved model catalog snapshot are both hashed. Raw token
   accounting remains the authoritative audit trail in the source protocol;
   dollars are not presented as universal.
7. **“The package leaks the held-out set.”** Final manifests and final rows are
   absent. The validator rejects final fields in development manifest files,
   outcome/result/trace/build paths, absolute local paths, raw secrets, and
   unapproved URLs.
8. **“The anonymous submission is easy to deanonymize.”** The release checklist
   requires review ACL mode, anonymous author metadata, no private URLs, no
   local paths, embedded fonts, A4, and a final PDF metadata inspection.
9. **“The trace audit substitutes for human adjudication.”** It does not. The
   audit remains a deterministic sensitivity screen, its semantic cases are
   unresolved, and V2 avoids relying on those cases for its headline result.
10. **“Why not test a stronger model?”** A prospectively frozen Luna/Terra
    extension was attempted on fresh development items, but repeated provider
    output-contract failures stopped the study before a complete Luna tier or
    any Terra execution. No partial outcomes were analyzed. The artifact reports
    process and budget status only; the manuscript therefore makes no
    stronger-model accuracy claim.

Open blockers before archival submission are administrative: reconfirm the
updated AI-use disclosure, complete the ACL ethics/OpenReview fields and license
choices, and decide whether the venue accepts a separate anonymous artifact.
Citation, artifact, PDF metadata/font, and visual inspections are complete.
