# REALM 2026 blinded adjudication packet

`blinded_packet.csv` is the authoritative fillable packet and
`blinded_packet.md` is a reviewer-friendly rendering. Both contain exactly
the 51 cases selected by the committed fairness audit that require semantic
manual review. They intentionally do not expose system identities or the
audit's deterministic categories.

Codex must not fill the human labels. Two authors should independently label
every A/B answer, then a third author (or an agreed adjudicator) may use the
private A/B key to resolve disagreements. Keep the independent forms and
record the final resolution and rationale. Do not alter official scores or
include the 900-example final partition in this process.

The packet is generated offline from
`paper/realm2026/artifacts/fairness_audit.json`:

```bash
python3 scripts/realm26_blinded_adjudication.py
```

The deterministic assignment seed is embedded in the packet metadata. The
mapping is written to `paper/realm2026/adjudication/private/ab_key.json`.
That directory is intentionally ignored and must be transferred through a
private author channel, never committed, uploaded with the packet, or shown
to independent reviewers. The private key is not needed for independent
review.
