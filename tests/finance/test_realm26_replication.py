import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.agents.finance.protocol_v2 import ProtocolError, fingerprint
from src.agents.finance.realm26_replication_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    load_replication_manifest,
    load_replication_protocol,
    resolve_path,
    validate_frozen_artifacts,
)
from src.agents.finance.run_realm26_replication import (
    BudgetedModel,
    ReplicationRunner,
    SpendLedger,
    StopExperiment,
)
from src.shared.llm_telemetry import LLMResult


def _protocol():
    return load_replication_protocol(DEFAULT_PROTOCOL_PATH)


def test_frozen_replication_indices_exclude_both_prior_partitions_without_rendering_them():
    protocol = _protocol()
    manifest = load_replication_manifest(protocol)
    source_path = resolve_path(Path(protocol["_path"]), protocol["source_protocol"])
    source_protocol = json.loads(source_path.read_text(encoding="utf-8"))
    source_root = source_path.parent

    assert sum(len(manifest["datasets"][dataset]["examples"]) for dataset in DATASETS) == 75
    for dataset in DATASETS:
        source_manifest = json.loads(
            (source_root / source_protocol["datasets"][dataset]["manifest"]).read_text(
                encoding="utf-8"
            )
        )
        reserved = set(source_manifest["development"]["indices"])
        reserved.update(source_manifest["final"]["indices"])
        selected = {
            int(item["index"]) for item in manifest["datasets"][dataset]["examples"]
        }
        assert len(selected) == 25
        assert selected.isdisjoint(reserved)

    source_manifest = json.loads(
        (source_root / source_protocol["datasets"]["convfinqa"]["manifest"]).read_text(
            encoding="utf-8"
        )
    )
    reserved_dialogue_hashes = {
        fingerprint(str(item["dialogue_id"]))
        for partition in ("development", "final")
        for item in source_manifest[partition]["examples"]
    }
    selected_dialogue_hashes = {
        item["dialogue_hash"]
        for item in manifest["datasets"]["convfinqa"]["examples"]
    }
    assert len(selected_dialogue_hashes) == 25
    assert selected_dialogue_hashes.isdisjoint(reserved_dialogue_hashes)


@pytest.mark.parametrize(
    "artifact",
    [
        "analysis",
        "executor",
        "llm_wrapper",
        "manifest",
        "methods",
        "model_snapshot",
        "prompts",
        "protocol_guard",
        "scorers",
    ],
)
def test_frozen_artifact_tampering_fails_closed(artifact):
    protocol = _protocol()
    tampered = deepcopy(protocol)
    tampered["artifact_hashes"][artifact] = "sha256:" + "0" * 64
    with pytest.raises(ProtocolError, match="hash mismatch"):
        validate_frozen_artifacts(tampered)


def _minimal_protocol():
    return {
        "budget": {"reservation_multiplier": 1.25},
        "inference": {
            "backend": "openrouter",
            "model_id": "openai/gpt-4o-mini-2024-07-18",
            "temperature": 0,
        },
        "retry_policy": {"max_attempts_per_call": 1},
    }


def _snapshot():
    return {
        "endpoint": {
            "pricing": {
                "prompt": "0.00000015",
                "completion": "0.0000006",
                "input_cache_read": "0.000000075",
            }
        }
    }


def test_spend_cap_reservation_persists_and_blocks_next_call(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = SpendLedger(path, "sha256:test", 15.0)
    ledger.reserve(call_key="one", maximum_cost_usd=14.0)
    ledger.complete(
        call_key="one",
        actual_cost_usd=14.0,
        status="ok",
        requested_model="model",
        resolved_model="model",
    )
    resumed = SpendLedger(path, "sha256:test", 15.0)
    assert resumed.actual_spend == 14.0
    with pytest.raises(StopExperiment, match="hard cap"):
        resumed.reserve(call_key="two", maximum_cost_usd=1.01)


def test_unresolved_reservation_fails_closed_on_resume(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = SpendLedger(path, "sha256:test", 15.0)
    ledger.reserve(call_key="interrupted", maximum_cost_usd=0.5)
    with pytest.raises(StopExperiment, match="Unresolved"):
        SpendLedger(path, "sha256:test", 15.0)


def test_model_binding_mismatch_stops_before_another_call(monkeypatch, tmp_path):
    expected = "openai/gpt-4o-mini-2024-07-18"

    def fake_call(*args, **kwargs):
        return LLMResult(
            text="Answer: 1",
            requested_model=expected,
            resolved_model="openai/gpt-4o-mini",
            backend="openrouter",
            input_tokens=10,
            output_tokens=2,
            total_tokens=12,
            provider_cost_usd=0.00001,
            latency_ms=1.0,
        )

    monkeypatch.setattr(
        "src.agents.finance.run_realm26_replication.llm_with_metadata", fake_call
    )
    ledger = SpendLedger(tmp_path / "ledger.json", "sha256:test", 15.0)
    model = BudgetedModel(_minimal_protocol(), _snapshot(), ledger, "pair")
    with pytest.raises(StopExperiment, match="Resolved model"):
        model(
            "prompt",
            stop=["\nObservation 1:"],
            temperature=0,
            model_id=expected,
            max_tokens=512,
        )
    assert len(ledger.data["calls"]) == 1
    assert ledger.data["pending_reservations"] == []


def _bare_runner(tmp_path):
    runner = object.__new__(ReplicationRunner)
    runner.protocol = {
        "frameworks": ["nexus", "react"],
        "inference": {"model_id": "model"},
        "protocol_id": "realm26_second_family_v1",
        "seed": 42,
    }
    runner.manifest = {
        "manifest_fingerprint": "sha256:manifest",
        "datasets": {
            dataset: {
                "examples": [
                    {"example_id": f"{dataset}-1", "index": 1, "item_hash": "sha256:item"}
                ]
            }
            for dataset in DATASETS
        },
    }
    runner.results_root = tmp_path
    runner.config_path = tmp_path / "config.json"
    runner.smoke_path = tmp_path / "smoke_complete.json"
    runner.run_history_path = tmp_path / "run_history.json"
    runner.protocol_fingerprint = "sha256:protocol"
    return runner


def test_resume_skips_immutable_completed_pair_and_rejects_duplicate(tmp_path):
    runner = _bare_runner(tmp_path)
    row = {"example_id": "finqa-1", "status": "success"}
    runner._save_result("finqa", "nexus", row)
    pending = runner._pending_pairs("full")
    assert len(pending) == 5
    assert ("finqa", runner.manifest["datasets"]["finqa"]["examples"][0], "nexus") not in pending
    with pytest.raises(StopExperiment, match="overwrite"):
        runner._save_result("finqa", "nexus", row)


def test_resume_config_mismatch_fails_closed(tmp_path):
    runner = _bare_runner(tmp_path)
    runner._write_or_validate_config()
    config = json.loads(runner.config_path.read_text(encoding="utf-8"))
    config["seed"] = 99
    runner.config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(StopExperiment, match="configuration differs"):
        runner._write_or_validate_config()


def test_full_phase_requires_validated_smoke(tmp_path):
    runner = _bare_runner(tmp_path)
    with pytest.raises(StopExperiment, match="requires"):
        runner.run("full")
