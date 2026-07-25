#!/usr/bin/env python3
"""Build private, blinded REALM 2026 author-adjudication forms.

The frozen fairness audit selects the cases. Exact questions and the prior
dialogue needed for ConvFinQA are recovered only from the hash-verified,
recorded development outputs named by that audit. The script never loads a
benchmark dataset, opens a final manifest, calls a provider, or fills a human
label.

Reviewer forms and the A/B key are private generated artifacts. Only a public
integrity manifest is written outside the ignored private directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "realm26-blinded-adjudication-v2"
RUBRIC_VERSION = "realm26-human-adjudication-rubric-v1"
DEFAULT_AUDIT = Path("paper/realm2026/artifacts/fairness_audit.json")
DEFAULT_ADJUDICATION_DIR = Path("paper/realm2026/adjudication")
DEFAULT_PACKET_DIR = DEFAULT_ADJUDICATION_DIR / "private" / "reviewer_packets"
DEFAULT_KEY = DEFAULT_ADJUDICATION_DIR / "private" / "key" / "ab_key.json"
DEFAULT_MANIFEST = DEFAULT_ADJUDICATION_DIR / "packet_manifest.json"
FORBIDDEN_OUTPUT_PATH_PARTS = {"final", "sealed-final", "results", "outcomes", "traces"}
FORBIDDEN_REVIEWER_TERMS = re.compile(
    r"\b(?:static(?:_nexus)?|react|nexus|framework|one_sided|both_wrong)\b", re.I
)
METHOD_REVEALING_FIELDS = (
    "actions",
    "calls",
    "llm_calls",
    "retrieval_operations",
    "search_queries",
    "trace_sha256",
)
LABEL_FIELDS = (
    "a_correctness",
    "a_unit_scale_validity",
    "a_failure_cause",
    "a_confidence",
    "a_notes",
    "b_correctness",
    "b_unit_scale_validity",
    "b_failure_cause",
    "b_confidence",
    "b_notes",
)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(str(value).encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def _guard_output_path(path: Path) -> None:
    lowered = {part.lower() for part in path.parts}
    if lowered & FORBIDDEN_OUTPUT_PATH_PARTS:
        raise ValueError(f"refusing partition/result-like output path: {path}")


def _validate_audit_scope(audit: Mapping[str, Any]) -> None:
    scope = audit.get("scope", {})
    if scope.get("partition") != "development_only":
        raise ValueError("audit is not explicitly development-only")
    if scope.get("sealed_final_partition_accessed") is not False:
        raise ValueError("audit does not attest that the final partition stayed sealed")
    if scope.get("external_provider_calls") != 0:
        raise ValueError("audit records provider calls")


def _manual_items(audit: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    _validate_audit_scope(audit)
    items = [
        item
        for item in audit.get("trace_items", [])
        if item.get("manual_review_required") is True
    ]
    expected_ids = list(audit.get("summary", {}).get("manual_review_item_ids", []))
    actual_ids = [str(item.get("item_id", "")) for item in items]
    if len(items) != 51 or audit.get("summary", {}).get("manual_review_count") != 51:
        raise ValueError(f"expected exactly 51 frozen manual-review items, got {len(items)}")
    if set(actual_ids) != set(expected_ids) or len(set(actual_ids)) != 51:
        raise ValueError("manual-review items do not match the frozen audit identifier list")
    return items


def _records(value: Any, path: Path) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, Mapping) and isinstance(value.get("results"), list):
        rows = value["results"]
    else:
        raise ValueError(f"unsupported result schema: {path}")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ValueError(f"result rows are not objects: {path}")
    return list(rows)


def _extract_question(raw_trace: Any) -> str:
    matches = re.findall(r"(?mi)^Question:\s*(.+?)\s*$", str(raw_trace or ""))
    normalized = [_normalize(match) for match in matches if _normalize(match)]
    if not normalized:
        raise ValueError("recorded development trace has no explicit Question line")
    if len(set(normalized)) != 1:
        raise ValueError("recorded development trace contains conflicting Question lines")
    return normalized[0]


def _extract_conversation_context(raw_trace: Any) -> str:
    text = str(raw_trace or "")
    candidates: list[str] = []
    for match in re.finditer(r"Conversations:\s*", text, re.I):
        tail = text[match.end():]
        end = re.search(r"\s+\[\d+\]\s+(?:Evidence|Dataset):", tail, re.I)
        candidate = tail[: end.start()] if end else tail
        candidate = _normalize(candidate)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return ""
    return max(candidates, key=len)


def load_task_contexts(
    audit: Mapping[str, Any], repo_root: Path
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Load only audit-named, hash-verified development result files."""

    items = _manual_items(audit)
    run_id = str(audit.get("provenance", {}).get("development_run", ""))
    if "development" not in run_id.lower() or "final" in run_id.lower():
        raise ValueError("audit development_run is not a safe development-only run identifier")
    frozen_hashes = audit.get("provenance", {}).get("input_sha256", {})
    if not isinstance(frozen_hashes, Mapping):
        raise ValueError("audit has no frozen input hash map")

    by_dataset: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        by_dataset.setdefault(str(item["dataset"]), []).append(item)

    arm_indices: dict[str, dict[str, Mapping[str, Any]]] = {}
    verified_sources: dict[str, str] = {}
    for dataset in sorted(by_dataset):
        for arm in ("nexus", "react"):
            relative = Path("results") / "finance" / dataset / run_id / arm / "results.json"
            relative_text = relative.as_posix()
            expected_hash = frozen_hashes.get(relative_text)
            if not isinstance(expected_hash, str):
                raise ValueError(f"audit does not freeze required development input: {relative_text}")
            path = repo_root / relative
            if not path.is_file():
                raise FileNotFoundError(f"missing frozen development input: {relative_text}")
            actual_hash = _sha256_file(path)
            if actual_hash != expected_hash:
                raise ValueError(f"frozen development input hash mismatch: {relative_text}")
            values = _records(json.loads(path.read_text(encoding="utf-8")), path)
            index = {str(row.get("example_id", "")): row for row in values}
            if len(index) != len(values):
                raise ValueError(f"duplicate or empty example IDs in {relative_text}")
            arm_indices[f"{dataset}:{arm}"] = index
            verified_sources[relative_text] = actual_hash

    contexts: dict[str, dict[str, str]] = {}
    for item in items:
        dataset = str(item["dataset"])
        example_id = str(item["example_id"])
        system_rows: list[Mapping[str, Any]] = []
        for arm in ("nexus", "react"):
            row = arm_indices[f"{dataset}:{arm}"].get(example_id)
            if row is None:
                raise ValueError(f"missing {arm} development row for {dataset}:{example_id}")
            system_rows.append(row)
        questions = [_extract_question(row.get("raw_trace")) for row in system_rows]
        if questions[0] != questions[1]:
            raise ValueError(f"system question mismatch for {dataset}:{example_id}")
        conversation = ""
        if dataset == "convfinqa":
            # The one-call record contains the deterministic evidence dossier,
            # including the shared prior dialogue. Iterative traces may repeat
            # that dossier inside action observations, so they are not used to
            # construct reviewer-visible task context.
            conversation = _extract_conversation_context(system_rows[0].get("raw_trace"))
            if not conversation:
                raise ValueError(f"missing prior dialogue for {dataset}:{example_id}")
        contexts[str(item["item_id"])] = {
            "question": questions[0],
            "conversation_context": conversation,
        }

    return contexts, {
        "development_run": run_id,
        "verified_source_files": verified_sources,
    }


def _stable_hash(seed: str, item_id: str, role: str) -> str:
    return hashlib.sha256(f"{seed}:{item_id}:{role}".encode("utf-8")).hexdigest()


def _assignment_commitment(seed: str) -> str:
    return _sha256_text(f"{SCHEMA_VERSION}:assignment-seed:{seed}")


def _redact_identity_terms(value: Any) -> str:
    return FORBIDDEN_REVIEWER_TERMS.sub("[redacted]", _normalize(value))


def build_packet(
    audit: Mapping[str, Any],
    task_contexts: Mapping[str, Mapping[str, str]],
    seed: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    items = _manual_items(audit)
    if not seed or len(seed) < 32:
        raise ValueError("private assignment seed must contain at least 32 characters")

    commitment = _assignment_commitment(seed)
    rows: list[dict[str, str]] = []
    key: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "assignment_commitment": commitment,
        "items": {},
    }
    for item in items:
        item_id = str(item["item_id"])
        context = task_contexts.get(item_id)
        if not context or not _normalize(context.get("question")):
            raise ValueError(f"missing exact question for {item_id}")
        evidence = item["trace_evidence"]
        systems = ["static_nexus", "react"]
        systems.sort(key=lambda system: _stable_hash(seed, item_id, system))
        key["items"][item_id] = {"A": systems[0], "B": systems[1]}
        row = {
            "rubric_version": RUBRIC_VERSION,
            "assignment_commitment": commitment,
            "dataset": str(item["dataset"]),
            "example_id": str(item["example_id"]),
            "question": _redact_identity_terms(context["question"]),
            "prior_dialogue": _redact_identity_terms(context.get("conversation_context", "")),
            "reference_answer": _redact_identity_terms(item.get("ground_truth")),
            "system_a_submitted_answer": _redact_identity_terms(
                evidence[systems[0]].get("answer")
            ),
            "system_b_submitted_answer": _redact_identity_terms(
                evidence[systems[1]].get("answer")
            ),
            **{field: "" for field in LABEL_FIELDS},
            "case_id": item_id,
        }
        rows.append(row)
    rows.sort(key=lambda row: row["case_id"])
    key["case_count"] = len(rows)
    key["packet_case_ids_sha256"] = _sha256_text(
        "\n".join(row["case_id"] for row in rows)
    )
    return rows, key


def _write_csv(rows: Sequence[Mapping[str, str]], path: Path, reviewer_form: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    form_rows = [{"reviewer_form": reviewer_form, **dict(row)} for row in rows]
    fieldnames = [name for name in form_rows[0] if name != "case_id"] + ["case_id"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(form_rows)


def _reviewer_guide(commitment: str) -> str:
    return "\n".join(
        [
            "# REALM 2026 independent blinded review",
            "",
            "Codex must not fill any human label. Complete this review independently.",
            "Use the accompanying frozen rubric. Do not inspect the source repository,",
            "fairness audit, other reviewer's form, assignment key, or system identities",
            "until both completed forms have been returned and locked.",
            "",
            f"Rubric version: `{RUBRIC_VERSION}`",
            f"A/B assignment commitment: `{commitment}`",
            "",
            "Fill every correctness, unit/scale, failure-cause, confidence, and notes",
            "cell for both System A and System B. Do not edit task or answer fields.",
            "",
        ]
    )


def write_outputs(
    rows: list[dict[str, str]],
    key: dict[str, Any],
    packet_dir: Path,
    manifest_path: Path,
    key_path: Path,
    source_metadata: Mapping[str, Any],
    rubric_path: Path,
) -> dict[str, Path]:
    for path in (packet_dir, manifest_path, key_path, rubric_path):
        _guard_output_path(path)
    if not rubric_path.is_file():
        raise FileNotFoundError(f"missing frozen rubric: {rubric_path}")
    packet_dir.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    reviewer_1 = packet_dir / "reviewer_1.csv"
    reviewer_2 = packet_dir / "reviewer_2.csv"
    guide = packet_dir / "REVIEWER_GUIDE.md"
    _write_csv(rows, reviewer_1, "reviewer_1")
    _write_csv(rows, reviewer_2, "reviewer_2")
    guide.write_text(_reviewer_guide(key["assignment_commitment"]), encoding="utf-8")
    key_path.write_text(json.dumps(key, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "rubric_sha256": _sha256_file(rubric_path),
        "scope": {
            "partition": "development_only",
            "case_count": len(rows),
            "external_provider_calls": 0,
            "sealed_final_partition_accessed": False,
            "human_labels_prefilled": False,
        },
        "assignment_commitment": key["assignment_commitment"],
        "packet_case_ids_sha256": key["packet_case_ids_sha256"],
        "private_packet_sha256": {
            reviewer_1.name: _sha256_file(reviewer_1),
            reviewer_2.name: _sha256_file(reviewer_2),
            guide.name: _sha256_file(guide),
        },
        "source": dict(source_metadata),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "reviewer_1": reviewer_1,
        "reviewer_2": reviewer_2,
        "guide": guide,
        "key": key_path,
        "manifest": manifest_path,
    }


def load_or_create_private_seed(
    key_path: Path, *, initialize: bool = False, rotate: bool = False
) -> str:
    if initialize and rotate:
        raise ValueError("choose either initialize or rotate, not both")
    if key_path.exists() and not rotate:
        value = json.loads(key_path.read_text(encoding="utf-8"))
        seed = value.get("seed") if isinstance(value, Mapping) else None
        if not isinstance(seed, str) or len(seed) < 32:
            raise ValueError("existing private key has no valid seed")
        return seed
    if initialize or rotate:
        return secrets.token_hex(32)
    raise FileNotFoundError(
        f"private key is missing: {key_path}; use --initialize-private-key once"
    )


def _validate_private_outputs(outputs: Mapping[str, Path], seed: str) -> None:
    reviewer_text = "\n".join(
        outputs[name].read_text(encoding="utf-8")
        for name in ("reviewer_1", "reviewer_2", "guide")
    )
    if FORBIDDEN_REVIEWER_TERMS.search(reviewer_text):
        raise AssertionError("private reviewer packet leaks a method identity term")
    if seed in reviewer_text or seed in outputs["manifest"].read_text(encoding="utf-8"):
        raise AssertionError("private assignment seed leaked outside the A/B key")
    for name in ("reviewer_1", "reviewer_2"):
        with outputs[name].open(newline="", encoding="utf-8") as handle:
            fieldnames = set(csv.DictReader(handle).fieldnames or [])
        if fieldnames & set(METHOD_REVEALING_FIELDS):
            raise AssertionError("reviewer packet contains method-revealing trace fields")
    if re.search(r"\bAction\s+\d+\s*:", reviewer_text, re.I):
        raise AssertionError("reviewer packet exposes an action-trace marker")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--packet-dir", type=Path, default=DEFAULT_PACKET_DIR)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--key-output", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--initialize-private-key", action="store_true")
    parser.add_argument("--rotate-private-key", action="store_true")
    args = parser.parse_args()
    for path in (args.packet_dir, args.manifest_output, args.key_output):
        _guard_output_path(path)

    audit_path = args.audit if args.audit.is_absolute() else args.repo_root / args.audit
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    contexts, source_metadata = load_task_contexts(audit, args.repo_root)
    key_path = args.key_output if args.key_output.is_absolute() else args.repo_root / args.key_output
    seed = load_or_create_private_seed(
        key_path,
        initialize=args.initialize_private_key,
        rotate=args.rotate_private_key,
    )
    rows, key = build_packet(audit, contexts, seed)
    packet_dir = args.packet_dir if args.packet_dir.is_absolute() else args.repo_root / args.packet_dir
    manifest_path = (
        args.manifest_output
        if args.manifest_output.is_absolute()
        else args.repo_root / args.manifest_output
    )
    rubric_path = args.repo_root / DEFAULT_ADJUDICATION_DIR / "rubric.md"
    outputs = write_outputs(
        rows,
        key,
        packet_dir,
        manifest_path,
        key_path,
        source_metadata,
        rubric_path,
    )
    _validate_private_outputs(outputs, seed)
    print(
        f"wrote two private reviewer forms for {len(rows)} cases; "
        f"public integrity manifest: {manifest_path}"
    )


if __name__ == "__main__":
    main()
