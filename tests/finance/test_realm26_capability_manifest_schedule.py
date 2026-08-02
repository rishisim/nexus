import copy
import itertools
from collections import Counter

import pytest

from src.agents.finance.protocol_v2 import ProtocolError, fingerprint
from src.agents.finance.realm26_capability_protocol import (
    DATASETS,
    FRAMEWORKS,
    TIERS,
    build_execution_schedule,
    build_manifest,
    validate_execution_schedule,
)


def _datasets():
    return {
        dataset: {
            "examples": [
                {"example_id": f"{dataset}-{index}", "index": index}
                for index in range(50)
            ]
        }
        for dataset in DATASETS
    }


def test_schedule_is_deterministic_complete_and_exactly_counterbalanced():
    datasets = _datasets()
    first = build_execution_schedule(datasets, 2026080201)
    second = build_execution_schedule(datasets, 2026080201)
    assert first == second
    validate_execution_schedule(first, datasets, 2026080201)

    permutations = Counter(tuple(item["model_order"]) for item in first["items"])
    assert permutations == Counter({order: 25 for order in itertools.permutations(TIERS)})
    framework_first = Counter(
        (tier, item["framework_order_by_tier"][tier][0])
        for item in first["items"]
        for tier in TIERS
    )
    assert framework_first == Counter({(tier, framework): 75 for tier in TIERS for framework in FRAMEWORKS})
    assert len({(item["dataset_id"], item["example_id"]) for item in first["items"]}) == 150


def test_schedule_validator_rejects_post_freeze_drift():
    datasets = _datasets()
    schedule = build_execution_schedule(datasets, 2026080201)
    drifted = copy.deepcopy(schedule)
    drifted["items"][0]["framework_order_by_tier"]["control"].reverse()
    with pytest.raises(ProtocolError, match="balanced|reproduce"):
        validate_execution_schedule(drifted, datasets, 2026080201)


class GuardedRows:
    def __init__(self, dataset, excluded):
        self.dataset = dataset
        self.excluded = set(excluded)

    def __len__(self):
        return 300

    def __getitem__(self, index):
        if index in self.excluded:
            raise AssertionError("excluded row content was dereferenced")
        row = {
            "answer": str(index),
            "evidence": [f"evidence-{index}"],
            "question": f"question-{index}",
            "source_id": f"{self.dataset}-{index}",
        }
        if self.dataset == "tatqa":
            row.update({"answer_from": "table", "question_type": "arithmetic"})
        if self.dataset == "convfinqa":
            row["dialogue_id"] = f"dialogue-{index}"
        return row


def test_fresh_manifest_never_dereferences_excluded_rows(monkeypatch):
    excluded_indices = set(range(20))
    exclusions = {
        "counts": {"failed_freeze_attempted": 17, "total": len(excluded_indices)},
        "dialogue_hashes": {fingerprint(f"dialogue-{index}") for index in excluded_indices},
        "example_ids": {f"reserved-{index}" for index in excluded_indices},
        "fingerprint": "sha256:test-exclusions",
        "indices": excluded_indices,
    }
    monkeypatch.setattr(
        "src.agents.finance.realm26_capability_protocol._identifier_exclusions",
        lambda protocol, dataset: exclusions,
    )
    monkeypatch.setattr(
        "src.agents.finance.realm26_capability_protocol.validate_protocol",
        lambda protocol: None,
    )

    protocol = {
        "sample": {"per_dataset": 50, "schedule_seed": 2026080201},
        "seed": 20260802,
    }

    def factory(dataset):
        return type("Env", (), {"rows": GuardedRows(dataset, excluded_indices)})()

    manifest = build_manifest(protocol, factory)
    assert all(
        int(item["index"]) not in excluded_indices
        for spec in manifest["datasets"].values()
        for item in spec["examples"]
    )
    validate_execution_schedule(
        manifest["execution_schedule"], manifest["datasets"], protocol["sample"]["schedule_seed"]
    )
