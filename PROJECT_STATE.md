# Project State

> Last updated: 2026-10-03

## Canonical checkout

Use `main` for the integrated research code and latest camera-ready manuscript
in `paper/realm2026/`. The consolidation retains the latest
`realm26/archival-short-paper` file tree and merges the existing `main` history.
The earlier adjudication branch's files are already identical to the integrated
implementation. No new experiment, provider call, or final-partition scoring
was performed during consolidation.

The manuscript's current title is **Capability Is Not Complementarity: A Routing
Feasibility Study in Financial Question Answering**. The completed three-tier
capability study and different-seed stability check are its primary evidence;
the original selector study and replications remain supporting evidence.
See [`paper/realm2026/README.md`](paper/realm2026/README.md) for the detailed
scientific status and [`paper/realm2026/notes/release_checklist.md`](paper/realm2026/notes/release_checklist.md)
for release checks. Repository records describe camera-ready preparation;
this consolidation does not independently verify external submission status.

## Research constraints

- All reported results are development-only.
- The protected final manifest remains unexecuted and unscored.
- Do not tune on existing outcomes and call them fresh evaluation.
- The setting is controlled-evidence reasoning, with no end-to-end retrieval claim.
- FinDER remains secondary without human-validated objective scoring.
- Author adjudication remains secondary and unresolved.
- Preserve the distinct, prospectively frozen protocols as scientific provenance;
  branch consolidation does not combine their experiment definitions or outcomes.

## Recovering retired branches

Every local and remote branch tip at consolidation is preserved by an annotated
Git tag pushed to GitHub before branch deletion:

- `archive/branches/local/<original-branch>` preserves the local tip.
- `archive/branches/origin/<original-branch>` preserves the remote tip.

For example, recover the latest former paper branch with:

```bash
git fetch origin --tags
git switch -c realm26/archival-short-paper archive/branches/origin/realm26/archival-short-paper
```

The `local` tags also preserve local-only branches and local tips that differed
from the remote. The existing `realm-emnlp-2026-camera-ready` release tag is
unchanged. Pre-existing stashes, ignored datasets, environments, private
adjudication files, and build outputs are retained locally; they are not
published by this consolidation. The remaining replication worktree is kept
at its original commit with a detached HEAD so its branch can be retired.

## Validation

From the repository root:

```bash
python -m pytest tests/finance -q
python paper/realm2026/artifact/validate_artifact.py
```

The integrated source and research artifacts match the latest paper branch;
only these entry-point documents change during consolidation. No manuscript
or protocol edits require a new paper build.
