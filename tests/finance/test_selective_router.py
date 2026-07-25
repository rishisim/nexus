import json

import numpy as np
import pytest

from src.agents.finance.selective_router import (
    FEATURE_NAMES,
    DevelopmentExample,
    SelectiveRouter,
    extract_router_features,
    feature_vector,
    train_selective_router,
)


def make_features(index=0, *, signal=0.0, narrative=0.0):
    features = {name: 0.0 for name in FEATURE_NAMES}
    features.update(
        {
            "question_char_count": 30.0 + index,
            "question_token_count": 7.0,
            "evidence_char_count": 400.0,
            "evidence_token_count": 70.0,
            "numeric_count": signal,
            "operator_count": signal,
            "period_count": 1.0,
            "entity_count": 1.0,
            "has_narrative": narrative,
            "lexical_coverage": 0.2 + (index % 6) / 10.0,
            "retrieval_top_score": 4.0,
            "retrieval_second_score": 2.0,
            "retrieval_score_margin": 0.1 + (index % 5) / 10.0,
            "chunk_count": 3.0,
            "chunk_dispersion": 0.25,
        }
    )
    return features


def test_feature_extractor_uses_only_frozen_pre_answer_schema():
    features = extract_router_features(
        "How much did ACME revenue increase from FY2024 to FY2025?",
        ["Table:\nPeriod | Revenue\nFY2024 | 10\nFY2025 | 15"],
        evidence_stats={
            "evidence_chunk_count": 4,
            "evidence_char_count": 500,
            "evidence_token_count": 90,
            "lexical_coverage": 0.75,
            "top_score": 6.0,
            "second_score": 4.0,
            "score_margin": 2.0,
            "chunk_dispersion": 0.8,
        },
    )

    assert tuple(features) == FEATURE_NAMES
    assert features["numeric_count"] == 2.0
    assert features["period_count"] == 2.0
    assert features["operator_count"] >= 1.0
    assert features["has_table"] == 1.0
    assert features["lexical_coverage"] == 0.75
    assert features["retrieval_score_margin"] == 2.0
    assert features["chunk_count"] == 4.0
    assert not any("answer" in key or "gold" in key for key in features)


@pytest.mark.parametrize("forbidden", ["gold_answer", "derivation", "scale", "target_label"])
def test_feature_schema_rejects_target_derived_inputs(forbidden):
    features = make_features()
    features[forbidden] = 1.0
    with pytest.raises(ValueError, match="forbidden"):
        feature_vector(features)


def test_feature_schema_rejects_missing_or_unknown_inputs():
    missing = make_features()
    missing.pop("chunk_dispersion")
    with pytest.raises(ValueError, match="missing"):
        feature_vector(missing)

    unknown = make_features()
    unknown["dataset_id"] = 1.0
    with pytest.raises(ValueError, match="unknown"):
        feature_vector(unknown)


def learned_examples():
    examples = []
    # Thirty benefit cases ensure at least six positives in every validation
    # fold; their strong pre-answer signal yields a valid learned artifact.
    for index in range(100):
        benefit = index < 30
        examples.append(
            DevelopmentExample(
                features=make_features(index, signal=5.0 if benefit else 0.0),
                static_correct=not benefit,
                react_correct=True,
                static_cost=1.0,
                react_cost=6.0,
            )
        )
    return examples


def test_training_is_deterministic_standardized_l2_and_uses_cheapest_valid_threshold():
    first = train_selective_router(learned_examples())
    second = train_selective_router(learned_examples())

    assert first.fallback_used is False
    assert first.router.mode == "learned"
    assert first.cv_auc == pytest.approx(1.0)
    assert first.selected_accuracy >= max(first.static_accuracy, first.react_accuracy) - 0.01
    # The frozen one-point slack permits one missed benefit case, so the
    # cheapest admissible threshold escalates 29 rather than all 30 cases.
    assert first.selected_escalation_rate == pytest.approx(0.29)
    assert first.selected_mean_cost == pytest.approx(2.45)
    assert first.router.to_dict() == second.router.to_dict()
    assert len(first.router.coefficients) == len(FEATURE_NAMES)
    assert all(scale > 0 for scale in first.router.scales)


def test_learned_router_routes_signal_cases_and_serializes_round_trip(tmp_path):
    report = train_selective_router(learned_examples())
    path = tmp_path / "router.json"
    report.router.save(path)
    loaded = SelectiveRouter.load(path)

    positive = loaded.decide(make_features(1, signal=5.0))
    negative = loaded.decide(make_features(80, signal=0.0))

    assert positive.route == "react"
    assert negative.route == "nexus"
    assert positive.benefit_probability > negative.benefit_probability
    assert json.loads(path.read_text()) == report.router.to_dict()


def test_fewer_than_five_benefit_examples_per_fold_uses_preregistered_rule():
    examples = []
    for index in range(50):
        benefit = index < 10
        examples.append(
            DevelopmentExample(
                features=make_features(index, narrative=float(benefit)),
                static_correct=not benefit,
                react_correct=True,
            )
        )

    report = train_selective_router(examples)

    assert report.fallback_used is True
    assert report.router.mode == "rule"
    assert "fewer than five" in report.fallback_reason
    assert report.router.coverage_median == pytest.approx(
        np.median([example.features["lexical_coverage"] for example in examples])
    )
    assert report.router.margin_q25 == pytest.approx(
        np.quantile([example.features["retrieval_score_margin"] for example in examples], 0.25)
    )


def test_cross_validated_auc_below_point_six_uses_preregistered_rule():
    examples = []
    for index in range(50):
        benefit = index < 25
        # Constant model inputs force an AUROC of 0.5 while each fold still has
        # exactly five usable benefit examples.
        features = make_features(0)
        examples.append(
            DevelopmentExample(
                features=features,
                static_correct=not benefit,
                react_correct=True,
            )
        )

    report = train_selective_router(examples)

    assert report.fallback_used is True
    assert report.cv_auc == pytest.approx(0.5)
    assert "AUROC" in report.fallback_reason


def test_rule_gate_matches_frozen_or_conditions():
    router = SelectiveRouter(
        mode="rule",
        threshold=None,
        coverage_median=0.5,
        margin_q25=0.2,
    )
    safe = make_features()
    safe["lexical_coverage"] = 0.5
    safe["retrieval_score_margin"] = 0.3
    low_coverage = dict(safe, lexical_coverage=0.49)
    low_margin = dict(safe, retrieval_score_margin=0.2)
    narrative = dict(safe, has_narrative=1.0)

    assert router.decide(safe).route == "nexus"
    assert router.decide(low_coverage).route == "react"
    assert router.decide(low_margin).route == "react"
    assert router.decide(narrative).route == "react"
