import json
from pathlib import Path

import pytest

from src.agents.finance.protocol_v2 import fingerprint
from src.agents.finance.realm26_capability_llm import call_capability_model, validate_live_catalog
from src.agents.finance.realm26_capability_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    _artifact_paths,
    build_manifest,
    load_manifest,
    load_protocol,
    validate_protocol,
)
from src.agents.finance.run_realm26_capability_ladder import CapabilityRunner, SpendLedger, StopExperiment


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_capability_request_uses_reasoning_none_and_no_sampling(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(json)
        return FakeResponse({
            "model": "openai/gpt-5.6-luna-20260709",
            "provider": "OpenAI",
            "choices": [{"message": {"content": '{"thought":"x","action":"Finish","answer":"7"}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28, "cost": 0.00001},
        })

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("src.agents.finance.realm26_capability_llm.requests.post", fake_post)
    response = call_capability_model(
        prompt="question", requested_model="openai/gpt-5.6-luna",
        canonical_slug="openai/gpt-5.6-luna-20260709", max_tokens=384, stop=[],
    )
    assert response.provider_name == "OpenAI"
    assert captured["reasoning_effort"] == "none"
    assert "temperature" not in captured and "top_p" not in captured and "stop" not in captured
    assert captured["provider"] == {
        "only": ["OpenAI"], "allow_fallbacks": False,
        "require_parameters": True, "data_collection": "deny",
    }


def test_catalog_snapshot_matches_only_exact_standard_openai_endpoint(monkeypatch):
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    snapshot_path = Path(protocol["_path"]).parent / protocol["model_snapshot"]
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    def fake_get(url, timeout):
        if url.endswith("/models"):
            return FakeResponse({"data": [
                {"id": row["id"], "canonical_slug": row["canonical_slug"], "created": row["created_unix"], "context_length": row["context_length"]}
                for row in snapshot["models"].values()
            ]})
        tier = "luna" if "luna" in url else "terra"
        return FakeResponse({"data": {"endpoints": [snapshot["models"][tier]["openai_endpoint"]]}})

    monkeypatch.setattr("src.agents.finance.realm26_capability_llm.requests.get", fake_get)
    assert validate_live_catalog(snapshot_path) == {
        "luna": "openai/gpt-5.6-luna-20260709",
        "terra": "openai/gpt-5.6-terra-20260709",
    }


def test_protocol_freezes_models_budgets_trigger_and_shared_contract():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    validate_protocol(protocol)
    assert protocol["models"]["luna"]["maximum_reserved_study_cost_usd"] < 5
    assert protocol["models"]["terra"]["maximum_reserved_study_cost_usd"] < 15
    assert protocol["terra_trigger"]["manual_override_forbidden"] is True
    assert protocol["inference"]["reasoning_effort"] == "none"
    assert protocol["inference"]["sampling_parameters_forbidden"] == ["temperature", "top_p"]


def test_real_manifest_excludes_every_prior_partition_and_uses_one_sample_for_both_tiers():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    manifest = load_manifest(protocol)
    assert sum(len(manifest["datasets"][dataset]["examples"]) for dataset in DATASETS) == 150
    for dataset in DATASETS:
        spec = manifest["datasets"][dataset]
        assert len(spec["examples"]) == 50
        assert spec["exclusion_counts"] == {
            "harmonized_v1": 50,
            "harmonized_v2": 50,
            "original_development": 50,
            "sealed_final_identifiers": 200,
            "second_family": 25,
            "total": 375,
        }
    assert protocol["sample"]["same_items_for_all_tiers"] is True


class GuardedRows:
    def __init__(self, dataset, reserved):
        self.dataset = dataset
        self.reserved = set(reserved)

    def __len__(self):
        return 700

    def context_for_index(self, idx):
        return int(idx)

    def __getitem__(self, idx):
        if idx in self.reserved:
            raise AssertionError("excluded or final content was dereferenced")
        row = {"answer": str(idx), "evidence": [f"e{idx}"], "question": f"q{idx}", "source_id": f"{self.dataset}-{idx}"}
        if self.dataset == "tatqa":
            row.update({"answer_from": "table", "question_type": "arithmetic"})
        if self.dataset == "convfinqa":
            row["dialogue_id"] = f"dialogue-{idx}"
        return row


def test_manifest_builder_never_dereferences_excluded_rows(monkeypatch):
    reserved = set(range(375))
    exclusions = {
        "counts": {"harmonized_v1": 50, "harmonized_v2": 50, "original_development": 50, "sealed_final_identifiers": 200, "second_family": 25, "total": 375},
        "dialogue_hashes": {fingerprint(f"reserved-dialogue-{idx}") for idx in reserved},
        "example_ids": {f"reserved-{idx}" for idx in reserved},
        "fingerprint": "sha256:test",
        "indices": reserved,
    }
    monkeypatch.setattr("src.agents.finance.realm26_capability_protocol._identifier_exclusions", lambda protocol, dataset: exclusions)
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)

    class Factory:
        def __call__(self, dataset):
            return type("Env", (), {"rows": GuardedRows(dataset, reserved)})()

    manifest = build_manifest(protocol, Factory())
    assert all(len(manifest["datasets"][dataset]["examples"]) == 50 for dataset in DATASETS)


def test_spend_ledger_reserves_separate_tier_cap(tmp_path):
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    ledger = SpendLedger(tmp_path / "ledger.json", "sha256:test", "terra", protocol["models"]["terra"])
    ledger.reserve("call", "sha256:prompt")
    assert ledger.data["pending_reservations"][0]["maximum_cost_usd"] == pytest.approx(0.0115456)


def test_terra_trigger_cannot_be_manually_overridden(tmp_path):
    runner = object.__new__(CapabilityRunner)
    runner.tier = "terra"
    missing = tmp_path / "missing.json"
    with pytest.raises(StopExperiment, match="trigger"):
        runner._validate_trigger(missing)
    decision = tmp_path / "decision.json"
    decision.write_text(json.dumps({
        "trigger_schema_version": "realm26-terra-trigger-v1",
        "run_terra": False,
        "luna_primary_ci": {"lower": -0.1},
    }))
    with pytest.raises(StopExperiment, match="authorize"):
        runner._validate_trigger(decision)


def test_all_acceptance_critical_artifacts_are_hash_bound():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH)
    assert set(protocol["artifact_hashes"]) == set(_artifact_paths(protocol))
