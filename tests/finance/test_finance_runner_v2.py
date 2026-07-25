import json
import pytest

from src.agents.finance.protocol_v2 import DATASETS, build_manifest, stable_json_text
from src.agents.finance.run_finance_experiments import (
    INFRASTRUCTURE_FAILURE,
    MODEL_FAILURE,
    RESULT_SCHEMA_VERSION,
    FinanceExperimentRunner,
    ProtocolError,
    build_parser,
    classify_exception,
)


MODEL = "provider/test-model"


class FakeEnv:
    def __init__(self, rows):
        self.rows = rows


def fake_financebench_rows():
    return [
        {
            "answer": str(idx),
            "evidence": [f"evidence {idx}"],
            "financebench_id": f"fb-{idx}",
            "question": f"question {idx}",
        }
        for idx in range(150)
    ]


def make_protocol(tmp_path):
    protocol = {
        "schema_version": "finance-protocol-v2",
        "protocol_id": "runner_test_v2",
        "seed": 20260709,
        "frameworks": ["direct", "cot", "react", "nexus", "selective"],
        "freeze_state": "frozen",
        "artifact_hashes": {
            "prompts": "sha256:test-prompts",
            "scorers": "sha256:test-scorers",
            "router": "sha256:test-router",
            "price_snapshot": "sha256:test-prices",
            "manifests": {},
        },
        "inference": {"primary": {"model_id": MODEL}},
        "datasets": {
            dataset: {
                "development_indices": list(range(50)),
                "final_count": 100 if dataset == "financebench" else 200,
                "manifest": f"manifests/{dataset}.json",
            }
            for dataset in DATASETS
        },
    }
    rows = fake_financebench_rows()
    manifest = build_manifest(protocol, "financebench", rows)
    protocol["artifact_hashes"]["manifests"]["financebench"] = manifest["manifest_fingerprint"]
    path = tmp_path / "protocol.json"
    path.write_text(stable_json_text(protocol), encoding="utf-8")
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir(exist_ok=True)
    (manifest_dir / "financebench.json").write_text(stable_json_text(manifest), encoding="utf-8")
    return path


def snapshot(model_ids):
    return {"captured_at": "fixed", "models": {model: {"id": model} for model in model_ids}}


def runner(tmp_path, method, **kwargs):
    protocol_path = make_protocol(tmp_path)
    model_snapshotter = kwargs.pop("model_snapshotter", snapshot)
    return FinanceExperimentRunner(
        dataset_id="financebench",
        model_id=MODEL,
        num_examples=kwargs.pop("num_examples", 2),
        frameworks=["direct"],
        results_base_dir=tmp_path / "results",
        results_tag="test",
        protocol=protocol_path,
        method_registry={"direct": method},
        env_factory=lambda _: FakeEnv(fake_financebench_rows()),
        dataset_setter=lambda _: None,
        model_snapshotter=model_snapshotter,
        **kwargs,
    )


def successful_method(calls):
    def method(*, idx, model_id, to_print=False):
        calls.append((idx, model_id, to_print))
        return 1.0, {
            "answer": str(idx),
            "gt_answer": str(idx),
            "native_scores": {"em": 1.0},
            "call_records": [
                {
                    "requested_model": model_id,
                    "resolved_model": model_id,
                    "input_tokens": 10,
                    "cached_tokens": 2,
                    "reasoning_tokens": 0,
                    "output_tokens": 3,
                    "total_tokens": 13,
                    "latency_ms": 5,
                    "estimated_cost_usd": 0.001,
                }
            ],
        }

    return method


def test_model_id_reaches_method_and_result_schema_is_complete(tmp_path):
    calls = []
    experiment = runner(tmp_path, successful_method(calls))
    experiment.run_all()
    assert calls == [(50, MODEL, False), (51, MODEL, False)]
    saved = json.loads(experiment._result_path("direct").read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert {row["example_id"] for row in saved} == {"fb-50", "fb-51"}
    assert all(row["result_schema_version"] == RESULT_SCHEMA_VERSION for row in saved)
    assert all(row["run_id"] == experiment.run_id for row in saved)
    assert all(row["requested_model"] == MODEL == row["resolved_model"] for row in saved)
    assert all(row["input_tokens"] == 10 and row["total_tokens"] == 13 for row in saved)
    assert all(row["status"] == "success" for row in saved)


def test_native_scorer_overrides_legacy_environment_match(tmp_path):
    def misleading_legacy_score(*, idx, model_id, to_print=False):
        return 1.0, {
            "answer": "definitely wrong",
            "gt_answer": str(idx),
            "em": 1.0,
            "f1": 1.0,
            "llm_telemetry": [
                {
                    "requested_model": model_id,
                    "resolved_model": model_id,
                    "status": "ok",
                }
            ],
            "llm_status": "ok",
        }

    experiment = runner(tmp_path, misleading_legacy_score, num_examples=1)
    experiment.run_all()
    saved = json.loads(experiment._result_path("direct").read_text())[0]
    assert saved["native_scores"]["scoring_method"] == "strict_exact_or_numeric_5dp"
    assert saved["native_scores"]["exact_match"] == 0.0
    assert saved["em"] == 0.0


def test_all_five_frameworks_receive_the_explicit_model_id(tmp_path):
    protocol_path = make_protocol(tmp_path)
    calls = []
    method = successful_method(calls)
    frameworks = ["direct", "cot", "react", "nexus", "selective"]
    experiment = FinanceExperimentRunner(
        dataset_id="financebench",
        model_id=MODEL,
        num_examples=1,
        frameworks=frameworks,
        results_base_dir=tmp_path / "results-all",
        protocol=protocol_path,
        method_registry={framework: method for framework in frameworks},
        env_factory=lambda _: FakeEnv(fake_financebench_rows()),
        dataset_setter=lambda _: None,
        model_snapshotter=snapshot,
    )
    experiment.run_all()
    assert calls == [(50, MODEL, False)] * 5
    assert all(experiment._result_path(framework).exists() for framework in frameworks)


def test_resume_skips_exact_completed_pairs_without_duplication(tmp_path):
    calls = []
    runner(tmp_path, successful_method(calls)).run_all()
    resumed_calls = []
    resumed = runner(tmp_path, successful_method(resumed_calls), resume=True)
    resumed.run_all()
    assert resumed_calls == []
    assert len(json.loads(resumed._result_path("direct").read_text())) == 2


def test_only_infrastructure_failure_is_retried_and_replaced(tmp_path):
    attempts = []

    class TypedInfrastructureError(RuntimeError):
        def __init__(self):
            self.status = "infrastructure_error"
            self.metadata = {
                "status": "infrastructure_error",
                "requested_model": MODEL,
                "resolved_model": MODEL,
                "backend": "openrouter",
                "input_tokens": 11,
                "cached_tokens": 2,
                "reasoning_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 11,
                "latency_ms": 123.0,
                "provider_cost_usd": 0.0001,
                "estimated_cost_usd": 0.0001,
                "retry_count": 2,
                "error_type": "Timeout",
                "error_message": "provider timed out",
            }
            super().__init__("provider timed out")

    def timeout(*, idx, model_id, to_print=False):
        attempts.append(idx)
        raise TypedInfrastructureError()

    failed = runner(tmp_path, timeout, num_examples=1)
    failed.run_all()
    saved = json.loads(failed._result_path("direct").read_text())
    assert saved[0]["status"] == INFRASTRUCTURE_FAILURE
    assert saved[0]["llm_call_count"] == 0
    assert saved[0]["llm_attempt_count"] == 3
    assert saved[0]["retry_count"] == 2
    assert saved[0]["input_tokens"] == saved[0]["total_tokens"] == 11
    assert saved[0]["provider_cost_usd"] == 0.0001
    assert len(saved[0]["call_records"]) == 1

    skipped_calls = []
    runner(tmp_path, successful_method(skipped_calls), num_examples=1, resume=True).run_all()
    assert skipped_calls == []

    retry_calls = []
    retried = runner(
        tmp_path,
        successful_method(retry_calls),
        num_examples=1,
        resume=True,
        retry_infrastructure_failures=True,
    )
    retried.run_all()
    saved = json.loads(retried._result_path("direct").read_text())
    assert retry_calls == [(50, MODEL, False)]
    assert len(saved) == 1
    assert saved[0]["status"] == "success"


@pytest.mark.parametrize(
    "error",
    [TimeoutError("timeout"), ConnectionError("connection")],
)
def test_raw_transport_errors_remain_retryable(error):
    assert classify_exception(error) == INFRASTRUCTURE_FAILURE


def test_generic_value_error_is_not_retryable():
    assert classify_exception(ValueError("bad output")) == MODEL_FAILURE


def test_model_failure_is_never_retried(tmp_path):
    def malformed(*, idx, model_id, to_print=False):
        raise ValueError("valid response could not be parsed")

    initial = runner(tmp_path, malformed, num_examples=1)
    initial.run_all()
    assert json.loads(initial._result_path("direct").read_text())[0]["status"] == MODEL_FAILURE
    calls = []
    resumed = runner(
        tmp_path,
        successful_method(calls),
        num_examples=1,
        resume=True,
        retry_infrastructure_failures=True,
    )
    resumed.run_all()
    assert calls == []


def test_exhausted_model_call_status_is_saved_as_model_failure_with_usage(tmp_path):
    def exhausted(*, idx, model_id, to_print=False):
        return 0.0, {
            "answer": "UNKNOWN",
            "llm_status": "error",
            "llm_telemetry": [
                {
                    "resolved_model": model_id,
                    "input_tokens": 7,
                    "output_tokens": 0,
                    "total_tokens": 7,
                    "status": "empty_response",
                }
            ],
        }

    experiment = runner(tmp_path, exhausted, num_examples=1)
    experiment.run_all()
    saved = json.loads(experiment._result_path("direct").read_text())[0]
    assert saved["status"] == MODEL_FAILURE
    assert saved["error_type"] == "ModelOutputFailure"
    assert saved["input_tokens"] == saved["total_tokens"] == 7


def test_callable_without_model_id_is_rejected_before_snapshot(tmp_path):
    def legacy(idx, to_print=False):
        return {}, {}

    experiment = runner(tmp_path, legacy, num_examples=1)
    with pytest.raises(ProtocolError, match="must accept model_id"):
        experiment.run_all()
    assert not experiment.model_snapshot_path.exists()


def test_missing_model_catalog_entry_is_persisted_then_fails_closed(tmp_path):
    experiment = runner(
        tmp_path,
        successful_method([]),
        num_examples=1,
        model_snapshotter=lambda model_ids: {
            "models": {},
            "missing_model_ids": list(model_ids),
            "source": "mock",
        },
    )
    with pytest.raises(ProtocolError, match="absent from OpenRouter catalog"):
        experiment.run_all()
    saved = json.loads(experiment.model_snapshot_path.read_text())
    assert saved["missing_model_ids"] == [MODEL]
    assert not experiment._result_path("direct").exists()


def test_dataset_revision_drift_fails_before_any_model_call(tmp_path):
    calls = []
    experiment = runner(tmp_path, successful_method(calls), num_examples=1)
    revised = fake_financebench_rows()
    revised[50]["question"] = "changed after manifest generation"
    experiment.env_factory = lambda _: FakeEnv(revised)
    with pytest.raises(ProtocolError, match="adapter content differs from frozen manifest"):
        experiment.run_all()
    assert calls == []
    assert not experiment.model_snapshot_path.exists()


def test_final_partition_refuses_unfrozen_protocol(tmp_path):
    protocol_path = make_protocol(tmp_path)
    protocol = json.loads(protocol_path.read_text())
    protocol["freeze_state"] = "foundation_unfrozen"
    protocol["artifact_hashes"]["router"] = None
    protocol_path.write_text(stable_json_text(protocol), encoding="utf-8")
    calls = []
    experiment = FinanceExperimentRunner(
        dataset_id="financebench",
        model_id=MODEL,
        num_examples=1,
        frameworks=["direct"],
        results_base_dir=tmp_path / "unfrozen-results",
        protocol=protocol_path,
        method_registry={"direct": successful_method(calls)},
        env_factory=lambda _: FakeEnv(fake_financebench_rows()),
        dataset_setter=lambda _: None,
        model_snapshotter=snapshot,
    )
    with pytest.raises(ProtocolError, match="freeze_state='frozen'"):
        experiment.run_all()
    assert calls == []


def test_cli_exposes_protocol_model_framework_resume_contract():
    args = build_parser().parse_args(
        [
            "--protocol",
            "finance_icaif26_v2",
            "--dataset",
            "finqa",
            "--model-id",
            MODEL,
            "--frameworks",
            "direct",
            "cot",
            "react",
            "nexus",
            "selective",
            "--results-tag",
            "paper",
            "--resume",
            "--retry-infrastructure-failures",
        ]
    )
    assert args.protocol == "finance_icaif26_v2"
    assert args.model_id == MODEL
    assert args.frameworks == ["direct", "cot", "react", "nexus", "selective"]
    assert args.resume and args.retry_infrastructure_failures
