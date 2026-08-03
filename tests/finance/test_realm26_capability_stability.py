import copy
import json
from pathlib import Path

import pytest

from src.agents.finance.realm26_capability_llm import build_capability_request_body
from src.agents.finance.realm26_capability_protocol import load_protocol
from src.agents.finance.protocol_v2 import ProtocolError
from src.agents.finance.run_realm26_capability_ladder import cumulative_budget_contract
from src.agents.finance.run_realm26_capability_stability import (
    STABILITY_PROTOCOL_ID,
    load_stability_protocol,
)


def test_stability_overlay_changes_only_frozen_replication_fields():
    protocol, base, spec = load_stability_protocol()
    assert load_protocol()["protocol_id"] == "realm26_capability_ladder"
    assert protocol["protocol_id"] == STABILITY_PROTOCOL_ID
    assert protocol["workflows"] == base["workflows"]
    assert protocol["models"] == base["models"]
    assert protocol["retry_policy"] == base["retry_policy"]
    assert protocol["sample"] == base["sample"]
    assert protocol["manifest"] == base["manifest"] == spec["manifest"]
    assert protocol["inference"]["request_seed"] == 20260803
    assert base["inference"]["request_seed"] == 20260802
    assert protocol["inference"]["sampling_parameters_forbidden"] == ["temperature", "top_p"]
    assert protocol["results"]["root"] == "runs/realm26_capability_stability"


def test_stability_request_bodies_differ_only_by_seed():
    protocol, base, _ = load_stability_protocol()
    for model in ("openai/gpt-4o-mini", "openai/gpt-5.6-luna", "openai/gpt-5.6-terra"):
        original = build_capability_request_body(
            prompt="synthetic",
            requested_model=model,
            max_tokens=384,
            action_schema="finish",
            seed=int(base["inference"]["request_seed"]),
        )
        replication = build_capability_request_body(
            prompt="synthetic",
            requested_model=model,
            max_tokens=384,
            action_schema="finish",
            seed=int(protocol["inference"]["request_seed"]),
        )
        assert original.pop("seed") == 20260802
        assert replication.pop("seed") == 20260803
        assert original == replication
        assert "temperature" not in replication and "top_p" not in replication


def test_stability_budget_reserves_every_allowed_call_under_global_cap():
    protocol, _, spec = load_stability_protocol()
    contract = cumulative_budget_contract(protocol)
    assert contract["prior_failed_attempt_spend_usd"] == pytest.approx(1.0071798110000005)
    assert contract["reserved_study_cost_usd"] == pytest.approx(18.499536)
    assert contract["cumulative_hard_cap_usd"] == 20.0
    assert (
        contract["prior_failed_attempt_spend_usd"]
        + contract["format_probe_spend_usd"]
        + contract["reserved_study_cost_usd"]
    ) == pytest.approx(spec["budget"]["combined_maximum_reservation_usd"])


def test_stability_protocol_rejects_result_dependent_seed_reuse(tmp_path):
    _, _, spec = load_stability_protocol()
    broken = copy.deepcopy(spec)
    broken["request_seed"] = broken["original_run"]["request_seed"]
    path = tmp_path / "stability.json"
    # The copied spec has relative artifact paths that are intentionally absent;
    # use the seed check through a patched absolute base path.
    broken["base_protocol"] = str(
        Path(__file__).parents[2]
        / "src/agents/finance/protocols/realm26_capability_ladder.json"
    )
    broken["manifest"] = str(
        Path(__file__).parents[2]
        / "src/agents/finance/protocols/manifests/realm26_capability_ladder/manifest.json"
    )
    broken["model_snapshot"] = str(
        Path(__file__).parents[2]
        / "src/agents/finance/protocols/snapshots/realm26_capability_stability_openrouter_catalog.json"
    )
    path.write_text(json.dumps(broken))
    with pytest.raises(ProtocolError, match="seed must be prospectively different"):
        load_stability_protocol(path)
