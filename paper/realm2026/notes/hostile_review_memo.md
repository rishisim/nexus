# Hostile-review memo: methodology, reproducibility, and anonymity

The artifact is intentionally provider-free rather than a full rerunnable
experiment. Reviewers can inspect recorded development aggregates, a sanitized
earlier-study score ledger, protocols, prompts, scorers, manifests, model
catalogs, and hashes without a provider call or sealed-partition access.

Likely objections and current answers:

1. **“Terra parity disproves the negative result.”** The revised paper no
   longer claims an invariant ReAct deficit. It reports the positive
   Terra--control and Terra--Luna interactions as a capability boundary. The
   routing conclusion rests on complementarity: Terra has only two ReAct-only
   exact successes and 0.7 points of oracle headroom.
2. **“The provider tiers are not a capability scale.”** Correct. They are named
   product tiers under one provider route, and Luna is not monotonically better
   on these tasks. The paper reports tier interactions and avoids a universal
   ordering claim.
3. **“Static and ReAct still see different evidence.”** Correct. They share the
   corpus, API, and ceilings, not the retrieved dossier. Static averages about
   2.85 retrieval operations and ReAct 1.16--1.31. The estimate compares
   end-to-end retrieval policies, not pure reasoning over identical evidence.
4. **“The paper claims a repaired router without evaluating one.”** It does
   not. The main study tests the paired complementarity prerequisite; no new
   router is fit or evaluated, and the oracle union is a diagnostic upper
   bound.
5. **“The two stopped freezes create researcher degrees of freedom.”** Both
   stops followed frozen process rules, no partial outcome was analyzed, all
   touched identifiers were excluded, the transport change was applied to all
   tiers before fresh synthetic probes, and the successful manifest and
   analysis were publicly frozen before inference.
6. **“The strict function tool favors one model.”** The live catalog showed
   `tools` and `tool_choice` on the same OpenAI endpoint for all tiers. The tool
   schema, prompt, seed, output ceiling, retry rule, and parser are identical;
   only model ID and the authorized inapplicable reasoning-field omission
   differ.
7. **“The result cannot be independently recomputed from raw rows.”** The
   artifact checks all three main complementarity matrices and includes the
   completed aggregate. It does not release capability answers, golds, or raw
   traces, so it cannot independently rescore the run. That distribution
   boundary is explicit.
8. **“The package leaks the held-out set or author identity.”** The validator
   rejects final fields, outcome/trace/build paths, absolute paths, raw secrets,
   commit IDs, and unapproved URLs. Final examples and outcomes are absent.
9. **“The trace audit substitutes for human adjudication.”** It does not. It is
   a deterministic sensitivity screen by the sole author; semantic cases remain
   unresolved and are not needed for the fresh matched results.
10. **“Costs and model behavior will drift.”** The paper reports provider
    spend and dated model bindings as properties of this run. The scientific
    claim is based primarily on paired correctness and complementarity, not a
    universal price forecast.

Open blockers before archival submission are administrative: complete the
remaining OpenReview profile/conflict/license fields, decide whether the venue
accepts a separate anonymous artifact, and perform final author review. The PDF,
tests, artifact, citations, metadata, and visual checks must be rerun after the
current rewrite.
