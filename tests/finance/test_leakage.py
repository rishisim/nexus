import json

import pytest

from src.agents.finance import finance_env


GOLD_ANSWER = "GOLD_ANSWER_SENTINEL"
GOLD_DERIVATION = "GOLD_DERIVATION_SENTINEL"
GOLD_SCALE = "GOLD_SCALE_SENTINEL"
TARGET_TYPE = "TARGET_TYPE_SENTINEL"
TARGET_SOURCE = "TARGET_SOURCE_SENTINEL"
RATIONALE = "RATIONALE_SENTINEL"


def _assert_no_gold_fields(info):
    assert "gt_answer" not in info
    assert "gold_scale" not in info
    assert "scale" not in info
    assert "question_type" not in info
    assert "answer_from" not in info


def test_financebench_excludes_justification_and_target_metadata(tmp_path):
    rows = [
        {
            "financebench_id": "financebench_id_test",
            "question": "What was source revenue?",
            "answer": GOLD_ANSWER,
            "justification": RATIONALE,
            "company": "Example Corp",
            "doc_name": "example_2025_10k",
            "doc_type": "10k",
            "doc_period": 2025,
            "doc_link": "https://example.test/filing.pdf",
            "question_type": TARGET_TYPE,
            "question_reasoning": GOLD_DERIVATION,
            "evidence": [
                {
                    "evidence_text": "Source revenue was 40 in 2025.",
                    "doc_name": "example_2025_10k",
                    "evidence_page_num": 12,
                    "answer": GOLD_ANSWER,
                }
            ],
        }
    ]
    data_path = tmp_path / "financebench.json"
    data_path.write_text(json.dumps(rows), encoding="utf-8")

    env = finance_env.FinanceBenchEnv(data_path=str(data_path))
    env.reset(0)

    assert "justification" not in env.current_row
    observation, _, done, info = env.step("Search[source revenue]")
    assert done is False
    assert "Source revenue was 40" in observation
    assert "example_2025_10k" in observation
    assert "page: 12" in observation
    for forbidden in (GOLD_ANSWER, RATIONALE, TARGET_TYPE, GOLD_DERIVATION):
        assert forbidden not in observation
    _assert_no_gold_fields(info)
    assert info["source_id"] == "financebench_id_test"
    assert info["doc_link"] == "https://example.test/filing.pdf"

    _, _, done, final_info = env.step("Finish[model prediction]")
    assert done is True
    assert final_info["gt_answer"] == GOLD_ANSWER
    assert final_info["question_type"] == TARGET_TYPE


def test_tatqa_never_renders_derivation_scale_or_target_labels(monkeypatch):
    raw_rows = [
        {
            "table": {
                "uid": "table-source-id",
                "table": [["Metric", "2025"], ["Revenue", "40"]],
                "answer": GOLD_ANSWER,
                "derivation": GOLD_DERIVATION,
            },
            "paragraphs": [
                {"uid": "paragraph-source-id", "order": 1, "text": "Revenue rose in 2025."},
                {"answer": GOLD_ANSWER, "derivation": GOLD_DERIVATION},
            ],
            "questions": [
                {
                    "uid": "tatqa-question-id",
                    "order": 1,
                    "question": "What was revenue?",
                    "answer": [GOLD_ANSWER],
                    "derivation": GOLD_DERIVATION,
                    "answer_type": TARGET_TYPE,
                    "answer_from": TARGET_SOURCE,
                    "scale": GOLD_SCALE,
                }
            ],
        }
    ]
    monkeypatch.setattr(finance_env, "_load_hf_rows", lambda *_: raw_rows)

    env = finance_env.EvidencePacketEnv("tatqa", split="validation")
    env.reset(0)

    assert "derivation" not in env.current_row
    assert env.current_row["gold_scale"] == GOLD_SCALE
    observation, _, _, info = env.step("Search[revenue]")
    for forbidden in (GOLD_ANSWER, GOLD_DERIVATION, GOLD_SCALE, TARGET_TYPE, TARGET_SOURCE):
        assert forbidden not in observation
    assert "tatqa-question-id" in observation
    assert "Revenue | 40" in observation
    _assert_no_gold_fields(info)

    lookup, _, _, lookup_info = env.step("Lookup[Revenue]")
    for forbidden in (GOLD_ANSWER, GOLD_DERIVATION, GOLD_SCALE, TARGET_TYPE, TARGET_SOURCE):
        assert forbidden not in lookup
    _assert_no_gold_fields(lookup_info)

    _, _, done, final_info = env.step("Finish[model prediction]")
    assert done is True
    assert final_info["gt_answer"] == GOLD_ANSWER
    assert final_info["gold_scale"] == GOLD_SCALE
    assert final_info["scale"] == GOLD_SCALE
    assert final_info["question_type"] == TARGET_TYPE
    assert final_info["answer_from"] == TARGET_SOURCE


def test_finder_serializes_only_reference_text_and_safe_source_id(monkeypatch):
    raw_rows = [
        {
            "_id": "finder-source-id",
            "text": "How did revenue change?",
            "answer": GOLD_ANSWER,
            "reasoning": RATIONALE,
            "category": "TARGET_CATEGORY_SENTINEL",
            "type": TARGET_TYPE,
            "references": [
                "Revenue increased from 30 to 40.",
                {
                    "content": "Operating income was stable.",
                    "answer": GOLD_ANSWER,
                    "reasoning": RATIONALE,
                },
            ],
        }
    ]
    monkeypatch.setattr(finance_env, "_load_hf_rows", lambda *_: raw_rows)

    env = finance_env.EvidencePacketEnv("finder", split="train")
    env.reset(0)

    assert "reasoning" not in env.current_row
    observation, _, _, info = env.step("Search[revenue operating income]")
    assert "Revenue increased from 30 to 40" in observation
    assert "Operating income was stable" in observation
    for forbidden in (GOLD_ANSWER, RATIONALE, TARGET_TYPE, "TARGET_CATEGORY_SENTINEL"):
        assert forbidden not in observation
    _assert_no_gold_fields(info)
    assert info["source_id"] == "finder-source-id"


def test_convfinqa_preserves_dialogue_id_without_exposing_labels(monkeypatch):
    query = (
        "Context: Filing revenue was 40.\n"
        "Conversations:\n"
        "Question: What was the prior value?\n"
        "Answer: 30\n"
        "Question: What was the change?\n"
        "Answer:"
    )
    raw_rows = [
        {
            "id": "convfinqa-source-id",
            "query": query,
            "answer": GOLD_ANSWER,
            "turn": "1",
            "dialogue_id": "dialogue-17",
        }
    ]
    monkeypatch.setattr(finance_env, "_load_hf_rows", lambda *_: raw_rows)

    env = finance_env.EvidencePacketEnv("convfinqa", split="valid")
    assert env.reset(0) == "What was the change?"
    observation, _, _, info = env.step("Search[revenue prior value]")

    assert "Filing revenue was 40" in observation
    assert "What was the prior value?" in observation
    assert GOLD_ANSWER not in observation
    assert info["dialogue_id"] == "dialogue-17"
    assert info["turn"] == "1"
    _assert_no_gold_fields(info)


def test_search_statistics_are_deterministic_non_gold_and_defensively_copied(monkeypatch):
    raw_rows = [
        {
            "id": "finqa-source-id",
            "query": "Context: Alpha revenue was 40. Beta expense was 20.\nQuestion: Revenue?\nAnswer:",
            "text": "Revenue?",
            "answer": GOLD_ANSWER,
        }
    ]
    monkeypatch.setattr(finance_env, "_load_hf_rows", lambda *_: raw_rows)
    env = finance_env.EvidencePacketEnv("finqa", split="valid")
    env.reset(0)

    _, _, _, first_info = env.step("Search[alpha revenue]")
    first = first_info["evidence_stats"]
    _, _, _, second_info = env.step("Search[alpha revenue]")
    second = second_info["evidence_stats"]

    assert first == second
    assert first["evidence_chunk_count"] == 2
    assert first["selected_chunk_count"] == 2
    assert first["query_token_count"] == 2
    assert first["lexical_coverage"] == 1.0
    assert first["top_score"] >= first["second_score"]
    assert first["score_margin"] == first["top_score"] - first["second_score"]
    assert 0.0 <= first["chunk_dispersion"] <= 1.0
    assert GOLD_ANSWER not in json.dumps(first)

    first["selected_indices"].append(999)
    assert 999 not in env.get_evidence_stats()["selected_indices"]


@pytest.mark.parametrize("dataset_id", ["finqa", "tatqa", "convfinqa", "finder"])
def test_unsupported_gold_fields_are_never_in_unfinished_info(dataset_id):
    """Document the runtime contract independently of dataset normalization."""
    env = object.__new__(finance_env.EvidencePacketEnv)
    env.dataset_id = dataset_id
    env.current_idx = 0
    env.current_row = {
        "question": "Question",
        "answer": GOLD_ANSWER,
        "source_id": "source",
        "question_type": TARGET_TYPE,
        "answer_from": TARGET_SOURCE,
        "gold_scale": GOLD_SCALE,
    }
    env.answer = None
    env.evidence_stats = finance_env._unsearched_evidence_stats([])

    _assert_no_gold_fields(env._get_info())
