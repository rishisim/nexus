import json
from pathlib import Path

import pytest

from src.agents.finance.protocol_v2 import ProtocolError, fingerprint
from src.agents.finance.realm26_harmonized_v2_methods import (
    REACT_ACTION_POLICY,
    ReActPolicyViolation,
    run_react_v2,
    run_static_v2,
)
from src.agents.finance.realm26_harmonized_v2_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    _artifact_paths,
    build_manifest,
    load_manifest,
    load_protocol,
    resolve_path,
    validate_protocol,
)
from src.agents.finance.run_realm26_harmonized_v2_replication import (
    HarmonizedV2Runner,
    StopExperiment,
)
from src.shared.llm_telemetry import LLMResult


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
        return "relevant 2025 evidence value 7", 0.0, False, {}


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


def method_kwargs(env, llm):
    return {
        "env": env,
        "llm_func": llm,
        "evidence_word_budget": 80,
        "context_word_budget": 220,
        "max_retrieval_operations": 3,
        "max_output_tokens": 384,
        "max_steps": 7,
    }


@pytest.mark.parametrize(
    "first_output",
    [
        '{"thought":"abstain","action":"Finish","answer":"UNKNOWN"}',
        '{"thought":"lookup","action":"Lookup","argument":"2025"}',
        "malformed",
    ],
)
def test_react_v2_fails_closed_unless_first_model_action_is_search(first_output):
    env = FakeEnv()
    with pytest.raises(ReActPolicyViolation, match="first|First"):
        run_react_v2(1, "model", **method_kwargs(env, llm_sequence([first_output])))
    assert env.actions == []


def test_v2_methods_enact_and_record_the_frozen_process_contract():
    static_llm = llm_sequence(['{"thought":"calc","action":"Finish","answer":"7"}'])
    _, static = run_static_v2(1, "model", **method_kwargs(FakeEnv(), static_llm))
    react_llm = llm_sequence([
        '{"thought":"find","action":"Search","argument":"2025 value"}',
        '{"thought":"calc","action":"Finish","answer":"7"}',
    ])
    _, react = run_react_v2(1, "model", **method_kwargs(FakeEnv(), react_llm))
    assert static["method_version"] == "realm26_harmonized_v2"
    assert static["n_calls"] == 1
    assert static["react_action_policy"] is None
    assert react["method_version"] == "realm26_harmonized_v2"
    assert react["first_model_action"] == "Search"
    assert react["model_actions"] == ["Search", "Finish"]
    assert react["react_action_policy"] == REACT_ACTION_POLICY
    assert react["react_process_integrity"] is True
    assert react["retrieval_operation_count"] == 1
    assert react["evidence_word_count"] > 0
    assert react["n_calls"] == 2
    assert all(len(prompt.split()) <= 220 for prompt in static_llm.prompts + react_llm.prompts)


def test_real_v2_manifest_excludes_original_second_family_v1_and_final_identifiers():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    manifest = load_manifest(protocol)
    source_path = resolve_path(Path(protocol["_path"]), protocol["exclusions"]["original_protocol"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    second = json.loads(resolve_path(Path(protocol["_path"]), protocol["exclusions"]["second_family_manifest"]).read_text(encoding="utf-8"))
    v1 = json.loads(resolve_path(Path(protocol["_path"]), protocol["exclusions"]["v1_manifest"]).read_text(encoding="utf-8"))
    assert sum(len(manifest["datasets"][dataset]["examples"]) for dataset in DATASETS) == 150
    for dataset in DATASETS:
        original = json.loads((source_path.parent / source["datasets"][dataset]["manifest"]).read_text(encoding="utf-8"))
        reserved = set(original["development"]["indices"]) | set(original["final"]["indices"])
        reserved |= {int(item["index"]) for item in second["datasets"][dataset]["examples"]}
        reserved |= {int(item["index"]) for item in v1["datasets"][dataset]["examples"]}
        selected = {int(item["index"]) for item in manifest["datasets"][dataset]["examples"]}
        assert len(selected) == 50
        assert selected.isdisjoint(reserved)
        assert manifest["datasets"][dataset]["exclusion_counts"] == {
            "harmonized_v1": 50,
            "original_development": 50,
            "sealed_final_identifiers": 200,
            "second_family": 25,
            "total": 325,
        }


class GuardedRows:
    def __init__(self, dataset, reserved):
        self.dataset = dataset
        self.reserved = set(reserved)

    def __len__(self):
        return 600

    def context_for_index(self, idx):
        return int(idx)

    def __getitem__(self, idx):
        if idx in self.reserved:
            raise AssertionError("reserved/final content was dereferenced")
        row = {
            "answer": str(idx),
            "evidence": [f"e{idx}"],
            "question": f"q{idx}",
            "source_id": f"{self.dataset}-{idx}",
        }
        if self.dataset == "tatqa":
            row.update({"answer_from": "table", "question_type": "arithmetic"})
        if self.dataset == "convfinqa":
            row["dialogue_id"] = f"dialogue-{idx}"
        return row


def test_v2_manifest_builder_never_dereferences_any_reserved_row(monkeypatch):
    reserved = set(range(325))
    exclusions = {
        "counts": {
            "harmonized_v1": 50,
            "original_development": 50,
            "sealed_final_identifiers": 200,
            "second_family": 25,
            "total": 325,
        },
        "dialogue_hashes": {fingerprint(f"reserved-dialogue-{idx}") for idx in reserved},
        "example_ids": {f"reserved-{idx}" for idx in reserved},
        "fingerprint": "sha256:test",
        "indices": reserved,
        "original_manifest_fingerprint": "sha256:original",
        "second_manifest_fingerprint": "sha256:second",
        "v1_manifest_fingerprint": "sha256:v1",
    }
    monkeypatch.setattr(
        "src.agents.finance.realm26_harmonized_v2_protocol._identifier_exclusions",
        lambda protocol, dataset: exclusions,
    )
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)

    class Factory:
        def __call__(self, dataset):
            return type("Env", (), {"rows": GuardedRows(dataset, reserved)})()

    manifest = build_manifest(protocol, Factory())
    assert all(len(manifest["datasets"][dataset]["examples"]) == 50 for dataset in DATASETS)


def test_smoke_process_check_reads_only_predeclared_process_fields():
    runner = object.__new__(HarmonizedV2Runner)
    runner.protocol = {
        "smoke": {"dataset": "finqa", "item_ordinal": 0},
        "workflows": {"react_min_evidence_operations": 1, "react_min_model_calls": 2},
    }
    runner.manifest = {"datasets": {"finqa": {"examples": [{"example_id": "item"}]}}}
    rows = {
        "static": [{"example_id": "item", "llm_call_count": 1}],
        "react": [{
            "evidence_word_count": 4,
            "example_id": "item",
            "first_model_action": "Search",
            "llm_call_count": 2,
            "native_scores": object(),
            "parse_status": "ok",
            "react_process_integrity": True,
            "retrieval_operation_count": 1,
        }],
    }
    runner._load = lambda dataset, framework: rows[framework]
    checks = runner._smoke_process_check()
    assert checks and all(checks.values())


def test_v2_protocol_pins_fresh_sample_smoke_and_publication_contracts():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    assert protocol["seed"] == 20260720
    assert protocol["publication"]["branch"] == "realm26/harmonized-replication-v2"
    assert protocol["smoke"]["process_checks"]["forbid_answer_or_score_access"] is True
    changed = dict(protocol)
    changed["seed"] = 20260721
    with pytest.raises(ProtocolError, match="seed"):
        validate_protocol(changed)


@pytest.mark.parametrize("name", [
    "analysis", "attestation", "base_methods", "data_adapter", "executor",
    "finance_env", "finance_statistics", "finance_utils", "llm_telemetry",
    "llm_wrapper", "manifest", "methods", "model_snapshot", "prompts",
    "protocol_guard", "protocol_memo", "protocol_utils", "pytest_config",
    "runner_telemetry", "scorers", "v1_harmonized_methods",
    "tests", "v1_harmonized_prompts", "v1_manifest",
])
def test_all_v2_acceptance_critical_artifacts_are_hash_bound(name):
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH, validate_artifacts=False)
    assert name in protocol["artifact_hashes"]
    assert name in _artifact_paths(protocol)


def test_v2_frozen_artifact_hashes_validate_end_to_end():
    protocol = load_protocol(DEFAULT_PROTOCOL_PATH)
    assert protocol["protocol_id"] == "realm26_harmonized_static_react_v2"


def test_smoke_process_check_fails_closed_on_v1_style_abstention():
    runner = object.__new__(HarmonizedV2Runner)
    runner.protocol = {
        "smoke": {"dataset": "finqa", "item_ordinal": 0},
        "workflows": {"react_min_evidence_operations": 1, "react_min_model_calls": 2},
    }
    runner.manifest = {"datasets": {"finqa": {"examples": [{"example_id": "item"}]}}}
    rows = {
        "static": [{"example_id": "item", "llm_call_count": 1}],
        "react": [{
            "evidence_word_count": 0,
            "example_id": "item",
            "first_model_action": "Finish",
            "llm_call_count": 1,
            "parse_status": "ok",
            "react_process_integrity": False,
            "retrieval_operation_count": 0,
        }],
    }
    runner._load = lambda dataset, framework: rows[framework]
    with pytest.raises(StopExperiment, match="manipulation"):
        runner._smoke_process_check()
