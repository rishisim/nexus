import json
from pathlib import Path

import pytest

from src.agents.finance import analyze_realm26_capability_ladder as analysis
from src.agents.finance.protocol_v2 import ProtocolError


TIERS = ("control", "luna", "terra")


def _paired_rows(tier):
    static = {"control": 0.25, "luna": 0.25, "terra": 0.50}[tier]
    react = {"control": 0.25, "luna": 0.50, "terra": 1.00}[tier]
    return {
        dataset: {
            "static": [{"native_scores": {"exact_match": static}}] * 2,
            "react": [{"native_scores": {"exact_match": react}}] * 2,
        }
        for dataset in analysis.DATASETS
    }


def test_three_tier_delta_interactions_are_stratified_and_preregistered(monkeypatch):
    monkeypatch.setattr(analysis, "TIERS", TIERS)
    monkeypatch.setattr(
        analysis,
        "_paired_rows",
        lambda protocol, manifest, root, tier: _paired_rows(tier),
    )
    protocol = {
        "analysis": {
            "bootstrap_resamples": 10_000,
            "bootstrap_seed": 20260801,
            "dataset_quality_metrics": {
                dataset: "native_scores.exact_match"
                for dataset in analysis.DATASETS
            },
        }
    }

    result = analysis.compare_tiers(
        protocol,
        {},
        {tier: Path(f"/{tier}") for tier in TIERS},
    )

    interactions = result["react_minus_static_delta_interactions"]
    assert set(interactions) == {
        "luna_minus_control",
        "terra_minus_control",
        "terra_minus_luna",
    }
    assert interactions["luna_minus_control"]["estimate"] == pytest.approx(0.25)
    assert interactions["terra_minus_control"]["estimate"] == pytest.approx(0.50)
    assert interactions["terra_minus_luna"]["estimate"] == pytest.approx(0.25)
    assert all(row["n_resamples"] == 10_000 for row in interactions.values())
    assert all(row["n_pairs"] == 6 for row in interactions.values())
    assert result["interaction_method"] == "dataset-stratified paired percentile bootstrap"


def test_all_and_only_frozen_tier_roots_are_required(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis, "TIERS", TIERS)
    roots = {tier: tmp_path / tier for tier in TIERS}
    assert list(analysis._validate_roots(roots)) == list(TIERS)

    with pytest.raises(ProtocolError, match=r"missing=\['terra'\]"):
        analysis._validate_roots({"control": roots["control"], "luna": roots["luna"]})
    with pytest.raises(ProtocolError, match=r"unexpected=\['pilot'\]"):
        analysis._validate_roots({**roots, "pilot": tmp_path / "pilot"})


def test_cli_exposes_one_required_root_per_frozen_tier(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis, "TIERS", TIERS)
    parser = analysis.build_parser()
    args = parser.parse_args([
        "--control-root", str(tmp_path / "control"),
        "--luna-root", str(tmp_path / "luna"),
        "--terra-root", str(tmp_path / "terra"),
        "--output", str(tmp_path / "result.json"),
        "--memo", str(tmp_path / "memo.md"),
    ])
    assert args.control_root.endswith("control")
    assert args.luna_root.endswith("luna")
    assert args.terra_root.endswith("terra")


def test_analysis_is_blocked_until_all_three_tiers_complete(tmp_path):
    roots = {tier: tmp_path / tier for tier in TIERS}
    for path in roots.values():
        path.mkdir()
    with pytest.raises(ProtocolError, match="completion record"):
        analysis._validate_study_completion({}, roots)
    (tmp_path / "study_complete.json").write_text(json.dumps({
        "status": "complete",
        "process_checks_passed": True,
        "tier_episode_counts": {tier: 300 for tier in TIERS},
    }))
    analysis._validate_study_completion({}, roots)
