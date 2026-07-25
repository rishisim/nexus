import copy
import json
import pytest

from src.agents.finance.protocol_v2 import (
    DATASETS,
    ProtocolError,
    build_manifest,
    fingerprint,
    generate_manifests,
    load_manifest,
    load_protocol,
    stable_json_text,
)


DEV = list(range(50))


def fake_protocol():
    return {
        "schema_version": "finance-protocol-v2",
        "protocol_id": "test_protocol",
        "seed": 20260709,
        "datasets": {
            dataset: {
                "development_indices": DEV,
                "final_count": 100 if dataset == "financebench" else 200,
                "manifest": f"manifests/{dataset}.json",
            }
            for dataset in DATASETS
        },
    }


def fake_rows(dataset):
    size = 150 if dataset == "financebench" else 360
    rows = []
    for idx in range(size):
        row = {
            "answer": str(idx),
            "evidence": [f"evidence {idx}"],
            "question": f"question {idx}",
            "source_id": f"{dataset}-{idx}",
        }
        if dataset == "financebench":
            row["financebench_id"] = f"fb-{idx}"
        elif dataset == "finder":
            row.update(category=f"category-{idx % 4}", question_type=f"type-{idx % 3}")
        elif dataset == "tatqa":
            row.update(question_type=f"type-{idx % 4}", answer_from=f"source-{idx % 3}")
        elif dataset == "convfinqa":
            # Development dialogues 0..9; all rows >= 50 use different dialogues.
            row["dialogue_id"] = idx // 5
        rows.append(row)
    return rows


class FakeEnv:
    def __init__(self, rows):
        self.rows = rows


def test_generation_is_byte_stable_and_has_exact_counts(tmp_path):
    protocol = fake_protocol()
    env_factory = lambda dataset: FakeEnv(fake_rows(dataset))
    generated = generate_manifests(protocol, env_factory, tmp_path)
    first = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    regenerated = generate_manifests(protocol, env_factory, tmp_path)
    second = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    assert first == second
    assert generated == regenerated
    assert set(generated) == set(DATASETS)
    assert sum(item["final"]["count"] for item in generated.values()) == 900
    for dataset, manifest in generated.items():
        expected = 100 if dataset == "financebench" else 200
        assert manifest["development"]["count"] == 50
        assert manifest["final"]["count"] == expected
        assert not set(manifest["development"]["indices"]) & set(manifest["final"]["indices"])


def test_convfinqa_has_dialogue_level_separation():
    manifest = build_manifest(fake_protocol(), "convfinqa", fake_rows("convfinqa"))
    development = {item["dialogue_id"] for item in manifest["development"]["examples"]}
    final = {item["dialogue_id"] for item in manifest["final"]["examples"]}
    assert development.isdisjoint(final)


@pytest.mark.parametrize("dataset, fields", [("finder", 12), ("tatqa", 12)])
def test_stratified_manifests_represent_all_large_strata(dataset, fields):
    manifest = build_manifest(fake_protocol(), dataset, fake_rows(dataset))
    represented = {item["stratum"] for item in manifest["final"]["examples"]}
    assert len(represented) == fields


def test_dataset_fingerprint_detects_row_revision():
    rows = fake_rows("finqa")
    before = build_manifest(fake_protocol(), "finqa", rows)["dataset_fingerprint"]
    changed = copy.deepcopy(rows)
    changed[100]["question"] = "revised question"
    after = build_manifest(fake_protocol(), "finqa", changed)["dataset_fingerprint"]
    assert before != after


def test_committed_protocol_and_manifests_have_900_untouched_final_examples():
    protocol = load_protocol()
    manifests = {dataset: load_manifest(protocol, dataset) for dataset in DATASETS}
    assert sum(manifest["final"]["count"] for manifest in manifests.values()) == 900
    for dataset, manifest in manifests.items():
        assert manifest["development"]["count"] == 50
        assert not set(manifest["development"]["indices"]) & set(manifest["final"]["indices"])
        payload = dict(manifest)
        supplied = payload.pop("manifest_fingerprint")
        assert supplied == fingerprint(payload)
    conv = manifests["convfinqa"]
    dev_dialogues = {item["dialogue_id"] for item in conv["development"]["examples"]}
    final_dialogues = {item["dialogue_id"] for item in conv["final"]["examples"]}
    assert dev_dialogues.isdisjoint(final_dialogues)


def test_manifest_tampering_fails_closed(tmp_path):
    protocol = fake_protocol()
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(stable_json_text(protocol), encoding="utf-8")
    manifest_dir = tmp_path / "manifests"
    generate_manifests(protocol_path, lambda dataset: FakeEnv(fake_rows(dataset)), manifest_dir)
    path = manifest_dir / "financebench.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["final"]["indices"][0] = 49
    path.write_text(stable_json_text(payload), encoding="utf-8")
    with pytest.raises(ProtocolError, match="fingerprint mismatch"):
        load_manifest(load_protocol(protocol_path), "financebench")
