#!/usr/bin/env python3
"""Assemble the provider-free, double-blind REALM review artifact.

This maintainer script reads the current development sources and saved result
rows.  It never opens datasets, final examples, or provider clients.  Result
rows are reduced to an explicit metric/telemetry whitelist before release.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = Path(__file__).resolve().parent
ORIGINAL_RUN = "finance_icaif26_v2_development_google-gemini-2.5-flash_dev-20260709"
REPLICATION_RUN = "realm26_second_family_v1_openai-gpt-4o-mini-2024-07-18"
PRIMARY_DATASETS = ("finqa", "tatqa", "convfinqa")
PRIMARY_SYSTEMS = ("direct", "cot", "nexus", "react", "selective")


def stable(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> object:
    if not path.is_file():
        raise SystemExit(f"missing source: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def safe_score_row(study: str, row: dict[str, object]) -> dict[str, object]:
    """Return only reviewer-safe metrics and telemetry from one saved row."""
    native = row.get("native_scores")
    if not isinstance(native, dict):
        raise SystemExit("saved result row is missing native_scores")
    dataset = str(row["dataset"])
    primary_metric = "f1" if dataset == "tatqa" else "exact_match"
    cost_keys = ("provider_cost_usd", "effective_cost_usd", "estimated_cost_usd")
    cost_source = next((key for key in cost_keys if row.get(key) is not None), None)
    if cost_source is None:
        raise SystemExit("saved result row is missing cost telemetry")
    return {
        "study": study,
        "dataset": dataset,
        "example_id": str(row["example_id"]),
        "system": str(row["framework"]),
        "status": str(row["status"]),
        "primary_metric": primary_metric,
        "primary_score": native.get(primary_metric),
        "exact_match": native.get("exact_match"),
        "f1": native.get("f1"),
        "llm_calls": row.get("llm_call_count"),
        "retrieval_operations": row.get("retrieval_operation_count"),
        "retry_count": row.get("retry_count"),
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
        "total_tokens": row.get("total_tokens"),
        "cost_usd": row[cost_source],
        "cost_source": cost_source,
        "latency_ms": row.get("latency_ms"),
        "route": row.get("route_selected"),
        "resolved_model": row.get("resolved_model"),
    }


def score_ledger() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for dataset in PRIMARY_DATASETS:
        for system in PRIMARY_SYSTEMS:
            source = (
                ROOT
                / "results"
                / "finance"
                / dataset
                / ORIGINAL_RUN
                / system
                / "results.json"
            )
            payload = read_json(source)
            if not isinstance(payload, list) or len(payload) != 50:
                raise SystemExit(f"expected 50 original rows: {source}")
            rows.extend(safe_score_row("original_development", row) for row in payload)

    for system in ("nexus", "react", "selective"):
        source = (
            ROOT
            / "results"
            / "finance"
            / "financebench"
            / ORIGINAL_RUN
            / system
            / "results.json"
        )
        payload = read_json(source)
        if not isinstance(payload, list) or len(payload) != 50:
            raise SystemExit(f"expected 50 FinanceBench rows: {source}")
        rows.extend(safe_score_row("original_development", row) for row in payload)

    for dataset in PRIMARY_DATASETS:
        for system in ("nexus", "react"):
            source = (
                ROOT
                / "results"
                / "finance"
                / REPLICATION_RUN
                / dataset
                / system
                / "results.json"
            )
            payload = read_json(source)
            if not isinstance(payload, list) or len(payload) != 25:
                raise SystemExit(f"expected 25 replication rows: {source}")
            rows.extend(safe_score_row("second_family_replication", row) for row in payload)

    rows.sort(
        key=lambda row: (
            row["study"],
            row["dataset"],
            row["system"],
            row["example_id"],
        )
    )
    return {
        "schema_version": "realm-anonymous-score-ledger-v1",
        "scope": (
            "development-only scored outcomes and telemetry; no answer, gold, "
            "prompt, evidence, or trace text"
        ),
        "row_count": len(rows),
        "rows": rows,
    }


def main() -> None:
    snapshots = ARTIFACT / "snapshots"
    manifests = ARTIFACT / "development_manifests"
    snapshots.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)

    source_files = {
        "protocol": ROOT / "src/agents/finance/protocols/finance_icaif26_v2.json",
        "prompts": ROOT / "src/agents/finance/finance_prompts.py",
        "method_prompts": ROOT / "src/agents/finance/method_prompts.py",
        "scorer": ROOT / "src/agents/finance/finance_scoring.py",
        "price_table": ROOT / "src/shared/llm_telemetry.py",
        "router": ROOT / "src/agents/finance/protocols/artifacts/selective_router.json",
        "model_snapshot": ROOT / "results/finance/finqa/finance_icaif26_v2_development_google-gemini-2.5-flash_dev-20260709/model_snapshot.json",
        "development_aggregation": ROOT / "paper/icaif2026/artifacts/development_summary.json",
    }
    for name, source in source_files.items():
        if not source.is_file():
            raise SystemExit(f"missing source: {source}")
        target = snapshots / source.name
        shutil.copyfile(source, target)

    additional_snapshots = {
        "paired_statistics.json": ROOT / "paper/realm2026/artifacts/paired_statistics.json",
        "realm26_second_family_model_snapshot.json": ROOT
        / "src/agents/finance/protocols/snapshots/realm26_second_family_v1_openai-gpt-4o-mini-2024-07-18.json",
    }
    for target_name, source in additional_snapshots.items():
        if not source.is_file():
            raise SystemExit(f"missing source: {source}")
        shutil.copyfile(source, snapshots / target_name)

    replication = read_json(
        ROOT / "paper/realm2026/artifacts/second_family_replication_v1.json"
    )
    if not isinstance(replication, dict):
        raise SystemExit("replication analysis must be a JSON object")
    for key in ("analysis_fingerprint", "manifest_fingerprint", "pre_result_commit"):
        replication.pop(key, None)
    replication["freeze_provenance"] = (
        "prospective public timestamp verified; identity-bearing reference omitted "
        "from double-blind review artifact"
    )
    (snapshots / "second_family_replication_v1.json").write_text(
        stable(replication), encoding="utf-8"
    )

    replication_protocol = read_json(
        ROOT / "src/agents/finance/protocols/realm26_second_family_v1.json"
    )
    if not isinstance(replication_protocol, dict):
        raise SystemExit("replication protocol must be a JSON object")
    frozen_hashes = replication_protocol.get("artifact_hashes", {})
    replication_protocol["artifact_hashes"] = {
        "components": sorted(frozen_hashes) if isinstance(frozen_hashes, dict) else [],
        "status": "verified before calls; values omitted for double-blind review",
    }
    (snapshots / "realm26_second_family_v1.json").write_text(
        stable(replication_protocol), encoding="utf-8"
    )

    replication_manifest = read_json(
        ROOT
        / "src/agents/finance/protocols/manifests/realm26_second_family_v1/manifest.json"
    )
    if not isinstance(replication_manifest, dict):
        raise SystemExit("replication manifest must be a JSON object")
    replication_manifest.pop("manifest_fingerprint", None)
    (snapshots / "realm26_second_family_manifest.json").write_text(
        stable(replication_manifest), encoding="utf-8"
    )

    (snapshots / "score_ledger.json").write_text(
        stable(score_ledger()), encoding="utf-8"
    )

    fairness = json.loads(
        (ROOT / "paper/realm2026/artifacts/fairness_audit.json").read_text(
            encoding="utf-8"
        )
    )
    fairness_provenance = fairness["provenance"]
    fairness_summary = {
        key: fairness[key]
        for key in (
            "schema_version",
            "scope",
            "fairness_matrix",
            "sampling",
            "summary",
            "limitations",
        )
    }
    fairness_summary["provenance"] = {
        "development_run": fairness_provenance["development_run"],
        "labels": fairness_provenance["labels"],
        "input_integrity": "verified internally; identity-linkable hashes omitted",
    }
    (snapshots / "fairness_audit_summary.json").write_text(
        stable(fairness_summary), encoding="utf-8"
    )

    for source in sorted((ROOT / "src/agents/finance/protocols/manifests").glob("*.json")):
        payload = json.loads(source.read_text(encoding="utf-8"))
        dev_only = dict(payload)
        dev_only.pop("final", None)
        dev_only["artifact_partition"] = "development_only"
        dev_only["final_partition"] = "excluded"
        target = manifests / source.name
        target.write_text(stable(dev_only), encoding="utf-8")

    entries = []
    for path in sorted(ARTIFACT.rglob("*")):
        if path.is_file() and path.name not in {"checksums.sha256", "manifest.json"}:
            entries.append({"path": path.relative_to(ARTIFACT).as_posix(), "sha256": sha256(path)})
    manifest = {
        "schema": "realm-anonymous-artifact-v1",
        "purpose": "provider-free audit of recorded development statistics and protocol inputs",
        "partition": "development_only",
        "sealed_final_partition": "excluded",
        "provider_calls": False,
        "entries": entries,
        "source_freeze": "anonymous-review-source-freeze-v1",
    }
    (ARTIFACT / "manifest.json").write_text(stable(manifest), encoding="utf-8")

    # Recompute after manifest creation; checksums excludes itself by design.
    entries = []
    for path in sorted(ARTIFACT.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            entries.append(f"{sha256(path)}  {path.relative_to(ARTIFACT).as_posix()}")
    (ARTIFACT / "checksums.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
