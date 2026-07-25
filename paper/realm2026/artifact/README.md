# Anonymous REALM 2026 review artifact

This is a provider-free bundle for auditing the paper's recorded development
statistics and inspecting the exact protocol inputs. It contains the original
development aggregates, paired-statistics output, a trace-audit summary with
raw answers removed, replication and harmonized-v2 aggregates/protocols,
development manifest rows, a sanitized per-example score/telemetry ledger,
prompt/scorer snapshots, the router snapshot, dated prices, and resolved model
snapshots.

The sealed final partition is excluded. No final outcomes, final examples,
provider responses, raw traces, credentials, datasets, archives, or build
products are included. The package recomputes the headline macro and
complementarity counts from 1,350 whitelisted per-example metric/telemetry rows,
including all 300 harmonized-v2 arm rows, and verifies treatment-integrity
fields and internal hashes. It cannot rerun the scorer without withheld
answer/gold text, does not validate a Git commit, and does not rerun a model.

## One-command validation

From the repository root, with Python 3.10+:

```bash
python3 paper/realm2026/artifact/validate_artifact.py
```

The validator is offline and does not import provider clients. It checks the
tracked filename/text surface, final-partition exclusion, score-ledger headline
recomputation, checksums, expected manifest shape, anonymous wording, absence
of raw secrets, and absence of identity-linkable Git commit IDs. It reports
paths and rule names only; secret values are never printed.

To regenerate the committed bundle after an intentional source change:

```bash
python3 paper/realm2026/artifact/assemble_artifact.py
python3 paper/realm2026/artifact/validate_artifact.py
```

Regeneration is a maintainer action, not a review-time provider call.

## Layout and provenance

* `snapshots/` contains exact byte copies of the protocol, prompt templates,
  scorer, price-table source, router, development aggregates, paired analysis,
  sanitized fairness summary, per-example score ledger, replication and
  harmonized-v2 protocols/analyses, the v2 prompt, and model catalog snapshots.
  Their package integrity is
  recorded in `manifest.json` and `checksums.sha256`. The fairness summary
  excludes trace items, answers, and ground truth.
* `development_manifests/` contains only the 50 development records per
  dataset. The `final` field is removed and an explicit exclusion marker is
  added.
* `manifest.json` records the artifact schema, opaque source freeze, partition,
  and expected file hashes. `checksums.sha256` is the independently convenient
  hash list.

The manifest uses an opaque source-freeze label. Identity-bearing repository
and commit references are deliberately withheld for double-blind review;
file-level package checksums remain available. Public benchmark/model names are
scientific provenance, not author identity.
The model snapshot records the catalog query timestamp and public model
pricing; the separate dated fallback rates are in the telemetry source
snapshot.

## Environment and licensing

Artifact validation needs Python and Git repository context, but no datasets or
network.
For code inspection, use Python 3.10+; the project finance tests additionally
use the dependencies documented by the repository's normal environment. The
artifact is released under the repository license in `LICENSE`. Dataset and
provider metadata remain subject to their upstream terms; this bundle does not
redistribute dataset content.

## Release gate

Before submission, run this validator, the finance test suite, and the ACL PDF
checks in `paper/realm2026/notes/release_checklist.md`. Do not create or add an
archive, PDF, LaTeX build directory, result row, final manifest, or trace.
