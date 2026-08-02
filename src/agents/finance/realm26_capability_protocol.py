"""Frozen guards and fresh-sample manifest for the REALM capability ladder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Sequence, Set

from .protocol_v2 import ProtocolError, _example_record, _sample, fingerprint, stratified_sample, write_stable_json


SCHEMA_VERSION = "realm26-capability-ladder-v1"
MANIFEST_SCHEMA_VERSION = "realm26-capability-manifest-v1"
PROTOCOL_ID = "realm26_capability_ladder"
DATASETS = ("finqa", "tatqa", "convfinqa")
FRAMEWORKS = ("static", "react")
TIERS = ("luna", "terra")
DEFAULT_PROTOCOL_PATH = Path(__file__).with_name("protocols") / f"{PROTOCOL_ID}.json"


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(protocol_path: Path, configured: str) -> Path:
    path = Path(configured)
    return (protocol_path.parent / path).resolve() if not path.is_absolute() else path.resolve()


def load_protocol(path: str | Path = DEFAULT_PROTOCOL_PATH, *, validate_artifacts: bool = True) -> Dict[str, Any]:
    protocol_path = Path(path).resolve()
    protocol = load_json(protocol_path)
    protocol["_path"] = str(protocol_path)
    validate_protocol(protocol)
    if validate_artifacts:
        validate_frozen_artifacts(protocol)
    return protocol


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("schema_version") != SCHEMA_VERSION or protocol.get("protocol_id") != PROTOCOL_ID:
        raise ProtocolError("Unexpected capability protocol schema or ID")
    if protocol.get("freeze_state") != "frozen":
        raise ProtocolError("Capability protocol must be frozen")
    if tuple(protocol.get("datasets", ())) != DATASETS or tuple(protocol.get("frameworks", ())) != FRAMEWORKS:
        raise ProtocolError("Dataset/framework order changed")
    if int(protocol.get("seed", -1)) != 20260801:
        raise ProtocolError("Sampling seed changed")
    sample = protocol.get("sample") or {}
    if sample.get("same_items_for_all_tiers") is not True or int(sample.get("per_dataset", -1)) != 50 or int(sample.get("total_items", -1)) != 150:
        raise ProtocolError("Frozen paired sample changed")
    expected_models = {
        "luna": {
            "requested_model_id": "openai/gpt-5.6-luna",
            "canonical_slug": "openai/gpt-5.6-luna-20260709",
            "hard_cap_usd": 4.99884544,
            "maximum_reserved_study_cost_usd": 1.385472,
            "maximum_reserved_call_cost_usd": 0.00115456,
        },
        "terra": {
            "requested_model_id": "openai/gpt-5.6-terra",
            "canonical_slug": "openai/gpt-5.6-terra-20260709",
            "hard_cap_usd": 15.0,
            "maximum_reserved_study_cost_usd": 13.85472,
            "maximum_reserved_call_cost_usd": 0.0115456,
        },
    }
    if protocol.get("models") != expected_models:
        raise ProtocolError("Capability tier bindings or budgets changed")
    if protocol.get("inference") != {
        "backend": "openrouter",
        "inter_call_delay_seconds": 0.1,
        "reasoning_effort": "none",
        "provider_routing": {
            "allow_fallbacks": False,
            "data_collection": "deny",
            "only": ["OpenAI"],
            "require_parameters": True,
        },
        "sampling_parameters_forbidden": ["temperature", "top_p"],
    }:
        raise ProtocolError("Inference contract changed")
    if protocol.get("retry_policy") != {"max_attempts_per_call": 1, "valid_outputs_are_immutable": True}:
        raise ProtocolError("One-attempt policy changed")
    if protocol.get("workflows") != {
        "answer_contract": "strict_json_finish_v1",
        "context_word_budget_per_call": 4096,
        "evidence_word_budget_per_item": 3000,
        "malformed_fallback": "UNKNOWN_without_retry",
        "max_output_tokens_per_call": 384,
        "max_retrieval_operations_per_item": 3,
        "react_action_policy": "first_model_action_must_be_search_v2",
        "react_max_steps": 7,
        "react_min_evidence_operations": 1,
        "react_min_model_calls": 2,
        "scorer_input": "canonical_parsed_answer_only",
        "static_model_calls": 1,
    }:
        raise ProtocolError("Shared workflow contract changed")
    analysis = protocol.get("analysis") or {}
    if int(analysis.get("bootstrap_resamples", -1)) != 10_000 or int(analysis.get("bootstrap_seed", -1)) != 20260801:
        raise ProtocolError("Bootstrap plan changed")
    if analysis.get("dataset_quality_metrics") != {
        "convfinqa": "native_scores.exact_match",
        "finqa": "native_scores.exact_match",
        "tatqa": "native_scores.f1",
    }:
        raise ProtocolError("Quality estimand changed")
    if protocol.get("tier_execution") != {
        "analysis_after_both_complete": True,
        "both_required": True,
        "manual_skip_forbidden": True,
        "order": ["luna", "terra"],
    }:
        raise ProtocolError("Tier execution plan changed")
    budget = protocol.get("budget") or {}
    if float(budget.get("failed_freeze_maximum_reservation_usd", -1)) != 0.00115456:
        raise ProtocolError("Failed-freeze reservation changed")
    if abs(sum(float(protocol["models"][tier]["hard_cap_usd"]) for tier in TIERS) + float(budget["failed_freeze_maximum_reservation_usd"]) - 20.0) > 1e-12:
        raise ProtocolError("Combined authorization exceeds or undershoots USD 20")
    if protocol.get("publication") != {
        "base_branch": "realm26/archival-short-paper",
        "branch": "realm26/luna-terra-capability",
        "remote": "origin",
    }:
        raise ProtocolError("Publication binding changed")
    if protocol.get("results") != {"root": "runs/realm26_capability_ladder", "tracked": False}:
        raise ProtocolError("Run-root binding changed")
    if protocol.get("manifest") != "manifests/realm26_capability_ladder/manifest.json":
        raise ProtocolError("Manifest binding changed")
    if protocol.get("model_snapshot") != "snapshots/realm26_capability_ladder_openrouter_catalog.json":
        raise ProtocolError("Model snapshot binding changed")
    if protocol.get("test_attestation") != "attestations/realm26_capability_ladder_tests.json":
        raise ProtocolError("Test attestation binding changed")


def _artifact_paths(protocol: Mapping[str, Any]) -> Dict[str, Path]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    finance = Path(__file__).parent
    repo = finance.parents[2]
    return {
        "analysis": finance / "analyze_realm26_capability_ladder.py",
        "attestation": resolve_path(protocol_path, str(protocol["test_attestation"])),
        "capability_llm": finance / "realm26_capability_llm.py",
        "data_adapter": finance / "realm26_harmonized_data.py",
        "executor": finance / "run_realm26_capability_ladder.py",
        "finance_statistics": finance / "finance_statistics.py",
        "manifest": resolve_path(protocol_path, str(protocol["manifest"])),
        "model_snapshot": resolve_path(protocol_path, str(protocol["model_snapshot"])),
        "protocol_guard": Path(__file__),
        "protocol_memo": repo / "paper" / "realm2026" / "capability_ladder_protocol.md",
        "protocol_utils": finance / "protocol_v2.py",
        "scorers": finance / "finance_scoring.py",
        "shared_methods": finance / "realm26_harmonized_v2_methods.py",
        "shared_prompts": finance / "realm26_harmonized_v2_prompts.py",
        "tests": repo / "tests" / "finance" / "test_realm26_capability_ladder.py",
        "telemetry": finance.parents[1] / "shared" / "llm_telemetry.py",
        "v2_manifest": resolve_path(protocol_path, str(protocol["exclusions"]["v2_manifest"])),
    }


def validate_frozen_artifacts(protocol: Mapping[str, Any]) -> None:
    expected = protocol.get("artifact_hashes") or {}
    paths = _artifact_paths(protocol)
    if set(expected) != set(paths):
        raise ProtocolError(f"Frozen artifact set mismatch: expected {sorted(paths)}, found {sorted(expected)}")
    actual = {name: sha256_file(path) for name, path in paths.items()}
    mismatches = {name: {"expected": expected[name], "actual": value} for name, value in actual.items() if expected[name] != value}
    if mismatches:
        raise ProtocolError(f"Frozen artifact hash mismatch: {mismatches}")
    snapshot = load_json(paths["model_snapshot"])
    if snapshot.get("requested_model_ids") != [protocol["models"][tier]["requested_model_id"] for tier in TIERS]:
        raise ProtocolError("Catalog snapshot model order changed")
    for tier in TIERS:
        row = snapshot["models"][tier]
        expected_model = protocol["models"][tier]
        if row.get("id") != expected_model["requested_model_id"] or row.get("canonical_slug") != expected_model["canonical_slug"]:
            raise ProtocolError(f"{tier}: catalog model identity mismatch")
        endpoint = row.get("openai_endpoint") or {}
        if endpoint.get("provider_name") != "OpenAI" or endpoint.get("tag") != "openai":
            raise ProtocolError(f"{tier}: frozen endpoint is not standard OpenAI")
        supported = set(endpoint.get("supported_parameters") or [])
        if not {"max_tokens", "reasoning_effort"}.issubset(supported):
            raise ProtocolError(f"{tier}: required parameters unavailable")
    attestation = load_json(paths["attestation"])
    if attestation.get("status") != "passed" or not attestation.get("commands"):
        raise ProtocolError("Pre-provider test attestation is incomplete")


def _source_paths(protocol: Mapping[str, Any]) -> Dict[str, Path]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    return {name: resolve_path(protocol_path, str(path)) for name, path in protocol["exclusions"].items() if name.endswith("_manifest") or name == "original_protocol"}


def _original_manifest_path(source_protocol_path: Path, dataset_id: str) -> Path:
    configured = load_json(source_protocol_path)["datasets"][dataset_id]["manifest"]
    path = Path(configured)
    return (source_protocol_path.parent / path).resolve() if not path.is_absolute() else path.resolve()


def _identifier_exclusions(protocol: Mapping[str, Any], dataset_id: str) -> Dict[str, Any]:
    """Read identifiers only from every prior partition, including sealed final."""

    paths = _source_paths(protocol)
    original = load_json(_original_manifest_path(paths["original_protocol"], dataset_id))
    prior_manifests = {
        name: load_json(path)["datasets"][dataset_id]
        for name, path in paths.items()
        if name != "original_protocol"
    }
    partitions = [original["development"], original["final"], *prior_manifests.values()]
    indices = {int(value) for value in original["development"]["indices"]} | {int(value) for value in original["final"]["indices"]}
    example_ids = {str(item["example_id"]) for partition in ("development", "final") for item in original[partition]["examples"]}
    for spec in prior_manifests.values():
        indices.update(int(item["index"]) for item in spec["examples"])
        example_ids.update(str(item["example_id"]) for item in spec["examples"])
    dialogue_hashes: Set[str] = set()
    if dataset_id == "convfinqa":
        for partition in ("development", "final"):
            dialogue_hashes.update(fingerprint(str(item.get("dialogue_id", ""))) for item in original[partition]["examples"])
        for spec in prior_manifests.values():
            dialogue_hashes.update(str(item["dialogue_hash"]) for item in spec["examples"])
    counts = {
        "original_development": len(original["development"]["indices"]),
        "sealed_final_identifiers": len(original["final"]["indices"]),
        "second_family": len(prior_manifests["second_family_manifest"]["examples"]),
        "harmonized_v1": len(prior_manifests["v1_manifest"]["examples"]),
        "harmonized_v2": len(prior_manifests["v2_manifest"]["examples"]),
        "total": len(indices),
    }
    return {
        "indices": indices,
        "example_ids": example_ids,
        "dialogue_hashes": dialogue_hashes,
        "counts": counts,
        "fingerprint": fingerprint({
            "indices": sorted(indices),
            "example_ids": sorted(example_ids),
            "dialogue_hashes": sorted(dialogue_hashes),
        }),
    }


def _selected_record(dataset_id: str, rows: Sequence[Mapping[str, Any]], idx: int) -> Dict[str, Any]:
    record = _example_record(dataset_id, rows, idx)
    record["item_hash"] = fingerprint(rows[idx])
    if dataset_id == "convfinqa":
        record.pop("dialogue_id", None)
        record["dialogue_hash"] = fingerprint(str(rows[idx].get("dialogue_id", "")))
    return record


def build_manifest(protocol: Mapping[str, Any], env_factory: Callable[[str], Any]) -> Dict[str, Any]:
    """Freeze fresh development identifiers without dereferencing excluded rows."""

    validate_protocol(protocol)
    per_dataset = int(protocol["sample"]["per_dataset"])
    seed = int(protocol["seed"])
    datasets: Dict[str, Any] = {}
    for dataset_id in DATASETS:
        rows = env_factory(dataset_id).rows
        excluded = _identifier_exclusions(protocol, dataset_id)
        reserved = set(excluded["indices"])
        candidates = sorted(set(range(len(rows))) - reserved)
        if dataset_id == "tatqa":
            reserved_contexts = {rows.context_for_index(idx) for idx in reserved}
            candidates = [idx for idx in candidates if rows.context_for_index(idx) not in reserved_contexts]
            selected = stratified_sample(candidates, rows, ("question_type", "answer_from"), per_dataset, seed, f"{PROTOCOL_ID}:{dataset_id}")
            policy = "seeded proportional answer_type x answer_source sample from wholly fresh contexts"
        elif dataset_id == "convfinqa":
            by_dialogue: Dict[str, int] = {}
            for idx in candidates:
                dialogue_hash = fingerprint(str(rows[idx].get("dialogue_id", "")))
                if dialogue_hash not in excluded["dialogue_hashes"]:
                    by_dialogue.setdefault(dialogue_hash, idx)
            selected = _sample(by_dialogue.values(), per_dataset, seed, f"{PROTOCOL_ID}:{dataset_id}:dialogues")
            policy = "one seeded turn per wholly fresh dialogue"
        else:
            selected = _sample(candidates, per_dataset, seed, f"{PROTOCOL_ID}:{dataset_id}")
            policy = "seeded sample after all prior and sealed-final identifier exclusions"
        records = [_selected_record(dataset_id, rows, idx) for idx in selected]
        if set(selected) & reserved or {item["example_id"] for item in records} & excluded["example_ids"]:
            raise ProtocolError(f"{dataset_id}: selected item overlaps excluded evidence")
        if dataset_id == "convfinqa":
            selected_dialogues = {item["dialogue_hash"] for item in records}
            if selected_dialogues & excluded["dialogue_hashes"] or len(selected_dialogues) != per_dataset:
                raise ProtocolError("ConvFinQA dialogue overlap or duplication")
        datasets[dataset_id] = {
            "candidate_count": len(candidates),
            "dataset_size": len(rows),
            "examples": records,
            "exclusion_counts": excluded["counts"],
            "exclusion_identifier_fingerprint": excluded["fingerprint"],
            "selection_policy": policy,
        }
    base_body: Dict[str, Any] = {
        "datasets": datasets,
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "seed": seed,
        "scope": "fresh_development_only_same_items_all_tiers",
    }
    replacement = protocol["sample"]["replacement"]
    if fingerprint(base_body) != replacement["failed_manifest_fingerprint"]:
        raise ProtocolError("Could not reproduce the superseded pre-result manifest")
    finqa_examples = base_body["datasets"]["finqa"]["examples"]
    consumed = [item for item in finqa_examples if item["example_id"] == replacement["consumed_example_id"] and int(item["index"]) == int(replacement["consumed_index"])]
    if len(consumed) != 1:
        raise ProtocolError("Consumed smoke item is absent or ambiguous")
    rows = env_factory("finqa").rows
    excluded = _identifier_exclusions(protocol, "finqa")
    base_indices = {int(item["index"]) for item in finqa_examples}
    replacement_candidates = sorted(set(range(len(rows))) - set(excluded["indices"]) - base_indices)
    replacement_index = _sample(
        replacement_candidates, 1, int(replacement["replacement_seed"]),
        f"{PROTOCOL_ID}:finqa:replacement",
    )[0]
    replacement_record = _selected_record("finqa", rows, replacement_index)
    base_body["datasets"]["finqa"]["examples"] = [
        replacement_record if item["example_id"] == replacement["consumed_example_id"] else item
        for item in finqa_examples
    ]
    base_body["datasets"]["finqa"]["selection_policy"] += "; one consumed smoke item replaced prospectively"
    base_body["replacement_audit"] = {
        "carried_forward_never_called_items": 149,
        "consumed_example_id": replacement["consumed_example_id"],
        "failed_freeze_commit": replacement["failed_freeze_commit"],
        "failed_manifest_fingerprint": replacement["failed_manifest_fingerprint"],
        "replacement_example_id": replacement_record["example_id"],
        "replacement_seed": replacement["replacement_seed"],
    }
    body = base_body
    body["manifest_fingerprint"] = fingerprint(body)
    return body


def load_manifest(protocol: Mapping[str, Any]) -> Dict[str, Any]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    manifest = load_json(resolve_path(protocol_path, str(protocol["manifest"])))
    supplied = manifest.pop("manifest_fingerprint", None)
    actual = fingerprint(manifest)
    manifest["manifest_fingerprint"] = supplied
    if supplied != actual or manifest.get("protocol_id") != PROTOCOL_ID:
        raise ProtocolError("Capability manifest fingerprint or protocol mismatch")
    return manifest


def validate_manifest_against_sources(protocol: Mapping[str, Any], manifest: Mapping[str, Any], env_factory: Callable[[str], Any]) -> None:
    replacement = protocol["sample"]["replacement"]
    if any(item["example_id"] == replacement["consumed_example_id"] for spec in manifest["datasets"].values() for item in spec["examples"]):
        raise ProtocolError("Consumed smoke item remains in replacement manifest")
    regenerated = build_manifest(protocol, env_factory)
    if regenerated != manifest:
        raise ProtocolError("Replacement manifest does not reproduce from sources")
    for dataset_id in DATASETS:
        rows = env_factory(dataset_id).rows
        spec = manifest["datasets"][dataset_id]
        excluded = _identifier_exclusions(protocol, dataset_id)
        if len(rows) != int(spec["dataset_size"]) or excluded["fingerprint"] != spec["exclusion_identifier_fingerprint"]:
            raise ProtocolError(f"{dataset_id}: dataset or exclusion drift")
        selected = [int(item["index"]) for item in spec["examples"]]
        if set(selected) & excluded["indices"]:
            raise ProtocolError(f"{dataset_id}: selected index overlaps prior evidence")
        for item in spec["examples"]:
            if dict(item) != _selected_record(dataset_id, rows, int(item["index"])):
                raise ProtocolError(f"{dataset_id}: selected development item drift")


def write_generated_manifest(protocol_path: str | Path, env_factory: Callable[[str], Any]) -> Path:
    path = Path(protocol_path).resolve()
    protocol = load_protocol(path, validate_artifacts=False)
    output = resolve_path(path, str(protocol["manifest"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    write_stable_json(output, build_manifest(protocol, env_factory))
    return output
