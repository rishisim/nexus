#!/usr/bin/env python3
"""Build the provider-free, blinded REALM 2026 adjudication packet.

The input is the committed fairness audit only.  This module never opens a
dataset manifest, final partition, result directory, or provider client.
The public packet intentionally contains no method names or deterministic
audit labels.  The A/B key is written separately and must not be distributed
with the reviewer packet.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SEED = "realm2026-blinded-author-adjudication-v1"
DEFAULT_AUDIT = Path("paper/realm2026/artifacts/fairness_audit.json")
DEFAULT_PACKET_DIR = Path("paper/realm2026/adjudication")
DEFAULT_KEY = DEFAULT_PACKET_DIR / "private" / "ab_key.json"
FORBIDDEN_PATH_PARTS = {"final", "sealed-final", "results", "outcomes", "traces"}
FORBIDDEN_PUBLIC_TERMS = re.compile(r"\b(?:static|react|nexus|framework|one_sided|both_wrong)\b", re.I)


def _stable_hash(seed: str, item_id: str, role: str) -> str:
    return hashlib.sha256(f"{seed}:{item_id}:{role}".encode()).hexdigest()


def _guard_path(path: Path) -> None:
    lowered = {part.lower() for part in path.parts}
    if lowered & FORBIDDEN_PATH_PARTS:
        raise ValueError(f"refusing partition/result-like path: {path}")


def _redact(value: Any) -> str:
    text = "" if value is None else str(value)
    return FORBIDDEN_PUBLIC_TERMS.sub("[redacted]", text)


def _trace_context(evidence: Mapping[str, Any]) -> str:
    actions = evidence.get("actions") or []
    action_text = " | ".join(f"{a.get('step')}: {_redact(a.get('action'))}" for a in actions)
    queries = evidence.get("static_search_queries") or []
    query_text = " | ".join(_redact(q) for q in queries)
    return json.dumps(
        {
            "submitted_answer": _redact(evidence.get("answer")),
            "actions": action_text,
            "search_queries": query_text,
            "trace_excerpt": _redact(evidence.get("trace_excerpt")),
            "calls": evidence.get("llm_calls"),
            "retrieval_operations": evidence.get("retrieval_operations"),
            "retry_count": evidence.get("retry_count"),
            "trace_sha256": evidence.get("trace_sha256"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def build_packet(audit: Mapping[str, Any], seed: str = SEED) -> tuple[list[dict[str, str]], dict[str, Any]]:
    scope = audit.get("scope", {})
    if scope.get("sealed_final_partition_accessed") is not False:
        raise ValueError("audit is not development-only")
    if scope.get("external_provider_calls") != 0:
        raise ValueError("audit records provider calls")
    items = [item for item in audit.get("trace_items", []) if item.get("manual_review_required") is True]
    expected = audit.get("summary", {}).get("manual_review_count")
    if len(items) != 51 or expected != 51:
        raise ValueError(f"expected exactly 51 frozen manual-review items, got {len(items)}")

    rows: list[dict[str, str]] = []
    key: dict[str, Any] = {"seed": seed, "items": {}}
    for item in items:
        item_id = str(item["item_id"])
        ev = item["trace_evidence"]
        systems = ["static_nexus", "react"]
        systems.sort(key=lambda system: _stable_hash(seed, item_id, system))
        key["items"][item_id] = {"A": systems[0], "B": systems[1]}
        row = {
            "case_id": item_id,
            "dataset": str(item["dataset"]),
            "example_id": str(item["example_id"]),
            "reference_answer": _redact(item.get("ground_truth")),
            "system_a_context": _trace_context(ev[systems[0]]),
            "system_b_context": _trace_context(ev[systems[1]]),
            "reviewer_1_a_correctness": "",
            "reviewer_1_a_unit_scale_validity": "",
            "reviewer_1_a_failure_cause": "",
            "reviewer_1_a_confidence": "",
            "reviewer_1_a_notes": "",
            "reviewer_1_b_correctness": "",
            "reviewer_1_b_unit_scale_validity": "",
            "reviewer_1_b_failure_cause": "",
            "reviewer_1_b_confidence": "",
            "reviewer_1_b_notes": "",
            "reviewer_2_a_correctness": "",
            "reviewer_2_a_unit_scale_validity": "",
            "reviewer_2_a_failure_cause": "",
            "reviewer_2_a_confidence": "",
            "reviewer_2_a_notes": "",
            "reviewer_2_b_correctness": "",
            "reviewer_2_b_unit_scale_validity": "",
            "reviewer_2_b_failure_cause": "",
            "reviewer_2_b_confidence": "",
            "reviewer_2_b_notes": "",
            "disagreement_resolution": "",
        }
        rows.append(row)
    rows.sort(key=lambda row: row["case_id"])
    key["case_count"] = len(rows)
    key["packet_case_ids_sha256"] = hashlib.sha256("\n".join(r["case_id"] for r in rows).encode()).hexdigest()
    return rows, key


def write_outputs(rows: list[dict[str, str]], key: dict[str, Any], packet_csv: Path, packet_md: Path, key_path: Path) -> None:
    for path in (packet_csv, packet_md, key_path):
        _guard_path(path)
    packet_csv.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    with packet_csv.open("w", newline="", encoding="utf-8") as handle:
        # Keep a nonblank field last so git's whitespace checker does not
        # mistake the required blank adjudication cells for trailing spaces.
        fieldnames = [name for name in rows[0] if name != "case_id"] + ["case_id"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# REALM 2026 blinded author-adjudication packet",
        "",
        "**Codex must not fill any human labels in this packet.** These 51 cases are a frozen, provider-free, development-only manual-review queue. The 900-example final partition was not opened or executed.",
        "",
        "## Instructions for reviewers",
        "",
        "1. Two authors independently review every case. Do not discuss cases or inspect the private A/B key during independent review.",
        "2. For System A and System B, label correctness, unit/scale validity, failure cause, and confidence; add concise notes. Use `unknown` when evidence is insufficient.",
        "3. Correctness is semantic against the reference, not string matching. Check sign, period, unit, scale, arithmetic, and unsupported extra claims.",
        "4. After both independent passes, reveal the key only to the adjudicator. Resolve disagreements by returning to the reference and supplied trace context, recording the decision and rationale in `disagreement_resolution`.",
        "5. Preserve the blank-label source packet. Any reported reclassification must state that it is author adjudication of development examples and must not replace official scores silently.",
        "",
        "Suggested controlled vocabularies: correctness=`correct`/`incorrect`/`uncertain`; unit/scale=`valid`/`invalid`/`uncertain`; confidence=`high`/`medium`/`low`. Failure cause may be free text, such as retrieval, arithmetic, period, unit/scale, answer contract, or other.",
        "",
        f"Deterministic A/B assignment seed: `{key['seed']}` (do not use it to infer system identity). Case count: {len(rows)}.",
        "",
        "The CSV is the authoritative fillable packet; each case below repeats the reference and the minimum trace context for A/B.",
        "",
    ]
    for row in rows:
        lines += [
            f"## {row['case_id']}",
            "",
            f"**Reference answer:** {row['reference_answer']}",
            "",
            f"### System A\n```json\n{row['system_a_context']}\n```",
            "",
            f"### System B\n```json\n{row['system_b_context']}\n```",
            "",
            "Labels are blank in the CSV for both reviewers.",
            "",
        ]
    packet_md.write_text("\n".join(lines), encoding="utf-8")
    key_path.write_text(json.dumps(key, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--packet-csv", type=Path, default=DEFAULT_PACKET_DIR / "blinded_packet.csv")
    parser.add_argument("--packet-md", type=Path, default=DEFAULT_PACKET_DIR / "blinded_packet.md")
    parser.add_argument("--key-output", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--seed", default=SEED)
    args = parser.parse_args()
    for path in (args.audit, args.packet_csv, args.packet_md, args.key_output):
        _guard_path(path)
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    rows, key = build_packet(audit, args.seed)
    write_outputs(rows, key, args.packet_csv, args.packet_md, args.key_output)
    public = args.packet_csv.read_text(encoding="utf-8") + args.packet_md.read_text(encoding="utf-8")
    if FORBIDDEN_PUBLIC_TERMS.search(public):
        raise AssertionError("public packet leaks method/audit terminology")
    print(f"wrote {len(rows)} blinded cases; private key: {args.key_output}")


if __name__ == "__main__":
    main()
