# Hostile-review memo: reproducibility and anonymity

The artifact is intentionally narrower than a full rerunnable experiment.
That is a feature for this submission: a reviewer can verify the exact
recorded development statistics, a sanitized per-example score ledger,
protocol, prompts, scorers, router, model catalog,
price table, development manifests, and hashes without any provider call or
access to the sealed partition.

Likely objections and current answers:

1. **“The result cannot be independently recomputed from raw rows.”** The
   headline macro and complementarity counts can now be recomputed from a
   whitelisted 1,050-row metric/telemetry ledger. The scorer itself cannot be
   rerun because benchmark answers and model responses remain excluded. This
   is an explicit privacy/licensing boundary, not end-to-end reproducibility.
2. **“The price claim is stale or provider-dependent.”** The dated fallback
   table and the resolved model catalog snapshot are both hashed. Raw token
   accounting remains the authoritative audit trail in the source protocol;
   dollars are not presented as universal.
3. **“The package leaks the held-out set.”** Final manifests and final rows are
   absent. The validator rejects final fields in development manifest files,
   outcome/result/trace/build paths, absolute local paths, raw secrets, and
   unapproved URLs.
4. **“The anonymous submission is easy to deanonymize.”** The release checklist
   requires review ACL mode, anonymous author metadata, no private URLs, no
   local paths, embedded fonts, A4, and a final PDF metadata inspection.
5. **“The paper overclaims a router result.”** The manuscript and project state
   already frame this as a failed development gate and negative complementarity
   result. Suggested prose changes, if needed, belong in a separate manuscript
   edit and are deliberately not made by this packaging change.

Open blockers before archival submission: complete the ACL ethics/AI-use/admin
answers, confirm citation completeness, perform the final PDF metadata/font
inspection, and decide whether the venue requires a separate artifact DOI or
license notice. None is resolved by this source-only commit.
