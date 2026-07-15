import csv
import io
from pathlib import Path

import pytest

from src.agents.finance.audit_realm_fairness import (
    EXPECTED_ONE_SIDED,
    _load_rows,
    audit_csv,
    build_audit,
    classify_failure,
    frozen_both_wrong_sample,
    scorer_sensitive_candidate,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def result(
    example_id,
    *,
    framework="react",
    correct=False,
    answer="wrong",
    ground_truth="right",
    calls=1,
    retrievals=1,
    trace="Action 1: Finish[wrong]",
):
    return {
        "example_id": example_id,
        "framework": framework,
        "answer": answer,
        "ground_truth": ground_truth,
        "native_scores": {"exact_match": 1.0 if correct else 0.0},
        "llm_call_count": calls,
        "llm_attempt_count": calls,
        "retrieval_operation_count": retrievals,
        "retry_count": 0,
        "raw_trace": trace,
    }


@pytest.mark.parametrize(
    ("prediction", "reference", "reason"),
    [
        (
            "The amount was $1,577 million.",
            "$1577.00",
            "reference_numeric_value_appears_in_prediction",
        ),
        (
            "The company distributes content in over 50 countries.",
            "over 50 countries",
            "normalized_reference_span_appears_in_prediction",
        ),
        (
            "-39.90%",
            "-0.39896",
            "rounded_reference_numeric_value_appears_in_prediction",
        ),
    ],
)
def test_scorer_sensitive_candidates_are_deterministic_not_corrected_labels(
    prediction, reference, reason
):
    assert scorer_sensitive_candidate(prediction, reference) == reason


def test_distant_numeric_mismatch_is_not_a_scorer_sensitive_candidate():
    assert scorer_sensitive_candidate("1.42%", "0.01") is None


def test_failure_rules_preserve_mechanical_and_review_boundaries():
    forced = result(
        "forced",
        answer="UNKNOWN",
        calls=7,
        retrievals=7,
        trace="\n".join(
            [f"Action {step}: Search[q{step}]" for step in range(1, 8)]
            + ["Action 8: Finish[UNKNOWN]"]
        ),
    )
    assert classify_failure(forced) == {
        "signal": "forced_nontermination",
        "confidence": "high",
        "ambiguous": False,
        "manual_review_required": False,
        "rule_evidence": "seven model calls were followed by adapter-added Finish[UNKNOWN]",
    }

    premature = result("early", retrievals=0)
    assert classify_failure(premature)["signal"] == "premature_finish_no_retrieval"

    candidate = result(
        "candidate", answer="The final amount is 1,577 million.", ground_truth="$1577.00"
    )
    classification = classify_failure(candidate)
    assert classification["signal"] == "scorer_sensitive_candidate"
    assert classification["manual_review_required"] is True


def test_both_wrong_sample_is_hash_ranked_and_order_independent():
    pairs = [
        (result(str(index), framework="nexus"), result(str(index)))
        for index in range(12)
    ]
    selected = frozen_both_wrong_sample(pairs, "finqa", count=5)
    reversed_selected = frozen_both_wrong_sample(reversed(pairs), "finqa", count=5)
    assert [item[0] for item in selected] == sorted(item[0] for item in selected)
    assert [item[1]["example_id"] for item in selected] == [
        item[1]["example_id"] for item in reversed_selected
    ]


def test_loader_refuses_any_final_partition_path():
    with pytest.raises(ValueError, match="sealed-final"):
        _load_rows(Path("/tmp/final/results.json"))


def test_repository_audit_reproduces_locked_disagreements_and_csv():
    audit = build_audit(REPO_ROOT)
    assert audit["scope"]["sealed_final_partition_accessed"] is False
    assert audit["scope"]["external_provider_calls"] == 0
    assert audit["summary"]["one_sided"] == EXPECTED_ONE_SIDED
    assert audit["summary"]["selection_counts"] == {
        "both_wrong_frozen_sample": 20,
        "one_sided": 52,
    }
    assert len(audit["trace_items"]) == 72
    assert {item["label_source"] for item in audit["trace_items"]} == {
        "deterministic_trace_rule_v1"
    }

    csv_rows = list(csv.DictReader(io.StringIO(audit_csv(audit))))
    assert len(csv_rows) == 72
    assert {row["item_id"] for row in csv_rows} == {
        item["item_id"] for item in audit["trace_items"]
    }
