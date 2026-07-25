import json
from pathlib import Path

import pytest

from src.agents.finance.protocol_v2 import ProtocolError, fingerprint
from src.agents.finance.realm26_harmonized_methods import run_react, run_static, strict_action
from src.agents.finance.realm26_harmonized_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    build_manifest,
    load_manifest,
    load_protocol,
    resolve_path,
    validate_frozen_artifacts,
)
from src.agents.finance.run_realm26_harmonized_replication import (
    SpendLedger,
    StopExperiment,
    public_freeze_preflight,
)
from src.shared.llm_telemetry import LLMResult


def test_strict_contract_has_identical_unknown_fallback():
    malformed = ["Answer: 7", "```json\n{}\n```", '{"action":"Finish"}', ""]
    for output in malformed:
        assert strict_action(output, static=True)["answer"] == "UNKNOWN"
        assert strict_action(output, static=False)["answer"] == "UNKNOWN"
        assert strict_action(output, static=True)["parse_status"] == "malformed_fallback"
        assert strict_action(output, static=False)["parse_status"] == "malformed_fallback"
    valid = strict_action('{"thought":"calc","action":"Finish","answer":"$7 million"}', static=True)
    assert valid == {"thought": "calc", "action": "Finish", "answer": "$7 million", "parse_status": "ok"}


class FakeEnv:
    def __init__(self):
        self.actions = []

    def reset(self, idx):
        return "What is the 2025 value?"

    def step(self, action):
        self.actions.append(action)
        if action.startswith("Finish["):
            answer = action[7:-1]
            return "done", float(answer == "7"), True, {
                "answer": answer,
                "gt_answer": "7",
                "gold_scale": "",
                "question_type": "arithmetic",
            }
        return " ".join(f"evidence-{n}" for n in range(500)), 0.0, False, {}


def llm_sequence(outputs):
    queue = list(outputs)
    prompts = []

    def call(prompt, model_id=None, **kwargs):
        prompts.append(prompt)
        return LLMResult(
            text=queue.pop(0),
            requested_model=model_id,
            resolved_model=model_id,
            backend="openrouter",
            input_tokens=20,
            output_tokens=8,
            total_tokens=28,
            provider_cost_usd=0.00001,
            latency_ms=1.0,
        )

    call.prompts = prompts
    return call


def test_both_methods_enforce_shared_context_evidence_output_and_scorer_answer_contract():
    static_llm = llm_sequence(['{"thought":"calc","action":"Finish","answer":"7"}'])
    _, static = run_static(
        1,
        "model",
        env=FakeEnv(),
        llm_func=static_llm,
        evidence_word_budget=80,
        context_word_budget=180,
        max_retrieval_operations=3,
        max_output_tokens=384,
    )
    react_llm = llm_sequence([
        '{"thought":"find","action":"Search","argument":"2025 value"}',
        '{"thought":"calc","action":"Finish","answer":"7"}',
    ])
    _, react = run_react(
        1,
        "model",
        env=FakeEnv(),
        llm_func=react_llm,
        evidence_word_budget=80,
        context_word_budget=180,
        max_retrieval_operations=3,
        max_output_tokens=384,
        max_steps=7,
    )
    for result in (static, react):
        assert result["answer"] == "7"
        assert result["evidence_word_count"] <= 80
        assert result["max_prompt_word_count"] <= 180
        assert result["parse_status"] == "ok"
    assert static["n_calls"] == 1
    assert react["n_calls"] == 2
    assert all(len(prompt.split()) <= 180 for prompt in static_llm.prompts + react_llm.prompts)


def test_real_manifest_excludes_original_development_second_family_and_final_identifiers():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    manifest = load_manifest(protocol)
    source_path = resolve_path(Path(protocol["_path"]), protocol["exclusions"]["original_protocol"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    second_path = resolve_path(Path(protocol["_path"]), protocol["exclusions"]["second_family_manifest"])
    second = json.loads(second_path.read_text(encoding="utf-8"))
    assert sum(len(manifest["datasets"][dataset]["examples"]) for dataset in DATASETS) == 150
    for dataset in DATASETS:
        source_manifest_path = source_path.parent / source["datasets"][dataset]["manifest"]
        original = json.loads(source_manifest_path.read_text(encoding="utf-8"))
        reserved = set(original["development"]["indices"]) | set(original["final"]["indices"])
        reserved |= {int(item["index"]) for item in second["datasets"][dataset]["examples"]}
        selected = {int(item["index"]) for item in manifest["datasets"][dataset]["examples"]}
        assert len(selected) == 50
        assert selected.isdisjoint(reserved)
        assert manifest["datasets"][dataset]["exclusion_counts"] == {
            "original_development": 50,
            "sealed_final_identifiers": 200,
            "second_family": 25,
            "total": 275,
        }


def test_analysis_metric_keys_and_directional_rule_are_frozen_to_serialized_fields():
    analysis = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)["analysis"]
    assert analysis["dataset_quality_metrics"] == {
        "convfinqa": "native_scores.exact_match",
        "finqa": "native_scores.exact_match",
        "tatqa": "native_scores.f1",
    }
    assert set(analysis["directional_interpretation"]) == {
        "static_advantage", "react_advantage", "inconclusive"
    }


class GuardedRows:
    def __init__(self, dataset, reserved):
        self.dataset = dataset
        self.reserved = set(reserved)

    def __len__(self):
        return 500

    def context_for_index(self, idx):
        return int(idx)

    def __getitem__(self, idx):
        if idx in self.reserved:
            raise AssertionError("reserved/final content was dereferenced")
        row = {"source_id": f"{self.dataset}-{idx}", "question": f"q{idx}", "answer": str(idx), "evidence": [f"e{idx}"]}
        if self.dataset == "tatqa":
            row.update({"question_type": "arithmetic", "answer_from": "table"})
        if self.dataset == "convfinqa":
            row["dialogue_id"] = f"dialogue-{idx}"
        return row


def test_manifest_builder_never_dereferences_reserved_rows(monkeypatch):
    reserved = set(range(275))
    exclusions = {
        "indices": reserved,
        "example_ids": {f"reserved-{idx}" for idx in reserved},
        "dialogue_hashes": {fingerprint(f"reserved-dialogue-{idx}") for idx in reserved},
        "counts": {"original_development": 50, "sealed_final_identifiers": 200, "second_family": 25, "total": 275},
        "fingerprint": "sha256:test",
        "original_manifest_fingerprint": "sha256:original",
        "second_manifest_fingerprint": "sha256:second",
    }
    monkeypatch.setattr(
        "src.agents.finance.realm26_harmonized_protocol._identifier_exclusions",
        lambda protocol, dataset: exclusions,
    )
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)

    class Factory:
        def __call__(self, dataset):
            return type("Env", (), {"rows": GuardedRows(dataset, reserved)})()

    manifest = build_manifest(protocol, Factory())
    assert all(len(manifest["datasets"][dataset]["examples"]) == 50 for dataset in DATASETS)


def test_spend_ledger_cap_is_exact_and_duplicate_call_keys_fail(tmp_path):
    ledger = SpendLedger(tmp_path / "ledger.json", "sha256:test", 5.0)
    ledger.reserve("call", 1.0, "sha256:prompt")
    result = LLMResult(
        text="ok",
        requested_model="model",
        resolved_model="model",
        backend="openrouter",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        provider_cost_usd=0.5,
    )
    ledger.complete("call", result, 0.5)
    with pytest.raises(StopExperiment, match="Duplicate"):
        ledger.reserve("call", 1.0, "sha256:prompt")
    with pytest.raises(StopExperiment, match="USD 5"):
        ledger.reserve("next", 4.51, "sha256:prompt2")
    with pytest.raises(StopExperiment, match="USD 5"):
        SpendLedger(tmp_path / "other.json", "sha256:test", 15.0)


def test_public_push_guard_fails_before_execution(monkeypatch):
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    calls = []

    def fake_git(repo, *args):
        calls.append(args)
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return "/repo"
        if args[:2] == ("branch", "--show-current"):
            return protocol["publication"]["branch"]
        if args[:2] == ("rev-parse", "HEAD"):
            return "abc"
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[:2] == ("ls-remote", "--heads"):
            return "def\trefs/heads/realm26/prompt-context-harmonized-replication"
        raise AssertionError(args)

    monkeypatch.setattr("src.agents.finance.run_realm26_harmonized_replication._git", fake_git)
    with pytest.raises(StopExperiment, match="publicly pushed"):
        public_freeze_preflight(protocol)


@pytest.mark.parametrize("name", [
    "analysis", "attestation", "base_methods", "data_adapter", "executor",
    "finance_env", "finance_statistics", "finance_utils", "llm_telemetry",
    "llm_wrapper", "manifest", "methods", "model_snapshot", "prompts",
    "protocol_guard", "protocol_memo", "protocol_utils", "pytest_config",
    "runner_telemetry", "scorers",
])
def test_all_acceptance_critical_artifacts_are_hashed(name):
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    assert name in protocol["artifact_hashes"]


def test_frozen_hash_tampering_fails_closed():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    protocol["artifact_hashes"] = dict(protocol["artifact_hashes"])
    protocol["artifact_hashes"]["methods"] = "sha256:" + "0" * 64
    with pytest.raises(ProtocolError, match="hash mismatch"):
        validate_frozen_artifacts(protocol)
