"""Prospectively frozen REALM 2026 second-family replication protocol.

This module deliberately uses a separate schema from ``finance_icaif26_v2``.
The original development and sealed-final manifests are read only to construct
an exclusion set; their examples are never rendered or copied into the new
manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Sequence

from .method_prompts import NEXUS_PROMPT, REACT_PROMPT
from .protocol_v2 import (
    ProtocolError,
    _example_record,
    _sample,
    fingerprint,
    load_manifest,
    load_protocol,
    stratified_sample,
    write_stable_json,
)


SCHEMA_VERSION = "realm26-finance-replication-v1"
MANIFEST_SCHEMA_VERSION = "realm26-finance-replication-manifest-v1"
PROTOCOL_ID = "realm26_second_family_v1"
DATASETS = ("finqa", "tatqa", "convfinqa")
FRAMEWORKS = ("nexus", "react")
DEFAULT_PROTOCOL_PATH = Path(__file__).with_name("protocols") / f"{PROTOCOL_ID}.json"


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(protocol_path: Path, configured: str) -> Path:
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = protocol_path.parent / candidate
    return candidate.resolve()


def prompt_fingerprint() -> str:
    return fingerprint({"nexus": NEXUS_PROMPT, "react": REACT_PROMPT})


def load_replication_protocol(
    path: str | Path = DEFAULT_PROTOCOL_PATH,
    *,
    validate_artifacts: bool = True,
) -> Dict[str, Any]:
    protocol_path = Path(path).resolve()
    protocol = _load_json(protocol_path)
    protocol["_path"] = str(protocol_path)
    validate_protocol(protocol)
    if validate_artifacts:
        validate_frozen_artifacts(protocol)
    return protocol


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError(f"Expected schema_version={SCHEMA_VERSION!r}")
    if protocol.get("protocol_id") != PROTOCOL_ID:
        raise ProtocolError(f"Expected protocol_id={PROTOCOL_ID!r}")
    if protocol.get("freeze_state") != "frozen":
        raise ProtocolError("Replication protocol must have freeze_state='frozen'")
    if tuple(protocol.get("datasets", ())) != DATASETS:
        raise ProtocolError(f"datasets must be exactly {DATASETS}")
    if tuple(protocol.get("frameworks", ())) != FRAMEWORKS:
        raise ProtocolError(f"frameworks must be exactly {FRAMEWORKS}")
    if int(protocol.get("sample", {}).get("per_dataset", -1)) != 25:
        raise ProtocolError("sample.per_dataset must remain frozen at 25")
    if int(protocol.get("seed", -1)) != 42:
        raise ProtocolError("seed must remain frozen at 42")
    inference = protocol.get("inference") or {}
    if inference.get("model_id") != "openai/gpt-4o-mini-2024-07-18":
        raise ProtocolError("Unexpected replication model binding")
    if inference.get("backend") != "openrouter" or inference.get("temperature") != 0:
        raise ProtocolError("OpenRouter backend and temperature zero are frozen")
    provider = inference.get("provider_routing") or {}
    expected_provider = {
        "allow_fallbacks": False,
        "data_collection": "deny",
        "only": ["OpenAI"],
        "require_parameters": True,
    }
    if provider != expected_provider:
        raise ProtocolError("OpenAI-only provider routing without fallback is frozen")
    if float(protocol.get("budget", {}).get("hard_cap_usd", -1)) != 15.0:
        raise ProtocolError("budget.hard_cap_usd must remain frozen at 15")
    if int(protocol.get("stopping_rule", {}).get("consecutive_provider_failures", -1)) != 2:
        raise ProtocolError("consecutive provider failure stop must remain frozen at 2")
    analysis = protocol.get("analysis") or {}
    if int(analysis.get("bootstrap_resamples", -1)) != 10_000:
        raise ProtocolError("analysis.bootstrap_resamples must remain frozen at 10000")


def validate_frozen_artifacts(protocol: Mapping[str, Any]) -> None:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    artifacts = protocol.get("artifact_hashes") or {}
    required = (
        "analysis",
        "executor",
        "llm_wrapper",
        "manifest",
        "methods",
        "model_snapshot",
        "prompts",
        "protocol_guard",
        "scorers",
    )
    missing = [name for name in required if not artifacts.get(name)]
    if missing:
        raise ProtocolError(f"Missing frozen artifact hashes: {missing}")

    manifest_path = resolve_path(protocol_path, str(protocol["manifest"]))
    snapshot_path = resolve_path(protocol_path, str(protocol["model_snapshot"]))
    methods_path = Path(__file__).with_name("finance_methods.py")
    scorer_path = Path(__file__).with_name("finance_scoring.py")
    analysis_path = Path(__file__).with_name("analyze_realm26_replication.py")
    executor_path = Path(__file__).with_name("run_realm26_replication.py")
    llm_path = Path(__file__).parents[2] / "shared" / "llm.py"
    actual = {
        "analysis": _sha256_file(analysis_path),
        "executor": _sha256_file(executor_path),
        "llm_wrapper": _sha256_file(llm_path),
        "manifest": _sha256_file(manifest_path),
        "model_snapshot": _sha256_file(snapshot_path),
        "prompts": prompt_fingerprint(),
        "protocol_guard": _sha256_file(Path(__file__)),
        "methods": _sha256_file(methods_path),
        "scorers": _sha256_file(scorer_path),
    }
    mismatches = {
        name: {"expected": artifacts[name], "actual": value}
        for name, value in actual.items()
        if artifacts[name] != value
    }
    if mismatches:
        raise ProtocolError(f"Frozen artifact hash mismatch: {mismatches}")

    snapshot = _load_json(snapshot_path)
    inference = protocol["inference"]
    if snapshot.get("model_id") != inference.get("model_id"):
        raise ProtocolError("Frozen model snapshot does not match inference.model_id")
    endpoint = snapshot.get("endpoint") or {}
    if endpoint.get("provider_name") != "OpenAI" or endpoint.get("tag") != "openai":
        raise ProtocolError("Frozen endpoint is not the OpenAI provider")
    supported = set(endpoint.get("supported_parameters") or [])
    if not {"temperature", "stop", "max_tokens"}.issubset(supported):
        raise ProtocolError("Frozen endpoint cannot faithfully run both workflows")


def _source_protocol(protocol_path: Path, protocol: Mapping[str, Any]) -> Dict[str, Any]:
    source = resolve_path(protocol_path, str(protocol["source_protocol"]))
    return load_protocol(source)


def _selected_record(dataset_id: str, rows: Sequence[Mapping[str, Any]], idx: int) -> Dict[str, Any]:
    record = _example_record(dataset_id, rows, idx)
    record["item_hash"] = fingerprint(rows[idx])
    if dataset_id == "convfinqa":
        record.pop("dialogue_id", None)
        record["dialogue_hash"] = fingerprint(str(rows[idx].get("dialogue_id", "")))
    return record


def build_replication_manifest(
    protocol: Mapping[str, Any],
    env_factory: Callable[[str], Any],
) -> Dict[str, Any]:
    """Select new evidence while treating both older partitions as reserved."""

    validate_protocol(protocol)
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    source_protocol = _source_protocol(protocol_path, protocol)
    per_dataset = int(protocol["sample"]["per_dataset"])
    seed = int(protocol["seed"])
    datasets: Dict[str, Any] = {}

    for dataset_id in DATASETS:
        rows = list(env_factory(dataset_id).rows)
        source_manifest = load_manifest(source_protocol, dataset_id)
        reserved = set(source_manifest["development"]["indices"])
        reserved.update(source_manifest["final"]["indices"])
        candidates = sorted(set(range(len(rows))) - reserved)
        if dataset_id == "finqa":
            selected = _sample(candidates, per_dataset, seed, f"{PROTOCOL_ID}:{dataset_id}")
            policy = "seeded sample excluding prior development and sealed final"
        elif dataset_id == "tatqa":
            selected = stratified_sample(
                candidates,
                rows,
                ("question_type", "answer_from"),
                per_dataset,
                seed,
                f"{PROTOCOL_ID}:{dataset_id}",
            )
            policy = "proportional question_type x answer_from strata excluding both prior partitions"
        else:
            reserved_dialogues = {
                str(rows[idx].get("dialogue_id", "")) for idx in reserved
            }
            eligible = [
                idx
                for idx in candidates
                if str(rows[idx].get("dialogue_id", "")) not in reserved_dialogues
            ]
            dialogue_to_index: Dict[str, int] = {}
            for idx in eligible:
                dialogue_to_index.setdefault(str(rows[idx].get("dialogue_id", "")), idx)
            selected_dialogue_indices = _sample(
                dialogue_to_index.values(),
                per_dataset,
                seed,
                f"{PROTOCOL_ID}:{dataset_id}:dialogues",
            )
            selected = sorted(selected_dialogue_indices)
            policy = "one turn per new dialogue excluding dialogues in both prior partitions"

        if set(selected) & reserved:
            raise ProtocolError(f"{dataset_id}: replication overlaps a reserved partition")
        if len(selected) != per_dataset or len(set(selected)) != per_dataset:
            raise ProtocolError(f"{dataset_id}: expected {per_dataset} unique selected rows")
        datasets[dataset_id] = {
            "candidate_count": len(candidates),
            "dataset_fingerprint": fingerprint(rows),
            "dataset_size": len(rows),
            "examples": [_selected_record(dataset_id, rows, idx) for idx in selected],
            "prior_manifest_fingerprint": source_manifest["manifest_fingerprint"],
            "reserved_count": len(reserved),
            "selection_policy": policy,
        }

    body: Dict[str, Any] = {
        "datasets": datasets,
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "seed": seed,
    }
    body["manifest_fingerprint"] = fingerprint(body)
    return body


def load_replication_manifest(protocol: Mapping[str, Any]) -> Dict[str, Any]:
    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    path = resolve_path(protocol_path, str(protocol["manifest"]))
    manifest = _load_json(path)
    supplied = manifest.pop("manifest_fingerprint", None)
    actual = fingerprint(manifest)
    manifest["manifest_fingerprint"] = supplied
    if supplied != actual:
        raise ProtocolError("Replication manifest fingerprint mismatch")
    if manifest.get("protocol_id") != PROTOCOL_ID:
        raise ProtocolError("Replication manifest/protocol ID mismatch")
    return manifest


def validate_manifest_against_sources(
    protocol: Mapping[str, Any],
    manifest: Mapping[str, Any],
    env_factory: Callable[[str], Any],
) -> None:
    """Fail before inference on drift, overlap, ID mismatch, or item-hash drift."""

    protocol_path = Path(str(protocol.get("_path", DEFAULT_PROTOCOL_PATH)))
    source_protocol = _source_protocol(protocol_path, protocol)
    for dataset_id in DATASETS:
        rows = list(env_factory(dataset_id).rows)
        spec = manifest["datasets"][dataset_id]
        if fingerprint(rows) != spec.get("dataset_fingerprint"):
            raise ProtocolError(f"{dataset_id}: adapter content drifted after freeze")
        source_manifest = load_manifest(source_protocol, dataset_id)
        if source_manifest["manifest_fingerprint"] != spec.get("prior_manifest_fingerprint"):
            raise ProtocolError(f"{dataset_id}: source manifest drifted after freeze")
        reserved = set(source_manifest["development"]["indices"])
        reserved.update(source_manifest["final"]["indices"])
        selected = [int(item["index"]) for item in spec["examples"]]
        if set(selected) & reserved:
            raise ProtocolError(f"{dataset_id}: selected row overlaps reserved evidence")
        if dataset_id == "convfinqa":
            reserved_dialogues = {
                str(rows[idx].get("dialogue_id", "")) for idx in reserved
            }
            selected_dialogues = [str(rows[idx].get("dialogue_id", "")) for idx in selected]
            if reserved_dialogues & set(selected_dialogues):
                raise ProtocolError("convfinqa: selected dialogue overlaps reserved evidence")
            if len(selected_dialogues) != len(set(selected_dialogues)):
                raise ProtocolError("convfinqa: replication dialogues must be unique")
        for item in spec["examples"]:
            idx = int(item["index"])
            expected = _selected_record(dataset_id, rows, idx)
            if dict(item) != expected:
                raise ProtocolError(f"{dataset_id}: selected item identity/hash drift")


def write_generated_manifest(
    protocol_path: str | Path,
    env_factory: Callable[[str], Any],
) -> Path:
    """Protocol-authoring helper; never called by the frozen experiment runner."""

    path = Path(protocol_path).resolve()
    protocol = load_replication_protocol(path, validate_artifacts=False)
    manifest = build_replication_manifest(protocol, env_factory)
    output = resolve_path(path, str(protocol["manifest"]))
    write_stable_json(output, manifest)
    return output
