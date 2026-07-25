# Frozen human-adjudication rubric

Version: `realm26-human-adjudication-rubric-v1`

Apply this rubric independently to both anonymized systems in every case.
Judge only the supplied question, any prior dialogue, the reference answer,
and the submitted response. Do not infer system identity or consult external
files, other reviewers, or the source repository.

## Correctness

- `correct`: the submitted answer semantically answers the exact question and
  agrees with the reference after legitimate formatting, unit, scale, and
  rounding normalization.
- `incorrect`: the answer has the wrong value, entity, sign, period, unit,
  scale, list membership, comparison, or conclusion; abstains despite an
  answerable reference; gives only an unevaluated expression; or adds a
  materially false claim.
- `uncertain`: the supplied task context or reference is genuinely insufficient
  or ambiguous. Do not use this merely because the answer is difficult to
  check.

For numeric answers, follow any precision requested by the question. Otherwise,
accept mathematically equivalent fractions, percentages, currencies, and
scaled quantities when the conversion is explicit or unambiguous. Accept
ordinary rounding consistent with the shown precision; if the intended
precision cannot be determined, use `uncertain` and explain why. For lists,
require all requested members and no materially incorrect extras.

## Unit and scale validity

Use `valid`, `invalid`, `not_applicable`, or `uncertain`.

- `valid`: unit, currency, percentage/fraction interpretation, and magnitude
  are correct or unambiguously equivalent.
- `invalid`: the numeric core may be related to the reference, but its unit,
  sign, currency, percent/fraction conversion, or thousand/million/billion
  scale is wrong.
- `not_applicable`: the task is nonnumeric and has no meaningful unit or scale.
- `uncertain`: the question and reference do not establish the intended unit or
  scale.

## Failure cause

Use one primary value: `none`, `abstention`, `arithmetic`, `period`,
`unit_scale`, `answer_contract`, `unsupported_claim`, `incomplete`, `other`, or
`uncertain`. Use `none` for correct answers. Assign only a cause supported by
the submitted response; do not guess about hidden retrieval or reasoning.
Explain `other` and borderline decisions in notes.

## Confidence and notes

Confidence is `high`, `medium`, or `low`. Notes should briefly justify every
`uncertain`, `invalid`, `other`, or low-confidence label and any decision where
the answer differs textually from the reference but is judged semantically
correct.
