import json

import pytest

from src.agents.finance.analyze_realm26_capability_audit import (
    _validate_complete_run,
    clopper_pearson_interval,
    continuous_oracle_headroom,
)
from src.agents.finance.protocol_v2 import ProtocolError


def test_clopper_pearson_matches_small_headroom_cells():
    one = clopper_pearson_interval(1, 150)
    two = clopper_pearson_interval(2, 150)
    assert one["estimate"] == pytest.approx(1 / 150)
    assert one["lower"] == pytest.approx(0.0001687711431)
    assert one["upper"] == pytest.approx(0.0365831677406)
    assert two["estimate"] == pytest.approx(2 / 150)
    assert two["lower"] == pytest.approx(0.00161882702984)
    assert two["upper"] == pytest.approx(0.0473330194963)


def test_continuous_oracle_uses_native_per_item_max_and_dataset_macro():
    static = {dataset: [1.0, 0.0] for dataset in ("finqa", "tatqa", "convfinqa")}
    react = {dataset: [0.0, 1.0] for dataset in ("finqa", "tatqa", "convfinqa")}
    result = continuous_oracle_headroom(static, react, n_resamples=100, seed=17)
    assert result["static_macro_quality"] == 0.5
    assert result["react_macro_quality"] == 0.5
    assert result["oracle_macro_quality"] == 1.0
    assert result["estimate"] == 0.5


def test_audit_is_blocked_before_complete_process_record(tmp_path):
    with pytest.raises(ProtocolError, match="blocked until the run completes"):
        _validate_complete_run(tmp_path, "protocol", 1)


def test_complete_record_still_requires_every_row(tmp_path):
    (tmp_path / "study_complete.json").write_text(json.dumps({
        "status": "complete",
        "process_checks_passed": True,
        "tier_episode_counts": {"control": 300, "luna": 300, "terra": 300},
    }))
    (tmp_path / "config.json").write_text(json.dumps({"protocol_id": "protocol"}))
    with pytest.raises(FileNotFoundError):
        _validate_complete_run(tmp_path, "protocol", 1)
