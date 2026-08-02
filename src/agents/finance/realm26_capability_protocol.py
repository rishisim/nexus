"""Frozen guards and fresh-sample manifest for the REALM capability ladder."""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from .protocol_v2 import ProtocolError, _example_record, _sample, fingerprint, stratified_sample, write_stable_json


SCHEMA_VERSION = "realm26-capability-ladder-v1"
MANIFEST_SCHEMA_VERSION = "realm26-capability-manifest-v1"
PROTOCOL_ID = "realm26_capability_ladder"
DATASETS = ("finqa", "tatqa", "convfinqa")
FRAMEWORKS = ("static", "react")
TIERS = ("control", "luna", "terra")
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
    if int(protocol.get("seed", -1)) != 20260802:
        raise ProtocolError("Sampling seed changed")
    sample = protocol.get("sample") or {}
    if (
        sample.get("same_items_for_all_tiers") is not True
        or int(sample.get("per_dataset", -1)) != 50
        or int(sample.get("total_items", -1)) != 150
        or int(sample.get("schedule_seed", -1)) < 0
    ):
        raise ProtocolError("Frozen paired sample changed")
    models = protocol.get("models")
    expected_ids = {
        "control": "openai/gpt-4o-mini",
        "luna": "openai/gpt-5.6-luna",
        "terra": "openai/gpt-5.6-terra",
    }
    if not isinstance(models, Mapping) or tuple(models) != TIERS:
        raise ProtocolError("Capability tiers must be ordered control, luna, terra")
    for tier in TIERS:
        model = models[tier]
        if not isinstance(model, Mapping) or model.get("requested_model_id") != expected_ids[tier]:
            raise ProtocolError(f"{tier}: requested model binding changed")
        if not isinstance(model.get("canonical_slug"), str) or not model["canonical_slug"].startswith(expected_ids[tier]):
            raise ProtocolError(f"{tier}: canonical catalog binding is missing")
        for field in (
            "maximum_reserved_call_cost_usd",
            "maximum_reserved_probe_cost_usd",
            "maximum_reserved_study_cost_usd",
        ):
            value = model.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) < 20:
                raise ProtocolError(f"{tier}: invalid {field}")
        if float(model["maximum_reserved_study_cost_usd"]) < 1200 * float(model["maximum_reserved_call_cost_usd"]):
            raise ProtocolError(f"{tier}: study reservation does not cover every allowed call")

    inference = protocol.get("inference") or {}
    if {
        "backend": inference.get("backend"),
        "provider_routing": inference.get("provider_routing"),
        "reasoning_effort_by_tier": inference.get("reasoning_effort_by_tier"),
        "request_seed": inference.get("request_seed"),
        "sampling_parameters_forbidden": inference.get("sampling_parameters_forbidden"),
        "structured_action_decoding": inference.get("structured_action_decoding"),
    } != {
        "backend": "openrouter",
        "provider_routing": {
            "allow_fallbacks": False,
            "data_collection": "deny",
            "only": ["OpenAI"],
            "require_parameters": True,
        },
        "reasoning_effort_by_tier": {"control": None, "luna": "none", "terra": "none"},
        "request_seed": 20260802,
        "sampling_parameters_forbidden": ["temperature", "top_p"],
        "structured_action_decoding": "strict_compact_json_schema_by_framework_and_react_step",
    }:
        raise ProtocolError("Inference contract changed")
    if not isinstance(inference.get("reasoning_semantics"), str) or not inference["reasoning_semantics"].strip():
        raise ProtocolError("Authorized reasoning-parameter exception is undocumented")
    if float(inference.get("inter_call_delay_seconds", -1)) != 0.1:
        raise ProtocolError("Frozen inter-call delay changed")
    if protocol.get("retry_policy") != {"max_attempts_per_call": 1, "valid_outputs_are_immutable": True}:
        raise ProtocolError("One-attempt policy changed")
    workflow = protocol.get("workflows") or {}
    required_workflow = {
        "context_word_budget_per_call": 4096,
        "evidence_word_budget_per_item": 3000,
        "malformed_output_policy": "prospective_stop_without_retry",
        "max_output_tokens_per_call": 384,
        "context_utf8_byte_budget_per_call": 8192,
        "max_retrieval_operations_per_item": 3,
        "react_action_policy": "first_model_action_must_be_search_v2",
        "react_max_steps": 7,
        "react_min_evidence_operations": 1,
        "react_min_model_calls": 2,
        "scorer_input": "canonical_parsed_answer_only",
        "static_model_calls": 1,
    }
    if any(workflow.get(key) != value for key, value in required_workflow.items()):
        raise ProtocolError("Shared workflow contract changed")
    if workflow.get("answer_contract") != "compact_action_argument_answer_v1":
        raise ProtocolError("Compact structured action contract is not frozen")
    analysis = protocol.get("analysis") or {}
    if int(analysis.get("bootstrap_resamples", -1)) != 10_000 or int(analysis.get("bootstrap_seed", -1)) != 20260802:
        raise ProtocolError("Bootstrap plan changed")
    if analysis.get("dataset_quality_metrics") != {
        "convfinqa": "native_scores.exact_match",
        "finqa": "native_scores.exact_match",
        "tatqa": "native_scores.f1",
    }:
        raise ProtocolError("Quality estimand changed")
    if analysis.get("interaction_pairs") != [["control", "luna"], ["control", "terra"], ["luna", "terra"]]:
        raise ProtocolError("Tier-interaction plan changed")
    if protocol.get("tier_execution") != {
        "analysis_after_all_complete": True,
        "all_required": True,
        "counterbalanced_schedule_from_manifest": True,
        "manual_skip_forbidden": True,
        "tiers": list(TIERS),
    }:
        raise ProtocolError("Tier execution plan changed")
    budget = protocol.get("budget") or {}
    if float(budget.get("hard_cap_usd", -1)) != 20.0:
        raise ProtocolError("Global authorization must remain USD 20")
    prior = float(budget.get("prior_failed_attempt_allowance_usd", -1))
    prior_probe_attempts = float(budget.get("format_probe_prior_attempt_allowance_usd", -1))
    probe_reservation = float(budget.get("format_probe_maximum_reservation_usd", -1))
    probe_actual = float(budget.get("format_probe_actual_spend_usd", -1))
    if abs(prior - 0.01279752925) > 1e-12 or prior_probe_attempts < 0 or probe_reservation < 0 or probe_actual < 0:
        raise ProtocolError("Prior-attempt or format-probe reservation changed")
    study = sum(float(models[tier]["maximum_reserved_study_cost_usd"]) for tier in TIERS)
    if abs(probe_reservation - sum(float(models[tier]["maximum_reserved_probe_cost_usd"]) for tier in TIERS)) > 1e-12:
        raise ProtocolError("Global probe reservation disagrees with per-tier reservations")
    cumulative_before_study = prior + prior_probe_attempts + probe_actual
    worst_case = cumulative_before_study + study
    if abs(study - float(budget.get("study_maximum_reservation_usd", -1))) > 1e-12:
        raise ProtocolError("Global study reservation disagrees with per-tier reservations")
    if abs(worst_case - float(budget.get("combined_maximum_reservation_usd", -1))) > 1e-12:
        raise ProtocolError("Combined budget reservation does not reconcile")
    if abs(cumulative_before_study - float(budget.get("cumulative_before_study_usd", -1))) > 1e-12:
        raise ProtocolError("Pre-study cumulative spend does not reconcile")
    if abs(20.0 - worst_case - float(budget.get("reservation_headroom_usd", -1))) > 1e-12:
        raise ProtocolError("Budget headroom does not reconcile")
    if worst_case > 20.0 + 1e-12:
        raise ProtocolError("Worst-case complete study reservation exceeds USD 20")
    if int(budget.get("max_study_calls_per_tier", -1)) != 1200 or int(budget.get("max_input_tokens_reserved_per_call", -1)) != 9000:
        raise ProtocolError("Per-tier maximum call count changed")
    probes = protocol.get("format_probes") or {}
    if (
        probes.get("status") != "completed_process_checks"
        or int(probes.get("calls_per_tier", -1)) != 3
        or int(probes.get("study_examples_consumed", -1)) != 0
        or abs(float(probes.get("actual_spend_usd", -1)) - probe_actual) > 1e-12
        or abs(float(probes.get("failed_prefreeze_attempt_allowance_usd", -1)) - prior_probe_attempts) > 1e-12
    ):
        raise ProtocolError("Synthetic format-probe attestation is incomplete")
    if protocol.get("publication") != {
        "base_branch": "realm26/archival-short-paper",
        "branch": "realm26/capability-robustness-study",
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
    if protocol.get("format_probe_attestation") != "attestations/realm26_capability_format_probes.json":
        raise ProtocolError("Format-probe attestation binding changed")

    exclusions = protocol.get("exclusions") or {}
    attempted_indices = exclusions.get("failed_freeze_attempted_indices_by_dataset")
    attempted_ids = exclusions.get("failed_freeze_attempted_example_ids_by_dataset")
    if not isinstance(attempted_indices, Mapping) or set(attempted_indices) != set(DATASETS):
        raise ProtocolError("Failed-freeze attempted-index exclusions are incomplete")
    if not isinstance(attempted_ids, Mapping) or set(attempted_ids) != set(DATASETS):
        raise ProtocolError("Failed-freeze attempted-ID exclusions are incomplete")
    for dataset_id in DATASETS:
        indices = attempted_indices[dataset_id]
        example_ids = attempted_ids[dataset_id]
        if not isinstance(indices, list) or not isinstance(example_ids, list):
            raise ProtocolError("Failed-freeze exclusions must be frozen lists")
        if len(indices) != len(set(map(int, indices))) or len(example_ids) != len(set(map(str, example_ids))):
            raise ProtocolError("Failed-freeze exclusions contain duplicates")
        if len(indices) != len(example_ids):
            raise ProtocolError("Failed-freeze index/ID exclusion counts disagree")
    if len(attempted_indices["finqa"]) != 17 or any(attempted_indices[name] for name in ("tatqa", "convfinqa")):
        raise ProtocolError("Expected exactly 17 failed-freeze FinQA examples")


def _artifact_paths(protocol: Mapping[str, Any]) -> Dict[str, Path]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    finance = Path(__file__).parent
    repo = finance.parents[2]
    return {
        "analysis": finance / "analyze_realm26_capability_ladder.py",
        "attestation": resolve_path(protocol_path, str(protocol["test_attestation"])),
        "capability_llm": finance / "realm26_capability_llm.py",
        "capability_methods": finance / "realm26_capability_methods.py",
        "data_adapter": finance / "realm26_harmonized_data.py",
        "executor": finance / "run_realm26_capability_ladder.py",
        "finance_statistics": finance / "finance_statistics.py",
        "format_probe_attestation": resolve_path(protocol_path, str(protocol["format_probe_attestation"])),
        "manifest": resolve_path(protocol_path, str(protocol["manifest"])),
        "model_snapshot": resolve_path(protocol_path, str(protocol["model_snapshot"])),
        "protocol_guard": Path(__file__),
        "protocol_memo": repo / "paper" / "realm2026" / "capability_ladder_protocol.md",
        "protocol_utils": finance / "protocol_v2.py",
        "scorers": finance / "finance_scoring.py",
        "shared_methods": finance / "realm26_harmonized_v2_methods.py",
        "shared_prompts": finance / "realm26_harmonized_v2_prompts.py",
        "tests": repo / "tests" / "finance" / "test_realm26_capability_ladder.py",
        "tests_contract": repo / "tests" / "finance" / "test_realm26_capability_contract.py",
        "tests_interaction": repo / "tests" / "finance" / "test_realm26_capability_interaction.py",
        "tests_manifest_schedule": repo / "tests" / "finance" / "test_realm26_capability_manifest_schedule.py",
        "tests_runner_schedule": repo / "tests" / "finance" / "test_realm26_capability_schedule.py",
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
        if not {"max_tokens", "response_format", "seed", "structured_outputs"}.issubset(supported):
            raise ProtocolError(f"{tier}: required parameters unavailable")
        if tier == "control" and "reasoning_effort" in supported:
            raise ProtocolError("Control reasoning-parameter exception no longer matches the catalog")
        if tier != "control" and "reasoning_effort" not in supported:
            raise ProtocolError(f"{tier}: reasoning disable parameter is unavailable")
    if not str(snapshot.get("reasoning_parameter_exception") or "").strip():
        raise ProtocolError("Catalog snapshot omits the authorized reasoning exception")
    attestation = load_json(paths["attestation"])
    if attestation.get("status") != "passed" or not attestation.get("commands"):
        raise ProtocolError("Pre-provider test attestation is incomplete")
    probe_attestation = load_json(paths["format_probe_attestation"])
    if (
        probe_attestation.get("status") != "passed"
        or int(probe_attestation.get("successful_probe_count", -1)) != 9
        or int(probe_attestation.get("study_examples_consumed", -1)) != 0
    ):
        raise ProtocolError("Format-probe attestation is incomplete")


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
    failed_indices = {
        int(value)
        for value in protocol["exclusions"]["failed_freeze_attempted_indices_by_dataset"][dataset_id]
    }
    failed_example_ids = {
        str(value)
        for value in protocol["exclusions"]["failed_freeze_attempted_example_ids_by_dataset"][dataset_id]
    }
    indices.update(failed_indices)
    example_ids.update(failed_example_ids)
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
        "failed_freeze_attempted": len(failed_indices),
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


def _shuffle(values: Iterable[Any], seed: int, label: str) -> List[Any]:
    """Return a reproducible permutation without process-dependent hashing."""

    items = list(values)
    digest = hashlib.sha256(f"{seed}:{label}".encode("utf-8")).digest()
    random.Random(int.from_bytes(digest[:8], "big")).shuffle(items)
    return items


def build_execution_schedule(datasets: Mapping[str, Any], schedule_seed: int) -> Dict[str, Any]:
    """Counterbalance model and framework order before any paid inference."""

    item_keys: List[Tuple[str, str]] = []
    for dataset_id in DATASETS:
        spec = datasets.get(dataset_id)
        if not isinstance(spec, Mapping) or not isinstance(spec.get("examples"), list):
            raise ProtocolError(f"{dataset_id}: schedule source examples are missing")
        item_keys.extend((dataset_id, str(item["example_id"])) for item in spec["examples"])
    if len(item_keys) != 150 or len(set(item_keys)) != 150:
        raise ProtocolError("Execution schedule requires exactly 150 unique dataset/example IDs")

    ordered_items = _shuffle(item_keys, schedule_seed, "item-order")
    model_orders = _shuffle(list(itertools.permutations(TIERS)) * 25, schedule_seed, "model-order")
    framework_first = {
        tier: _shuffle(["static"] * 75 + ["react"] * 75, schedule_seed, f"framework-order:{tier}")
        for tier in TIERS
    }
    items: List[Dict[str, Any]] = []
    for position, ((dataset_id, example_id), model_order) in enumerate(zip(ordered_items, model_orders)):
        items.append({
            "dataset_id": dataset_id,
            "example_id": example_id,
            "framework_order_by_tier": {
                tier: list(FRAMEWORKS) if framework_first[tier][position] == "static" else list(reversed(FRAMEWORKS))
                for tier in TIERS
            },
            "model_order": list(model_order),
            "position": position,
        })
    return {"items": items, "schedule_seed": int(schedule_seed)}


def validate_execution_schedule(
    schedule: Mapping[str, Any], datasets: Mapping[str, Any], schedule_seed: int
) -> None:
    """Reject schedule drift, imbalance, missing items, or post-freeze reordering."""

    if not isinstance(schedule, Mapping) or schedule.get("schedule_seed") != int(schedule_seed):
        raise ProtocolError("Execution schedule seed changed")
    items = schedule.get("items")
    if not isinstance(items, list) or len(items) != 150:
        raise ProtocolError("Execution schedule must contain 150 items")
    expected_keys = {
        (dataset_id, str(item["example_id"]))
        for dataset_id in DATASETS
        for item in datasets[dataset_id]["examples"]
    }
    scheduled_keys = {(str(item.get("dataset_id")), str(item.get("example_id"))) for item in items}
    if scheduled_keys != expected_keys or len(scheduled_keys) != 150:
        raise ProtocolError("Execution schedule item IDs do not match the manifest")
    if [item.get("position") for item in items] != list(range(150)):
        raise ProtocolError("Execution schedule positions changed")

    permutation_counts: Counter[Tuple[str, ...]] = Counter()
    first_counts: Counter[Tuple[str, str]] = Counter()
    for item in items:
        model_order = tuple(item.get("model_order", ()))
        if set(model_order) != set(TIERS) or len(model_order) != len(TIERS):
            raise ProtocolError("Each scheduled item must contain one permutation of all tiers")
        permutation_counts[model_order] += 1
        framework_orders = item.get("framework_order_by_tier")
        if not isinstance(framework_orders, Mapping) or set(framework_orders) != set(TIERS):
            raise ProtocolError("Each scheduled item must order both frameworks for every tier")
        for tier in TIERS:
            order = tuple(framework_orders[tier])
            if set(order) != set(FRAMEWORKS) or len(order) != len(FRAMEWORKS):
                raise ProtocolError(f"{tier}: invalid framework order")
            first_counts[(tier, order[0])] += 1
    if set(permutation_counts) != set(itertools.permutations(TIERS)) or set(permutation_counts.values()) != {25}:
        raise ProtocolError("Six model permutations must occur exactly 25 times each")
    if any(first_counts[(tier, framework)] != 75 for tier in TIERS for framework in FRAMEWORKS):
        raise ProtocolError("Static/ReAct first order must be balanced 75/75 within every tier")
    if dict(schedule) != build_execution_schedule(datasets, schedule_seed):
        raise ProtocolError("Execution schedule does not reproduce from the frozen seed")


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
            selected = stratified_sample(candidates, rows, ("question_type", "answer_from"), per_dataset, seed, f"{PROTOCOL_ID}:{dataset_id}")
            policy = "seeded proportional answer_type x answer_source sample after identifier-only exclusions"
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
    base_body["execution_schedule"] = build_execution_schedule(
        datasets, int(protocol["sample"]["schedule_seed"])
    )
    base_body["manifest_fingerprint"] = fingerprint(base_body)
    return base_body


def load_manifest(protocol: Mapping[str, Any]) -> Dict[str, Any]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    manifest = load_json(resolve_path(protocol_path, str(protocol["manifest"])))
    supplied = manifest.pop("manifest_fingerprint", None)
    actual = fingerprint(manifest)
    manifest["manifest_fingerprint"] = supplied
    if supplied != actual or manifest.get("protocol_id") != PROTOCOL_ID:
        raise ProtocolError("Capability manifest fingerprint or protocol mismatch")
    validate_execution_schedule(
        manifest.get("execution_schedule") or {},
        manifest.get("datasets") or {},
        int(protocol["sample"]["schedule_seed"]),
    )
    return manifest


def validate_manifest_against_sources(protocol: Mapping[str, Any], manifest: Mapping[str, Any], env_factory: Callable[[str], Any]) -> None:
    regenerated = build_manifest(protocol, env_factory)
    if regenerated != manifest:
        raise ProtocolError("Fresh manifest and schedule do not reproduce from sources")
    validate_execution_schedule(
        manifest["execution_schedule"], manifest["datasets"], int(protocol["sample"]["schedule_seed"])
    )
    for dataset_id in DATASETS:
        rows = env_factory(dataset_id).rows
        spec = manifest["datasets"][dataset_id]
        excluded = _identifier_exclusions(protocol, dataset_id)
        if len(rows) != int(spec["dataset_size"]) or excluded["fingerprint"] != spec["exclusion_identifier_fingerprint"]:
            raise ProtocolError(f"{dataset_id}: dataset or exclusion drift")
        selected = [int(item["index"]) for item in spec["examples"]]
        if set(selected) & excluded["indices"]:
            raise ProtocolError(f"{dataset_id}: selected index overlaps prior evidence")
        if {str(item["example_id"]) for item in spec["examples"]} & excluded["example_ids"]:
            raise ProtocolError(f"{dataset_id}: selected ID overlaps prior evidence")
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
