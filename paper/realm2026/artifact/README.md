# Anonymous REALM 2026 review artifact

This is the smallest provider-free bundle for reproducing the paper's
development aggregation and inspecting the exact protocol inputs. It contains
development-only aggregate statistics, development manifest rows, prompt and
scorer source snapshots, the router snapshot, the dated price table, and the
resolved model catalog snapshot used by the run.

The sealed final partition is excluded. No final outcomes, final examples,
provider responses, raw traces, credentials, datasets, archives, or build
products are included. The package therefore reproduces aggregation from the
committed aggregate statistics and verifies all source and manifest hashes; it
does not rerun a model.

## One-command validation

From the repository root, with Python 3.10+:

```bash
python3 paper/realm2026/artifact/validate_artifact.py
```

The validator is offline and does not import provider clients. It checks the
tracked filename/text surface, final-partition exclusion, source references,
checksums, expected manifest shape, anonymous wording, and absence of raw
secrets. It reports paths and rule names only; secret values are never printed.

To regenerate the committed bundle after an intentional source change:

```bash
python3 paper/realm2026/artifact/assemble_artifact.py
python3 paper/realm2026/artifact/validate_artifact.py
```

Regeneration is a maintainer action, not a review-time provider call.

## Layout and provenance

* `snapshots/` contains exact byte copies of the protocol, prompt templates,
  scorer, price-table source, router, development aggregate, and model catalog
  snapshot. Their provenance is recorded in `manifest.json` and
  `checksums.sha256`.
* `development_manifests/` contains only the 50 development records per
  dataset. The `final` field is removed and an explicit exclusion marker is
  added.
* `manifest.json` records the artifact schema, source commit, partition, and
  expected file hashes. `checksums.sha256` is the independently convenient
  hash list.

The source commit is the archival branch tip `c08d0ae` before this artifact
addition. Public benchmark/model names are provenance, not author identity.
The model snapshot records the catalog query timestamp and public model
pricing; the separate dated fallback rates are in the telemetry source
snapshot.

## Environment and licensing

The development aggregation is JSON-only and needs no datasets or network.
For code inspection, use Python 3.10+; the project finance tests additionally
use the dependencies documented by the repository's normal environment. The
artifact is released under the repository license in `LICENSE`. Dataset and
provider metadata remain subject to their upstream terms; this bundle does not
redistribute dataset content.

## Release gate

Before submission, run this validator, the finance test suite, and the ACL PDF
checks in `paper/realm2026/notes/release_checklist.md`. Do not create or add an
archive, PDF, LaTeX build directory, result row, final manifest, or trace.
