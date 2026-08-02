import json
from pathlib import Path

import pytest

from src.agents.finance.realm26_capability_llm import validate_live_catalog
from src.agents.finance.realm26_capability_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    TIERS,
    _artifact_paths,
    load_manifest,
    load_protocol,
    validate_execution_schedule,
    validate_protocol,
)
from src.agents.finance.run_realm26_capability_ladder import cumulative_budget_contract


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_frozen_protocol_has_three_mandatory_tiers_and_reconciled_budget():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    validate_protocol(protocol)
    assert tuple(protocol["models"]) == TIERS == ("control", "luna", "terra")
    assert protocol["tier_execution"]["all_required"] is True
    assert protocol["format_probes"]["status"] == "completed_process_checks"
    assert protocol["format_probes"]["study_examples_consumed"] == 0
    contract = cumulative_budget_contract(protocol)
    assert (
        contract["prior_failed_attempt_spend_usd"]
        + contract["format_probe_spend_usd"]
        + contract["reserved_study_cost_usd"]
        <= contract["cumulative_hard_cap_usd"]
    )


def test_manifest_is_fresh_shared_and_counterbalanced():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    manifest = load_manifest(protocol)
    assert sum(len(manifest["datasets"][name]["examples"]) for name in DATASETS) == 150
    assert all(len(manifest["datasets"][name]["examples"]) == 50 for name in DATASETS)
    assert manifest["datasets"]["finqa"]["exclusion_counts"]["failed_freeze_attempted"] == 17
    attempted = set(protocol["exclusions"]["failed_freeze_attempted_example_ids_by_dataset"]["finqa"])
    selected = {item["example_id"] for item in manifest["datasets"]["finqa"]["examples"]}
    assert not selected & attempted
    validate_execution_schedule(
        manifest["execution_schedule"], manifest["datasets"], protocol["sample"]["schedule_seed"]
    )


def test_catalog_snapshot_matches_three_exact_openai_endpoints(monkeypatch):
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    snapshot_path = Path(protocol["_path"]).parent / protocol["model_snapshot"]
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    def fake_get(url, timeout):
        if url.endswith("/models"):
            return FakeResponse({"data": [
                {
                    "id": row["id"], "canonical_slug": row["canonical_slug"],
                    "created": row["created_unix"], "context_length": row["context_length"],
                }
                for row in snapshot["models"].values()
            ]})
        tier = next(name for name, row in snapshot["models"].items() if row["id"] in url)
        return FakeResponse({"data": {"endpoints": [snapshot["models"][tier]["openai_endpoint"]]}})

    monkeypatch.setattr("src.agents.finance.realm26_capability_llm.requests.get", fake_get)
    assert validate_live_catalog(snapshot_path) == {
        tier: protocol["models"][tier]["canonical_slug"] for tier in TIERS
    }


def test_artifact_hashes_cover_every_acceptance_critical_file():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH)
    assert set(protocol["artifact_hashes"]) == set(_artifact_paths(protocol))


def test_authorized_reasoning_exception_is_narrow_and_explicit():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    assert protocol["inference"]["reasoning_effort_by_tier"] == {
        "control": None, "luna": "none", "terra": "none",
    }
    assert "GPT-4o-mini" in protocol["inference"]["reasoning_semantics"]
    assert protocol["inference"]["sampling_parameters_forbidden"] == ["temperature", "top_p"]
