# ICAIF 2026 Track Decision After the Development Gate

Decision date: 2026-07-09  
Protocol: `finance_icaif26_v2`  
Final-manifest state: unopened (900 examples)

## Decision

**Do not submit the current selective-orchestration claim to the ICAIF 2026
main track. Retain this version for a workshop or a later expanded study.**

This is the conditional outcome specified before the repaired development run:
if neither Selective Nexus nor Static Nexus is Pareto-competitive, the project
must not force a main-track claim or inspect the final set.

## Development evidence

The five systems were rerun on the complete development partition: 50 examples
from each of five datasets, 1,250 paired system/example results in total. All
results completed successfully with measured provider telemetry.

| System | Primary macro | Cost / example (USD) | Development status |
| --- | ---: | ---: | --- |
| Direct | 41.38% | 0.000343 | Frontier |
| CoT/PoT | **43.23%** | 0.000819 | Frontier |
| Static Nexus | 43.04% | 0.001010 | Dominated by CoT/PoT |
| Selective Nexus | 36.75% | 0.001322 | Dominated |
| ReAct | 29.93% | 0.001479 | Dominated |

The primary macro is the unweighted mean of FinQA execution accuracy, TAT-QA
official F1, and ConvFinQA execution accuracy. FinanceBench strict scoring and
FinDER operational results remain secondary and do not enter this macro.

Among the 200 examples with objective router labels, only 10 were ReAct-correct
and Static-Nexus-incorrect. This is insufficient for the preregistered learned
router, so the rule fallback activated. It escalated 70% of examples; the fresh
selective rerun achieved 29.5% exact accuracy versus 39.5% for always static
(the offline saved-branch estimate was 28.0%) while increasing cost.

## Why this is not currently a main-track paper

1. The proposed selector contribution failed its preregistered development
   gate rather than merely missing statistical significance.
2. Static Nexus does not provide a fallback contribution because CoT/PoT is
   slightly more accurate and about 19% cheaper on the primary development
   aggregate.
3. Opening the 900-example final set now would spend the confirmatory sample on
   a method whose central claim is already contradicted by development data.
4. Reframing the same experiment as a universal agentic failure would also be
   too strong: the controlled-evidence setting isolates orchestration and does
   not evaluate end-to-end retrieval.

## Viable workshop/later-study angle

> **Controlled Evidence Reveals Agentic Overthinking in Financial QA**

The defensible contribution is an exploratory, leakage-audited comparison
showing that iterative agency can add cost and errors when benchmark evidence
is already available. A workshop paper can report the development study,
failure modes, and the value of strict protocol controls without presenting the
unopened final manifest as confirmatory evidence.

A new main-track attempt should require a substantively different method and a
new preregistered protocol version, not threshold retuning. Examples include an
answer-verification trigger with independently measurable uncertainty, an
end-to-end retrieval setting where iterative search can create genuine value,
or a new dataset designed to contain enough static-versus-iterative
disagreements to support routing. The current 900-example final manifest should
remain sealed until such a protocol is frozen.
