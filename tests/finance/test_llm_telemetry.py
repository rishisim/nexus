import unittest
import inspect
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.shared import llm as llm_module
from src.shared.llm_telemetry import (
    LLMResult,
    PRICE_SNAPSHOT_DATE,
    TokenUsage,
    estimate_cost_usd,
    parse_gemini_usage,
    parse_openrouter_usage,
)


class OpenRouterBodyTests(unittest.TestCase):
    def test_gemini_flash_uses_deterministic_non_reasoning_request(self):
        body = llm_module._build_openrouter_body(
            "question", ["\n"], 0.7, 256, "google/gemini-2.5-flash"
        )

        self.assertEqual(body["model"], "google/gemini-2.5-flash")
        self.assertEqual(body["temperature"], 0.0)
        self.assertEqual(body["top_p"], 1.0)
        self.assertEqual(body["reasoning"], {"max_tokens": 0})

    def test_luna_omits_sampling_parameters_and_disables_reasoning(self):
        body = llm_module._build_openrouter_body(
            "question", [], 0.7, 256, "openai/gpt-5.6-luna"
        )

        self.assertEqual(body["reasoning_effort"], "none")
        self.assertNotIn("temperature", body)
        self.assertNotIn("top_p", body)

    def test_exact_gpt_4o_mini_binds_openai_provider_without_fallbacks(self):
        stop = ["\nObservation 1:", "Finish["]
        body = llm_module._build_openrouter_body(
            "question", stop, 0.0, 256, "openai/gpt-4o-mini-2024-07-18"
        )

        self.assertEqual(body["model"], "openai/gpt-4o-mini-2024-07-18")
        self.assertEqual(body["temperature"], 0.0)
        self.assertEqual(body["stop"], stop)
        self.assertEqual(
            body["provider"],
            {
                "only": ["OpenAI"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
            },
        )


class UsageParsingTests(unittest.TestCase):
    def test_openrouter_usage_is_defensive_and_preserves_provider_totals(self):
        usage = parse_openrouter_usage(
            {
                "usage": {
                    "prompt_tokens": "100",
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_tokens_details": {"cached_tokens": 10},
                    "completion_tokens_details": {"reasoning_tokens": 5},
                    "cost": "0.0012",
                }
            }
        )

        self.assertEqual(usage.input_tokens, 100)
        self.assertEqual(usage.cached_tokens, 10)
        self.assertEqual(usage.reasoning_tokens, 5)
        self.assertEqual(usage.output_tokens, 20)
        self.assertEqual(usage.total_tokens, 120)
        self.assertEqual(usage.provider_cost_usd, 0.0012)

    def test_missing_total_does_not_double_count_reasoning(self):
        usage = parse_openrouter_usage(
            {
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "completion_tokens_details": {"reasoning_tokens": 5},
                }
            }
        )

        self.assertEqual(usage.output_tokens, 20)
        self.assertEqual(usage.reasoning_tokens, 5)
        self.assertEqual(usage.total_tokens, 120)

    def test_missing_or_malformed_usage_becomes_zero_not_exception(self):
        usage = parse_openrouter_usage(
            {"usage": {"prompt_tokens": "bad", "completion_tokens": None}}
        )

        self.assertEqual(usage, TokenUsage())

    def test_gemini_usage_supports_sdk_objects(self):
        response = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=50,
                cached_content_token_count=7,
                thoughts_token_count=3,
                candidates_token_count=10,
                total_token_count=63,
            )
        )

        usage = parse_gemini_usage(response)

        self.assertEqual(usage.input_tokens, 50)
        self.assertEqual(usage.cached_tokens, 7)
        self.assertEqual(usage.reasoning_tokens, 3)
        self.assertEqual(usage.output_tokens, 13)
        self.assertEqual(usage.total_tokens, 63)

    def test_frozen_price_estimate_accounts_for_cache_and_reasoning(self):
        self.assertEqual(PRICE_SNAPSHOT_DATE, "2026-07-09")
        usage = TokenUsage(
            input_tokens=100,
            cached_tokens=10,
            output_tokens=20,
            reasoning_tokens=5,
        )

        estimate = estimate_cost_usd("google/gemini-2.5-flash", usage)

        self.assertAlmostEqual(estimate, 0.0000773)
        self.assertIsNone(estimate_cost_usd("unknown/model", usage))


class LLMContractTests(unittest.TestCase):
    def setUp(self):
        self.response_data = {
            "model": "google/gemini-2.5-flash",
            "choices": [{"message": {"content": "  answer  "}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 10},
                "completion_tokens_details": {"reasoning_tokens": 5},
                "cost": 0.0012,
            },
        }

    def test_default_attempt_limit_matches_frozen_protocol(self):
        parameter = inspect.signature(llm_module.llm_with_metadata).parameters[
            "max_retries"
        ]

        self.assertEqual(llm_module.DEFAULT_MAX_ATTEMPTS, 5)
        self.assertEqual(parameter.default, 5)

    @patch.object(llm_module, "LLM_DELAY", 0)
    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-placeholder"})
    @patch.object(llm_module.req, "post")
    def test_explicit_model_reaches_request_and_metadata_is_returned(self, post):
        response = Mock()
        response.json.return_value = self.response_data
        response.raise_for_status.return_value = None
        post.return_value = response

        result = llm_module.llm(
            "question",
            stop=[],
            model_id="google/gemini-2.5-flash",
            return_metadata=True,
        )

        self.assertIsInstance(result, LLMResult)
        self.assertEqual(result.text, "answer")
        self.assertEqual(result.requested_model, "google/gemini-2.5-flash")
        self.assertEqual(result.resolved_model, "google/gemini-2.5-flash")
        self.assertEqual(result.backend, "openrouter")
        self.assertEqual(result.output_tokens, 20)
        self.assertEqual(result.reasoning_tokens, 5)
        self.assertEqual(result.provider_cost_usd, 0.0012)
        self.assertEqual(result.effective_cost_usd, 0.0012)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.retry_count, 0)
        request_body = post.call_args.kwargs["json"]
        self.assertEqual(request_body["model"], "google/gemini-2.5-flash")

    @patch.object(llm_module, "LLM_DELAY", 0)
    @patch.object(llm_module, "_call_openrouter")
    def test_legacy_call_still_returns_string(self, call):
        call.return_value = self.response_data

        result = llm_module.llm("question", stop=[])

        self.assertEqual(result, "answer")
        self.assertIsInstance(result, str)

    @patch.object(llm_module, "LLM_DELAY", 0)
    @patch.object(llm_module.random, "uniform", return_value=0.0)
    @patch.object(llm_module.time, "sleep")
    @patch.object(llm_module, "_call_openrouter")
    def test_retry_count_tracks_infrastructure_failure_before_success(
        self, call, sleep, uniform
    ):
        call.side_effect = [
            llm_module.req.Timeout("timed out"),
            self.response_data,
        ]

        result = llm_module.llm_with_metadata("question", stop=[])

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch.object(llm_module, "LLM_DELAY", 0)
    @patch.object(llm_module.time, "sleep")
    @patch.object(llm_module, "_call_openrouter", side_effect=RuntimeError("network"))
    def test_generic_model_failure_is_not_retried(self, call, sleep):
        result = llm_module.llm_with_metadata(
            "question", stop=[], max_retries=2
        )

        self.assertEqual(result.status, "model_error")
        self.assertEqual(result.error_type, "RuntimeError")
        self.assertEqual(result.text, "")
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(call.call_count, 1)
        sleep.assert_not_called()

    @patch.object(llm_module, "LLM_DELAY", 0)
    @patch.object(llm_module.time, "sleep")
    @patch.object(llm_module, "_call_openrouter")
    def test_empty_response_is_model_failure_and_is_not_retried(self, call, sleep):
        call.return_value = {"choices": [], "usage": {"prompt_tokens": 10}}

        result = llm_module.llm_with_metadata(
            "question", stop=[], max_retries=3
        )

        self.assertEqual(result.status, "empty_response")
        self.assertEqual(result.error_type, "empty_response")
        self.assertEqual(result.input_tokens, 10)
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(call.call_count, 1)
        sleep.assert_not_called()

    @patch.object(llm_module, "LLM_DELAY", 0)
    @patch.object(llm_module.time, "sleep")
    @patch.object(llm_module, "_call_openrouter")
    def test_auth_error_is_client_failure_and_is_not_retried(self, call, sleep):
        error = llm_module.req.HTTPError("unauthorized")
        error.response = SimpleNamespace(status_code=401)
        call.side_effect = error

        result = llm_module.llm_with_metadata(
            "question", stop=[], max_retries=3
        )

        self.assertEqual(result.status, "client_error")
        self.assertEqual(result.error_type, "HTTPError")
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(call.call_count, 1)
        sleep.assert_not_called()

    @patch.object(llm_module, "LLM_DELAY", 0)
    @patch.object(llm_module.random, "uniform", return_value=0.0)
    @patch.object(llm_module.time, "sleep")
    @patch.object(llm_module, "_call_openrouter")
    def test_retryable_http_error_exhaustion_is_infrastructure_failure(
        self, call, sleep, uniform
    ):
        error = llm_module.req.HTTPError("rate limited")
        error.response = SimpleNamespace(status_code=429)
        call.side_effect = error

        result = llm_module.llm_with_metadata(
            "question", stop=[], max_retries=3
        )

        self.assertEqual(result.status, "infrastructure_error")
        self.assertEqual(result.error_type, "HTTPError")
        self.assertEqual(result.retry_count, 2)
        self.assertEqual(call.call_count, 3)
        self.assertEqual([entry.args[0] for entry in sleep.call_args_list], [1, 2])

    @patch.object(llm_module.req, "get")
    def test_model_catalog_snapshot_reports_missing_slugs(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [
                {
                    "id": "google/gemini-2.5-flash",
                    "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
                }
            ]
        }
        get.return_value = response

        snapshot = llm_module.fetch_openrouter_model_snapshot(
            ["missing/model", "google/gemini-2.5-flash"]
        )

        self.assertEqual(
            snapshot["requested_model_ids"],
            ["google/gemini-2.5-flash", "missing/model"],
        )
        self.assertEqual(snapshot["missing_model_ids"], ["missing/model"])
        self.assertIn("google/gemini-2.5-flash", snapshot["models"])
        get.assert_called_once_with(llm_module._OPENROUTER_MODELS_URL, timeout=30.0)


if __name__ == "__main__":
    unittest.main()
