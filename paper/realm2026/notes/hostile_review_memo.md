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
   exact successes, while headroom over its empirically better arm is one item.
   Its native-quality point estimate is 1.0 point (95% upper limit 2.1).
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
   schema, prompt, output ceiling, retry rule, and parser are identical;
   only model ID and the authorized inapplicable reasoning-field omission
   differ.
7. **“The headroom point estimates are not hard ceilings.”** Correct. The paper
   now leads with native-quality headroom and paired intervals (upper limits
   1.9--3.8 points), and labels exact estimates separately (upper limits
   3.7--4.7). Even the optimistic exact bound is an oracle ceiling a learned
   router only partly recovers, with higher observed cost and latency.
8. **“The result is stochastic and rare cells may flip.”** Temperature and
   top-p were omitted, so provider defaults applied and a fixed seed did not
   guarantee deterministic generation. A disclosed post-hoc same-manifest,
   different-seed check changed individual counts and Terra's point ordering,
   but retained only 0--1 exact oracle-benefit items and 0.7--1.4 points of
   native-quality headroom. One replication does not estimate full variance.
9. **“The result cannot be independently recomputed from raw rows.”** The
   artifact now ships 900 identifier-free paired metric records and the exact
   audit code. Its offline validator recomputes both runs' exact matrices,
   Clopper--Pearson intervals, macro quality, native-quality headroom, and paired
   bootstrap intervals. It cannot independently rescore answers because golds,
   predictions, and raw traces remain excluded.
10. **“The package leaks the held-out set or author identity.”** The validator
   rejects final fields, outcome/trace/build paths, absolute paths, raw secrets,
   commit IDs, and unapproved URLs. Final examples and outcomes are absent.
11. **“The trace audit substitutes for human adjudication.”** It does not. It is
   a deterministic sensitivity screen by the sole author; semantic cases remain
   unresolved and are not needed for the fresh matched results.
12. **“Reasoning was disabled.”** Correct. A nonzero-reasoning arm is the key
    untested boundary. Adding it after observing these results would weaken the
    protocol claim, so any follow-up should be prospectively frozen.
13. **“Accuracy is too low to diagnose complementarity.”** FinQA and ConvFinQA
    are near floor. On TAT-QA, where F1 is further from floor, continuous
    headroom remains at most 2.9 points in the main run and 2.5 in the seed
    check. The paper nevertheless concedes that complementarity may emerge at
    deployment-realistic accuracy levels not reached here.
14. **“Costs and model behavior will drift.”** The paper reports provider
    spend and dated model bindings as properties of this run. The scientific
    claim is based primarily on paired correctness and complementarity, not a
    universal price forecast.

Open blockers before archival submission are administrative: complete the
remaining OpenReview profile/conflict/license fields, decide whether the venue
accepts a separate anonymous artifact, and perform final author review. The PDF,
tests, artifact, citations, metadata, and visual checks must be rerun after the
current rewrite.
