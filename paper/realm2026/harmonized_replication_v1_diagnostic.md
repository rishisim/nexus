# Post-run diagnostic: harmonized replication v1

Status: **manipulation-check failure; do not use the v1 directional estimate as
evidence about iterative ReAct quality.** This diagnostic was written only
after the prospectively frozen run and analysis completed. It does not alter,
rescore, discard, or rerun any v1 row.

## Observed collapse

The run completed all 150 paired development items and all integrity/provider
guards passed. However, the intended iterative treatment did not occur:

- all 150 ReAct rows had `parse_status = ok`;
- all 150 ReAct rows submitted `UNKNOWN`;
- all 150 ReAct rows made exactly one model call;
- all 150 ReAct rows performed zero retrieval operations and observed zero
  evidence words;
- Static made one call after two or three deterministic evidence operations,
  and submitted `UNKNOWN` on 7 of 150 rows.

Consequently, the frozen analysis's `static_advantage` label compares Static
with retrieved evidence against immediate ReAct abstention. It is not an
estimate of one-call Static versus bounded iterative ReAct under realized
comparable evidence access.

## Protocol mechanism

The shared finish contract instructed both systems to submit `UNKNOWN` when
evidence was insufficient. Static received retrieved evidence before its only
model call. ReAct's first prompt displayed no evidence and allowed either an
evidence action or `Finish`. The model consistently followed the insufficiency
instruction by finishing with `UNKNOWN` immediately, so the loop never reached
an evidence-bearing second step.

This is a structural prompt-policy conflict visible without using answer
correctness: the treatment failed its behavioral manipulation check on every
ReAct item. The zero ReAct score is therefore not interpreted substantively.

## Consequence and next valid action

Version 1 remains an immutable, development-only protocol-failure record. It
must not be folded into the original selector gate, used to claim a universal
Static advantage, or presented as the acceptance-critical corrective result.

Any replacement must be a separately named and prospectively frozen protocol
on fresh development items. Before public freeze, its ReAct policy must require
an evidence action while evidence is absent and retrieval budget remains, and
its smoke must include a predeclared behavioral manipulation check without
examining correctness. No v1 item may be reused for that study.
