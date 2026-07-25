from dataclasses import dataclass

import pytest

from src.agents.finance.finance_methods import (
    FRAMEWORKS,
    FinanceMethodLLMError,
    build_structured_queries,
    offline_oracle,
    run_cot,
    run_direct,
    run_nexus,
    run_react,
    run_selective,
)
from src.agents.finance.selective_router import SelectiveRouter


@dataclass
class MockLLMResult:
    text: str
    requested_model: str
    resolved_model: str
    backend: str = "mock"
    input_tokens: int = 10
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 4
    total_tokens: int = 14
    latency_ms: float = 2.0
    provider_cost_usd: float = 0.001
    estimated_cost_usd: float = 0.001
    retry_count: int = 0
    status: str = "ok"

    def to_dict(self):
        return self.__dict__.copy()


class MockLLM:
    def __init__(self, outputs, events=None):
        self.outputs = list(outputs)
        self.calls = []
        self.events = events

    def __call__(
        self,
        prompt,
        *,
        stop,
        num_traces,
        max_tokens,
        model_id,
        return_metadata,
    ):
        assert return_metadata is True
        if self.events is not None:
            self.events.append(("llm", model_id))
        self.calls.append(
            {
                "prompt": prompt,
                "stop": stop,
                "num_traces": num_traces,
                "max_tokens": max_tokens,
                "model_id": model_id,
            }
        )
        return MockLLMResult(
            text=self.outputs.pop(0),
            requested_model=model_id,
            resolved_model=model_id,
        )


class MockEnv:
    def __init__(self, question="What was ACME revenue in FY2025?", events=None):
        self.question = question
        self.answer = None
        self.actions = []
        self.events = events
        self.reset_count = 0

    def reset(self, idx=None):
        self.reset_count += 1
        self.answer = None
        if self.events is not None:
            self.events.append(("reset", idx))
        return self.question

    def step(self, action):
        self.actions.append(action)
        if self.events is not None:
            self.events.append(("env", action))
        if action.startswith("Search["):
            observation = (
                "Search results\nTable:\nPeriod | Revenue\nFY2025 | $42 million\n"
                "Internal benchmark secret answer is not present."
            )
            return observation, 0.0, False, {
                "evidence_stats": {
                    "evidence_chunk_count": 2,
                    "evidence_char_count": len(observation),
                    "evidence_token_count": len(observation.split()),
                    "selected_chunk_count": 1,
                    "selected_char_count": len(observation),
                    "selected_token_count": len(observation.split()),
                    "query_token_count": 6,
                    "lexical_coverage": 0.8,
                    "top_score": 4.0,
                    "second_score": 1.0,
                    "score_margin": 3.0,
                    "selected_indices": [0],
                    "chunk_dispersion": 0.5,
                }
            }
        if action.startswith("Lookup["):
            return "FY2025 revenue was $42 million.", 0.0, False, {"evidence_stats": {}}
        if action.startswith("Finish["):
            self.answer = action[len("Finish["):-1]
            reward = float("42" in self.answer)
            return "finished", reward, True, {
                "answer": self.answer,
                "gt_answer": "$42 million",
                "em": reward,
                "native_scores": {"exact": reward},
            }
        raise AssertionError(f"Unexpected action: {action}")


@pytest.mark.parametrize(
    ("runner", "expected_framework", "prompt_fragment"),
    [
        (run_direct, "direct", "Return exactly one line"),
        (run_cot, "cot", "Reason step by step"),
    ],
)
def test_single_search_methods_bind_real_model_and_return_uniform_result(
    runner, expected_framework, prompt_fragment
):
    env = MockEnv()
    model = MockLLM(["Reasoning: evidence extraction\nAnswer: $42 million"])

    reward, result = runner(
        3,
        "google/gemini-2.5-flash",
        env=env,
        llm_func=model,
        evidence_token_budget=12,
    )

    assert reward == 1.0
    assert result["framework"] == expected_framework
    assert result["answer"] == "$42 million"
    assert result["n_calls"] == 1
    assert result["retrieval_calls"] == 1
    assert result["dossier_token_count"] == 12
    assert result["dossier_truncated"] is True
    assert result["requested_model"] == "google/gemini-2.5-flash"
    assert model.calls[0]["model_id"] == "google/gemini-2.5-flash"
    assert prompt_fragment in model.calls[0]["prompt"]
    assert env.actions[0] == "Search[What was ACME revenue in FY2025?]"


def test_static_nexus_uses_deterministic_structured_queries_and_one_generation_call():
    env = MockEnv()
    model = MockLLM(["Reasoning: 42\nAnswer: $42 million"])

    _, result = run_nexus(0, "model/test", env=env, llm_func=model)

    expected_queries = build_structured_queries(env.question)
    assert result["search_queries"] == expected_queries
    assert [action for action in env.actions if action.startswith("Search[")] == [
        f"Search[{query}]" for query in expected_queries
    ]
    assert result["n_calls"] == 1
    assert result["retrieval_calls"] == len(expected_queries)


def test_equal_dossier_budget_applies_to_direct_cot_and_nexus():
    results = []
    for runner in (run_direct, run_cot, run_nexus):
        env = MockEnv()
        model = MockLLM(["Answer: $42 million"])
        _, result = runner(
            0,
            "model/test",
            env=env,
            llm_func=model,
            evidence_token_budget=9,
        )
        results.append(result)
    assert [result["dossier_token_count"] for result in results] == [9, 9, 9]


def test_react_uses_at_most_seven_model_steps_and_shared_actions():
    env = MockEnv()
    model = MockLLM(
        [
            "Thought 1: Find the revenue.\nAction 1: Search[ACME FY2025 revenue]",
            "Thought 2: It is 42.\nAction 2: Finish[$42 million]",
        ]
    )

    reward, result = run_react(0, "model/react", env=env, llm_func=model)

    assert reward == 1.0
    assert result["answer"] == "$42 million"
    assert result["n_calls"] == 2
    assert result["retrieval_calls"] == 1
    assert env.actions == ["Search[ACME FY2025 revenue]", "Finish[$42 million]"]
    assert all(call["model_id"] == "model/react" for call in model.calls)


def test_invalid_react_output_finishes_unknown_without_an_unbudgeted_repair_call():
    env = MockEnv()
    model = MockLLM(["I cannot produce an action."])

    _, result = run_react(0, "model/react", env=env, llm_func=model)

    assert result["n_calls"] == 1
    assert result["n_badcalls"] == 1
    assert result["answer"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("status", "failure_type"),
    [
        ("infrastructure_error", "infrastructure_failure"),
        ("empty_response", "model_failure"),
        ("client_error", "model_failure"),
    ],
)
def test_failed_model_call_raises_typed_error_and_never_submits_an_answer(
    status, failure_type
):
    env = MockEnv()

    def failed_llm(
        prompt,
        *,
        stop,
        num_traces,
        max_tokens,
        model_id,
        return_metadata,
    ):
        result = MockLLMResult(
            text="",
            requested_model=model_id,
            resolved_model=model_id,
            input_tokens=37,
            output_tokens=0,
            total_tokens=37,
            retry_count=2,
            status=status,
        )
        result.error_type = "SyntheticProviderError"
        result.error_message = "synthetic failure"
        return result

    with pytest.raises(FinanceMethodLLMError) as caught:
        run_direct(0, "model/failing", env=env, llm_func=failed_llm)

    error = caught.value
    assert error.failure_type == failure_type
    assert error.status == status
    assert error.metadata["retry_count"] == 2
    assert error.metadata["input_tokens"] == 37
    assert error.metadata["total_tokens"] == 37
    assert error.metadata["requested_model"] == "model/failing"
    assert not any(action.startswith("Finish[") for action in env.actions)


def test_selective_route_is_decided_after_retrieval_but_before_generation():
    events = []
    env = MockEnv(events=events)
    model = MockLLM(["Answer: $42 million"], events=events)
    router = SelectiveRouter(
        mode="rule",
        threshold=None,
        coverage_median=0.5,
        margin_q25=0.25,
    )

    _, result = run_selective(
        0,
        "model/selective",
        env=env,
        llm_func=model,
        router=router,
    )

    initial_search_position = events.index(("env", f"Search[{env.question}]"))
    model_position = events.index(("llm", "model/selective"))
    assert initial_search_position < model_position
    assert result["framework"] == "selective"
    assert result["selected_framework"] == "nexus"
    assert result["router_features"]["lexical_coverage"] == 0.8
    # The pre-routing Search[question] is reused rather than duplicated.
    assert env.actions.count(f"Search[{env.question}]") == 1


def test_selective_narrative_rule_routes_to_clean_react_episode():
    events = []
    env = MockEnv(question="What is the strategic impact of ACME revenue?", events=events)
    model = MockLLM(["Thought 1: Answer.\nAction 1: Finish[$42 million]"], events=events)
    router = SelectiveRouter(
        mode="rule",
        threshold=None,
        coverage_median=0.0,
        margin_q25=-1.0,
    )

    _, result = run_selective(
        0, "model/selective", env=env, llm_func=model, router=router
    )

    assert result["selected_framework"] == "react"
    assert "narrative_or_implication_question" in result["router_reasons"]
    assert env.reset_count == 2
    assert result["router_retrieval_calls"] == 1


def test_offline_oracle_selects_correct_result_and_is_not_deployable_framework():
    static = {"answer": "wrong", "reward": 0.0, "n_calls": 1}
    react = {"answer": "42", "reward": 1.0, "n_calls": 4}

    result = offline_oracle(static, react)

    assert result["selected_framework"] == "react"
    assert result["oracle_only"] is True
    assert "oracle" not in FRAMEWORKS
