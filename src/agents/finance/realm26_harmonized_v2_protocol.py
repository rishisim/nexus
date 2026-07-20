"""Frozen protocol and manifest guards for the harmonized v2 corrective study."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Sequence, Set, Tuple

from .protocol_v2 import ProtocolError, _example_record, _sample, fingerprint, stratified_sample, write_stable_json


SCHEMA_VERSION = "realm26-harmonized-replication-v2"
MANIFEST_SCHEMA_VERSION = "realm26-harmonized-manifest-v2"
PROTOCOL_ID = "realm26_harmonized_static_react_v2"
DATASETS = ("finqa", "tatqa", "convfinqa")
FRAMEWORKS = ("static", "react")
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
        raise ProtocolError("Unexpected harmonized protocol schema or ID")
    if protocol.get("freeze_state") != "frozen":
        raise ProtocolError("Corrective protocol must be frozen")
    if tuple(protocol.get("datasets", ())) != DATASETS or tuple(protocol.get("frameworks", ())) != FRAMEWORKS:
        raise ProtocolError("Dataset/framework order is frozen")
    if int(protocol.get("sample", {}).get("per_dataset", -1)) != 50:
        raise ProtocolError("Exactly 50 fresh development items per dataset are frozen")
    if int(protocol.get("sample", {}).get("total_items", -1)) != 150:
        raise ProtocolError("Exactly 150 fresh development items are frozen")
    if int(protocol.get("seed", -1)) != 20260720:
        raise ProtocolError("Sampling seed is frozen")
    inference = protocol.get("inference") or {}
    if inference != {
        "backend": "openrouter",
        "model_id": "openai/gpt-4o-mini-2024-07-18",
        "provider_routing": {
            "allow_fallbacks": False,
            "data_collection": "deny",
            "only": ["OpenAI"],
            "require_parameters": True,
        },
        "temperature": 0,
        "top_p": 1.0,
        "inter_call_delay_seconds": 0.1,
    }:
        raise ProtocolError("Exact model/provider/sampling binding changed")
    if protocol.get("retry_policy") != {"max_attempts_per_call": 1, "valid_outputs_are_immutable": True}:
        raise ProtocolError("No-retry policy changed")
    if float(protocol.get("budget", {}).get("hard_cap_usd", -1)) != 5.0:
        raise ProtocolError("Provider hard cap must be exactly USD 5")
    workflows = protocol.get("workflows") or {}
    expected = {
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
    }
    if workflows != expected:
        raise ProtocolError("Harmonized answer/evidence/context workflow contract changed")
    analysis = protocol.get("analysis") or {}
    if int(analysis.get("bootstrap_resamples", -1)) != 10_000:
        raise ProtocolError("Bootstrap plan changed")
    if int(analysis.get("bootstrap_seed", -1)) != 20260720:
        raise ProtocolError("Bootstrap seed changed")
    if analysis.get("dataset_quality_metrics") != {
        "convfinqa": "native_scores.exact_match",
        "finqa": "native_scores.exact_match",
        "tatqa": "native_scores.f1",
    }:
        raise ProtocolError("Serialized dataset-native metric keys changed")
    if analysis.get("primary_serialized_metric") != "dataset_quality_metrics mapping above":
        raise ProtocolError("Primary serialized metric declaration changed")
    if analysis.get("directional_interpretation") != {
        "inconclusive": "primary 95% interval includes zero",
        "react_advantage": "primary react-minus-static 95% interval lower bound is greater than zero",
        "static_advantage": "primary react-minus-static 95% interval upper bound is less than zero",
    }:
        raise ProtocolError("Directional interpretation rule changed")
    if protocol.get("claims_scope") != "development_only_v2_corrective_study_separate_from_v1_and_original_gate":
        raise ProtocolError("Claims-scope separation changed")
    if protocol.get("publication") != {
        "base_branch": "realm26/archival-short-paper",
        "branch": "realm26/harmonized-replication-v2",
        "remote": "origin",
    }:
        raise ProtocolError("Public freeze branch/base binding changed")
    if protocol.get("exclusions") != {
        "allowed_final_use": "identifier_overlap_exclusion_only",
        "original_protocol": "finance_icaif26_v2.json",
        "second_family_manifest": "manifests/realm26_second_family_v1/manifest.json",
        "v1_manifest": "manifests/realm26_harmonized_static_react_v1/manifest.json",
    }:
        raise ProtocolError("Sample-exclusion sources changed")
    if protocol.get("results") != {
        "root": "results/finance/realm26_harmonized_static_react_v2_openai-gpt-4o-mini-2024-07-18",
        "tag": "realm26_harmonized_static_react_v2",
    }:
        raise ProtocolError("Result destination changed")
    if protocol.get("manifest") != "manifests/realm26_harmonized_static_react_v2/manifest.json":
        raise ProtocolError("Manifest binding changed")
    if protocol.get("test_attestation") != "attestations/realm26_harmonized_static_react_v2_tests.json":
        raise ProtocolError("Test-attestation binding changed")
    if protocol.get("smoke") != {
        "dataset": "finqa",
        "item_ordinal": 0,
        "outcomes_must_not_be_summarized_before_full_run": True,
        "process_checks": {
            "forbid_answer_or_score_access": True,
            "react_evidence_word_count_minimum": 1,
            "react_first_model_action": "Search",
            "react_llm_call_count_minimum": 2,
            "react_parse_status": "ok",
            "react_retrieval_operation_count_minimum": 1,
            "static_llm_call_count": 1,
        },
        "runs_both_workflows": True,
    }:
        raise ProtocolError("Smoke manipulation check changed")


def _artifact_paths(protocol: Mapping[str, Any]) -> Dict[str, Path]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    finance = Path(__file__).parent
    shared = finance.parents[1] / "shared"
    return {
        "analysis": finance / "analyze_realm26_harmonized_v2_replication.py",
        "attestation": resolve_path(protocol_path, str(protocol["test_attestation"])),
        "base_methods": finance / "finance_methods.py",
        "executor": finance / "run_realm26_harmonized_v2_replication.py",
        "finance_env": finance / "finance_env.py",
        "finance_statistics": finance / "finance_statistics.py",
        "finance_utils": finance / "finance_utils.py",
        "llm_telemetry": shared / "llm_telemetry.py",
        "llm_wrapper": shared / "llm.py",
        "manifest": resolve_path(protocol_path, str(protocol["manifest"])),
        "methods": finance / "realm26_harmonized_v2_methods.py",
        "data_adapter": finance / "realm26_harmonized_data.py",
        "model_snapshot": resolve_path(protocol_path, str(protocol["model_snapshot"])),
        "prompts": finance / "realm26_harmonized_v2_prompts.py",
        "protocol_memo": finance.parents[2] / "paper" / "realm2026" / "harmonized_replication_v2_protocol.md",
        "pytest_config": finance.parents[2] / "pytest.ini",
        "protocol_guard": Path(__file__),
        "protocol_utils": finance / "protocol_v2.py",
        "runner_telemetry": finance / "run_finance_experiments.py",
        "scorers": finance / "finance_scoring.py",
        "tests": finance.parents[2] / "tests" / "finance" / "test_realm26_harmonized_v2_replication.py",
        "v1_harmonized_methods": finance / "realm26_harmonized_methods.py",
        "v1_harmonized_prompts": finance / "realm26_harmonized_prompts.py",
        "v1_manifest": resolve_path(protocol_path, str(protocol["exclusions"]["v1_manifest"])),
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
    if snapshot.get("model_id") != protocol["inference"]["model_id"]:
        raise ProtocolError("Model snapshot slug mismatch")
    endpoint = snapshot.get("endpoint") or {}
    if endpoint.get("provider_name") != "OpenAI" or endpoint.get("tag") != "openai":
        raise ProtocolError("Frozen endpoint is not OpenAI")
    if not {"temperature", "stop", "max_tokens"}.issubset(set(endpoint.get("supported_parameters") or [])):
        raise ProtocolError("Frozen endpoint lacks required parameters")
    attestation = load_json(paths["attestation"])
    if attestation.get("status") != "passed" or not attestation.get("commands"):
        raise ProtocolError("Pre-provider test attestation is incomplete")


def _source_paths(protocol: Mapping[str, Any]) -> Tuple[Path, Path, Path]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    return (
        resolve_path(protocol_path, str(protocol["exclusions"]["original_protocol"])),
        resolve_path(protocol_path, str(protocol["exclusions"]["second_family_manifest"])),
        resolve_path(protocol_path, str(protocol["exclusions"]["v1_manifest"])),
    )


def _original_manifest_path(source_protocol_path: Path, dataset_id: str) -> Path:
    source = load_json(source_protocol_path)
    configured = source["datasets"][dataset_id]["manifest"]
    path = Path(configured)
    return (source_protocol_path.parent / path).resolve() if not path.is_absolute() else path.resolve()


def _identifier_exclusions(protocol: Mapping[str, Any], dataset_id: str) -> Dict[str, Any]:
    """Read only identifier fields from sealed-final manifests for exclusion."""

    source_protocol_path, second_path, v1_path = _source_paths(protocol)
    original = load_json(_original_manifest_path(source_protocol_path, dataset_id))
    second = load_json(second_path)["datasets"][dataset_id]
    v1_manifest = load_json(v1_path)
    v1 = v1_manifest["datasets"][dataset_id]
    development_indices = {int(value) for value in original["development"]["indices"]}
    final_indices = {int(value) for value in original["final"]["indices"]}
    second_indices = {int(item["index"]) for item in second["examples"]}
    v1_indices = {int(item["index"]) for item in v1["examples"]}
    development_ids = {str(item["example_id"]) for item in original["development"]["examples"]}
    final_ids = {str(item["example_id"]) for item in original["final"]["examples"]}
    second_ids = {str(item["example_id"]) for item in second["examples"]}
    v1_ids = {str(item["example_id"]) for item in v1["examples"]}
    dialogue_hashes: Set[str] = set()
    if dataset_id == "convfinqa":
        for partition in ("development", "final"):
            dialogue_hashes.update(
                fingerprint(str(item.get("dialogue_id", "")))
                for item in original[partition]["examples"]
            )
        dialogue_hashes.update(str(item["dialogue_hash"]) for item in second["examples"])
        dialogue_hashes.update(str(item["dialogue_hash"]) for item in v1["examples"])
    return {
        "indices": development_indices | final_indices | second_indices | v1_indices,
        "example_ids": development_ids | final_ids | second_ids | v1_ids,
        "dialogue_hashes": dialogue_hashes,
        "counts": {
            "original_development": len(development_indices),
            "sealed_final_identifiers": len(final_indices),
            "second_family": len(second_indices),
            "harmonized_v1": len(v1_indices),
            "total": len(development_indices | final_indices | second_indices | v1_indices),
        },
        "fingerprint": fingerprint({
            "development_indices": sorted(development_indices),
            "final_indices": sorted(final_indices),
            "second_indices": sorted(second_indices),
            "v1_indices": sorted(v1_indices),
            "dialogue_hashes": sorted(dialogue_hashes),
        }),
        "original_manifest_fingerprint": original["manifest_fingerprint"],
        "second_manifest_fingerprint": load_json(second_path)["manifest_fingerprint"],
        "v1_manifest_fingerprint": v1_manifest["manifest_fingerprint"],
    }


def _selected_record(dataset_id: str, rows: Sequence[Mapping[str, Any]], idx: int) -> Dict[str, Any]:
    record = _example_record(dataset_id, rows, idx)
    record["item_hash"] = fingerprint(rows[idx])
    if dataset_id == "convfinqa":
        record.pop("dialogue_id", None)
        record["dialogue_hash"] = fingerprint(str(rows[idx].get("dialogue_id", "")))
    return record


def build_manifest(protocol: Mapping[str, Any], env_factory: Callable[[str], Any]) -> Dict[str, Any]:
    """Select fresh development rows without dereferencing any final row content."""

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
            if not hasattr(rows, "context_for_index"):
                raise ProtocolError("TAT-QA authoring requires the lazy context-safe adapter")
            reserved_contexts = {rows.context_for_index(idx) for idx in reserved}
            candidates = [idx for idx in candidates if rows.context_for_index(idx) not in reserved_contexts]
            selected = stratified_sample(candidates, rows, ("question_type", "answer_from"), per_dataset, seed, f"{PROTOCOL_ID}:{dataset_id}")
            policy = "seeded proportional answer_type x answer_source sample from contexts containing no original, second-family, v1, or final identifiers"
        elif dataset_id == "convfinqa":
            by_dialogue: Dict[str, int] = {}
            for idx in candidates:
                dialogue_hash = fingerprint(str(rows[idx].get("dialogue_id", "")))
                if dialogue_hash not in excluded["dialogue_hashes"]:
                    by_dialogue.setdefault(dialogue_hash, idx)
            selected = _sample(by_dialogue.values(), per_dataset, seed, f"{PROTOCOL_ID}:{dataset_id}:dialogues")
            policy = "one seeded turn per new dialogue after original, second-family, v1, and final identifier exclusions"
        else:
            selected = _sample(candidates, per_dataset, seed, f"{PROTOCOL_ID}:{dataset_id}")
            policy = "seeded sample after original, second-family, v1, and final identifier exclusions"
        records = [_selected_record(dataset_id, rows, idx) for idx in selected]
        if set(selected) & reserved:
            raise ProtocolError(f"{dataset_id}: selected index overlaps excluded evidence")
        if {item["example_id"] for item in records} & excluded["example_ids"]:
            raise ProtocolError(f"{dataset_id}: selected example ID overlaps excluded evidence")
        if dataset_id == "convfinqa":
            selected_dialogues = {item["dialogue_hash"] for item in records}
            if selected_dialogues & excluded["dialogue_hashes"] or len(selected_dialogues) != per_dataset:
                raise ProtocolError("convfinqa: selected dialogue overlaps or is duplicated")
        datasets[dataset_id] = {
            "candidate_count": len(candidates),
            "dataset_size": len(rows),
            "examples": records,
            "exclusion_counts": excluded["counts"],
            "exclusion_identifier_fingerprint": excluded["fingerprint"],
            "original_manifest_fingerprint": excluded["original_manifest_fingerprint"],
            "second_manifest_fingerprint": excluded["second_manifest_fingerprint"],
            "v1_manifest_fingerprint": excluded["v1_manifest_fingerprint"],
            "selection_policy": policy,
        }
    body: Dict[str, Any] = {
        "datasets": datasets,
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "seed": seed,
        "scope": "fresh_development_only",
    }
    body["manifest_fingerprint"] = fingerprint(body)
    return body


def load_manifest(protocol: Mapping[str, Any]) -> Dict[str, Any]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    manifest = load_json(resolve_path(protocol_path, str(protocol["manifest"])))
    supplied = manifest.pop("manifest_fingerprint", None)
    actual = fingerprint(manifest)
    manifest["manifest_fingerprint"] = supplied
    if supplied != actual or manifest.get("protocol_id") != PROTOCOL_ID:
        raise ProtocolError("Harmonized manifest fingerprint or protocol mismatch")
    return manifest


def validate_manifest_against_sources(protocol: Mapping[str, Any], manifest: Mapping[str, Any], env_factory: Callable[[str], Any]) -> None:
    """Validate selected development rows and identifier exclusions before inference."""

    for dataset_id in DATASETS:
        rows = env_factory(dataset_id).rows
        spec = manifest["datasets"][dataset_id]
        excluded = _identifier_exclusions(protocol, dataset_id)
        if len(rows) != int(spec["dataset_size"]):
            raise ProtocolError(f"{dataset_id}: dataset size drift")
        if excluded["fingerprint"] != spec["exclusion_identifier_fingerprint"]:
            raise ProtocolError(f"{dataset_id}: exclusion identifier drift")
        selected = [int(item["index"]) for item in spec["examples"]]
        if set(selected) & excluded["indices"]:
            raise ProtocolError(f"{dataset_id}: selected index overlaps excluded evidence")
        for item in spec["examples"]:
            if dict(item) != _selected_record(dataset_id, rows, int(item["index"])):
                raise ProtocolError(f"{dataset_id}: selected development item drift")


def write_generated_manifest(protocol_path: str | Path, env_factory: Callable[[str], Any]) -> Path:
    path = Path(protocol_path).resolve()
    protocol = load_protocol(path, validate_artifacts=False)
    output = resolve_path(path, str(protocol["manifest"]))
    write_stable_json(output, build_manifest(protocol, env_factory))
    return output
