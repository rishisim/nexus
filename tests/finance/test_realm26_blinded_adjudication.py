import copy
import csv
import json
from pathlib import Path

import pytest

from scripts.realm26_blinded_adjudication import (
    FORBIDDEN_REVIEWER_TERMS,
    LABEL_FIELDS,
    METHOD_REVEALING_FIELDS,
    build_packet,
    load_or_create_private_seed,
    load_task_contexts,
    write_outputs,
)


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "paper/realm2026/artifacts/fairness_audit.json"
TEST_SEED = "test-only-private-seed-0123456789abcdef"


@pytest.fixture(scope="module")
def audit():
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contexts_and_source(audit):
    return load_task_contexts(audit, ROOT)


def test_questions_come_from_hash_verified_development_outputs(audit, contexts_and_source):
    contexts, source = contexts_and_source
    assert len(contexts) == 51
    assert len(source["verified_source_files"]) == 8
    assert "development" in source["development_run"]
    assert all(value["question"] for value in contexts.values())
    conv = {key: value for key, value in contexts.items() if key.startswith("convfinqa:")}
    assert len(conv) == 12
    assert all(value["conversation_context"] for value in conv.values())
    assert all(
        not value["conversation_context"]
        for key, value in contexts.items()
        if not key.startswith("convfinqa:")
    )


def test_packet_is_exactly_frozen_queue_and_is_deterministic(audit, contexts_and_source):
    contexts, _ = contexts_and_source
    rows_a, key_a = build_packet(audit, contexts, TEST_SEED)
    rows_b, key_b = build_packet(audit, contexts, TEST_SEED)
    assert len(rows_a) == 51
    assert rows_a == rows_b
    assert key_a == key_b
    assert set(key_a["items"]) == {row["case_id"] for row in rows_a}
    assert all(row["question"] for row in rows_a)
    assert all(row[field] == "" for row in rows_a for field in LABEL_FIELDS)


def test_private_forms_hide_seed_identity_and_method_telemetry(
    tmp_path, audit, contexts_and_source
):
    contexts, source = contexts_and_source
    rows, key = build_packet(audit, contexts, TEST_SEED)
    outputs = write_outputs(
        rows,
        key,
        tmp_path / "private" / "reviewer_packets",
        tmp_path / "packet_manifest.json",
        tmp_path / "private" / "key" / "ab_key.json",
        source,
        ROOT / "paper/realm2026/adjudication/rubric.md",
    )
    reviewer_text = "\n".join(
        outputs[name].read_text(encoding="utf-8")
        for name in ("reviewer_1", "reviewer_2", "guide")
    )
    manifest_text = outputs["manifest"].read_text(encoding="utf-8")
    assert TEST_SEED not in reviewer_text
    assert TEST_SEED not in manifest_text
    assert not FORBIDDEN_REVIEWER_TERMS.search(reviewer_text)
    assert "question" in reviewer_text
    assert "prior_dialogue" in reviewer_text
    assert "static_nexus" not in reviewer_text.lower()
    assert "react" not in reviewer_text.lower()

    with outputs["reviewer_1"].open(newline="", encoding="utf-8") as handle:
        reviewer_1 = list(csv.DictReader(handle))
    with outputs["reviewer_2"].open(newline="", encoding="utf-8") as handle:
        reviewer_2 = list(csv.DictReader(handle))
    assert len(reviewer_1) == len(reviewer_2) == 51
    assert not set(METHOD_REVEALING_FIELDS) & set(reviewer_1[0])
    assert not set(METHOD_REVEALING_FIELDS) & set(reviewer_2[0])
    assert {row["reviewer_form"] for row in reviewer_1} == {"reviewer_1"}
    assert {row["reviewer_form"] for row in reviewer_2} == {"reviewer_2"}
    for left, right in zip(reviewer_1, reviewer_2):
        assert {k: v for k, v in left.items() if k != "reviewer_form"} == {
            k: v for k, v in right.items() if k != "reviewer_form"
        }
        assert all(left[field] == right[field] == "" for field in LABEL_FIELDS)

    manifest = json.loads(manifest_text)
    assert manifest["scope"] == {
        "case_count": 51,
        "external_provider_calls": 0,
        "human_labels_prefilled": False,
        "partition": "development_only",
        "sealed_final_partition_accessed": False,
    }
    assert manifest["assignment_commitment"] == key["assignment_commitment"]
    assert manifest["rubric_sha256"].startswith("sha256:")


def test_private_seed_requires_explicit_initialization_and_can_rotate(tmp_path):
    key_path = tmp_path / "private" / "key.json"
    with pytest.raises(FileNotFoundError):
        load_or_create_private_seed(key_path)
    first = load_or_create_private_seed(key_path, initialize=True)
    key_path.parent.mkdir(parents=True)
    key_path.write_text(json.dumps({"seed": first}), encoding="utf-8")
    assert load_or_create_private_seed(key_path) == first
    assert load_or_create_private_seed(key_path, rotate=True) != first


def test_development_input_hash_mismatch_is_rejected(audit):
    changed = copy.deepcopy(audit)
    path = next(
        key
        for key in changed["provenance"]["input_sha256"]
        if key.endswith("/nexus/results.json")
    )
    changed["provenance"]["input_sha256"][path] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        load_task_contexts(changed, ROOT)


def test_non_development_run_is_rejected(audit):
    changed = copy.deepcopy(audit)
    changed["provenance"]["development_run"] = "sealed-final"
    with pytest.raises(ValueError, match="development-only"):
        load_task_contexts(changed, ROOT)


@pytest.mark.parametrize("name", ["final", "sealed-final", "results", "outcomes", "traces"])
def test_partition_or_result_like_output_paths_are_refused(
    tmp_path, name, audit, contexts_and_source
):
    contexts, source = contexts_and_source
    rows, key = build_packet(audit, contexts, TEST_SEED)
    with pytest.raises(ValueError):
        write_outputs(
            rows,
            key,
            tmp_path / name / "reviewer_packets",
            tmp_path / "packet_manifest.json",
            tmp_path / "private" / "key.json",
            source,
            ROOT / "paper/realm2026/adjudication/rubric.md",
        )
