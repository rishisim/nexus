import itertools
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import src.agents.finance.run_realm26_capability_ladder as runner_module
from src.agents.finance.run_realm26_capability_ladder import (
    BudgetedCapabilityModel,
    CapabilityRunner,
    CumulativeBudgetGuard,
    StopExperiment,
    build_parser,
    cumulative_budget_contract,
    normalized_execution_schedule,
)
from src.shared.llm_telemetry import LLMResult


TIERS = ("control", "luna", "terra")
DATASETS = ("finqa", "tatqa", "convfinqa")


def scheduled_manifest():
    examples = {
        dataset: {
            "examples": [
                {"example_id": f"{dataset}-{offset}", "index": offset, "item_hash": f"sha256:{dataset}-{offset}"}
                for offset in range(50)
            ]
        }
        for dataset in DATASETS
    }
    permutations = list(itertools.permutations(TIERS))
    items = []
    for position in range(150):
        dataset = DATASETS[position // 50]
        example_id = f"{dataset}-{position % 50}"
        items.append({
            "position": position,
            "dataset_id": dataset,
            "example_id": example_id,
            "model_order": list(permutations[position % 6]),
            "framework_order_by_tier": {
                tier: (["static", "react"] if (position + tier_index) % 2 == 0 else ["react", "static"])
                for tier_index, tier in enumerate(TIERS)
            },
        })
    return {
        "datasets": examples,
        "execution_schedule": {"schedule_seed": 20260802, "items": items},
        "manifest_fingerprint": "sha256:test",
    }


def test_schedule_runs_all_tiers_and_arms_in_frozen_counterbalanced_order():
    manifest = scheduled_manifest()
    episodes = normalized_execution_schedule(manifest, tiers=TIERS)
    assert len(episodes) == 150 * 3 * 2
    first = manifest["execution_schedule"]["items"][0]
    assert episodes[:6] == [
        ("finqa", "finqa-0", tier, framework)
        for tier in first["model_order"]
        for framework in first["framework_order_by_tier"][tier]
    ]
    assert {tier for _, _, tier, _ in episodes} == set(TIERS)


def test_schedule_rejects_a_missing_tier_before_inference():
    manifest = scheduled_manifest()
    manifest["execution_schedule"]["items"][0]["model_order"] = ["control", "luna"]
    with pytest.raises(StopExperiment, match="mandatory tier"):
        normalized_execution_schedule(manifest, tiers=TIERS)


def test_single_study_command_has_no_tier_or_benchmark_smoke_switch():
    parser = build_parser()
    assert {action.dest for action in parser._actions} == {"help", "protocol", "preflight_only", "format_probes"}
    with pytest.raises(SystemExit):
        parser.parse_args(["--tier", "luna"])


def test_budget_reserves_prior_attempts_probes_and_complete_study():
    protocol = {
        "budget": {
            "hard_cap_usd": 20.0,
            "prior_failed_attempt_allowance_usd": 0.0128,
            "format_probe_prior_attempt_allowance_usd": 0.004,
            "format_probe_actual_spend_usd": 0.006,
            "study_maximum_reservation_usd": 19.9,
        },
        "models": {
            tier: {"maximum_reserved_call_cost_usd": 0.01}
            for tier in TIERS
        },
    }
    contract = cumulative_budget_contract(protocol)
    assert contract["reserved_study_cost_usd"] == 19.9
    assert contract["prior_failed_attempt_spend_usd"] == 0.0128
    assert contract["format_probe_spend_usd"] == 0.01


@dataclass
class FakeCapabilityResponse:
    result: LLMResult
    finish_reason: str = "stop"


def test_one_global_ledger_accounts_for_calls_from_every_tier(tmp_path):
    contract = {
        "cumulative_hard_cap_usd": 1.0,
        "prior_failed_attempt_spend_usd": 0.1,
        "format_probe_spend_usd": 0.2,
    }
    models = {tier: {"maximum_reserved_call_cost_usd": 0.05} for tier in TIERS}
    path = tmp_path / "cumulative_spend_ledger.json"
    ledger = CumulativeBudgetGuard(contract, path=path, protocol_fingerprint="sha256:test", models=models)
    response = FakeCapabilityResponse(LLMResult(
        text='{"action":"Finish","argument":"","answer":"1"}',
        requested_model="model", resolved_model="model", backend="openrouter",
        input_tokens=1, output_tokens=1, total_tokens=2,
        latency_ms=1.0, provider_cost_usd=0.01, status="ok",
    ))
    ledger.tier_view("control").reserve("control/call-1", "sha256:a")
    ledger.tier_view("control").complete("control/call-1", response, 0.01)
    ledger.tier_view("terra").reserve("terra/call-1", "sha256:b")
    ledger.tier_view("terra").complete("terra/call-1", response, 0.01)
    assert ledger.current_spend == pytest.approx(0.32)
    assert {row["tier"] for row in json.loads(path.read_text())["calls"]} == {"control", "terra"}


def test_budgeted_model_enforces_frozen_shared_delay_before_provider_call(monkeypatch):
    events = []

    class FakeLedger:
        def reserve(self, call_key, prompt_hash):
            events.append(("reserve", call_key, prompt_hash))

        def complete(self, call_key, response, estimated_cost):
            events.append(("complete", call_key, estimated_cost))

    response = SimpleNamespace(
        result=LLMResult(
            text='{"action":"Finish","argument":"","answer":"1"}',
            requested_model="openai/gpt-4o-mini",
            resolved_model="openai/gpt-4o-mini",
            backend="openrouter",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            latency_ms=1.0,
            provider_cost_usd=0.00001,
            estimated_cost_usd=0.00001,
            status="ok",
        ),
        finish_reason="stop",
        provider_name="OpenAI",
        request_parameters={"action_schema": "finish"},
    )
    monkeypatch.setattr(runner_module, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(runner_module, "call_capability_model", lambda **kwargs: response)
    protocol = {
        "inference": {"inter_call_delay_seconds": 0.1, "request_seed": 20260802},
        "workflows": {"max_output_tokens_per_call": 384},
        "models": {
            "control": {
                "requested_model_id": "openai/gpt-4o-mini",
                "canonical_slug": "openai/gpt-4o-mini",
            }
        },
    }
    snapshot = {
        "models": {
            "control": {
                "openai_endpoint": {
                    "pricing": {"prompt": 0.00000015, "completion": 0.0000006, "input_cache_read": 0.00000015}
                }
            }
        }
    }
    model = BudgetedCapabilityModel(protocol, snapshot, FakeLedger(), "control", "finqa/example", "static")
    model("prompt", model_id="openai/gpt-4o-mini")

    assert events[0] == ("sleep", 0.1)
    assert events[1][0] == "reserve"
    assert events[2][0] == "complete"


def test_completion_record_is_withheld_until_every_tier_is_complete(tmp_path):
    runner = object.__new__(CapabilityRunner)
    runner.completion_path = tmp_path / "study_complete.json"
    runner.history_path = tmp_path / "run_history.json"
    runner.protocol_fingerprint = "sha256:test"
    runner.pre_result_commit = "abc123"
    runner.manifest = {"execution_schedule": {"items": [{}]}}
    runner.budget_guard = type("Budget", (), {"current_spend": 0.5})()
    runner._pending = lambda: []
    runner._completion_counts = lambda: {"control": 2, "luna": 2, "terra": 1}
    with pytest.raises(StopExperiment, match="three mandatory tiers"):
        runner.run()
    assert not runner.completion_path.exists()
