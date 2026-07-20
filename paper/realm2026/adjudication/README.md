# REALM 2026 blinded author adjudication

This directory defines the frozen, human-only review of the 51 development
cases selected by `paper/realm2026/artifacts/fairness_audit.json`. Codex must
not fill, infer, or resolve any human label.

## Why the reviewer forms are private

The forms contain exact benchmark questions, prior dialogue where required,
reference answers, and submitted responses. They are generated under
`private/`, which is ignored, and must be transferred directly to reviewers.
The public repository contains the generator, frozen rubric, and an integrity
manifest, not the fillable forms or A/B key.

This is operational blinding, not a claim that the underlying public audit is
cryptographically unlinkable. During independent review, reviewers must receive
only their assigned CSV, `rubric.md`, and `REVIEWER_GUIDE.md`; they must not
inspect the repository, audit, other reviewer's form, or private key.

## Generate or verify the packet

The generator reads only the recorded development result files named by the
audit and verifies their frozen SHA-256 hashes. It does not load datasets, open
the sealed final partition, or call a provider.

Initialize the private assignment once:

```bash
python3 scripts/realm26_blinded_adjudication.py --initialize-private-key
```

Rerun deterministically with the preserved private key:

```bash
python3 scripts/realm26_blinded_adjudication.py
```

Use `--rotate-private-key` only before either reviewer receives a form. Never
rotate or regenerate the assignment after review begins.

Generated private files:

- `private/reviewer_packets/reviewer_1.csv`
- `private/reviewer_packets/reviewer_2.csv`
- `private/reviewer_packets/REVIEWER_GUIDE.md`
- `private/key/ab_key.json`

The tracked `packet_manifest.json` commits to the secret assignment and hashes
the exact private reviewer files without exposing the seed or mapping.

## Human workflow

1. Freeze and hash the two reviewer forms before distribution.
2. Give each reviewer only their own CSV, the reviewer guide, and `rubric.md`.
3. Each reviewer independently labels every A/B answer and returns the locked
   form without discussing cases.
4. Validate both returned forms, then reveal the A/B key to the adjudicator.
5. Resolve disagreements against the frozen rubric and record the rationale.
6. Report these as human adjudication of development examples; do not silently
   replace the official benchmark scores.

Keep the ignored private directory until adjudication and manuscript updates
are complete. Do not upload it to GitHub or include it in the anonymous
artifact.
