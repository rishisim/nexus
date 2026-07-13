import unittest

from src.agents.finance.finance_scoring import (
    SEMANTIC_JUDGE_REQUEST_SCHEMA,
    SemanticJudgeResponse,
    build_semantic_judge_request,
    infer_predicted_scale,
    parse_numeric_answer,
    render_semantic_judge_prompt,
    score_convfinqa,
    score_dataset,
    score_financebench,
    score_finqa,
    score_tatqa,
)


class ExecutionScoringTests(unittest.TestCase):
    def test_sign_is_never_ignored(self):
        self.assertTrue(score_finqa("Final answer: -42", "-42").correct)
        self.assertFalse(score_finqa("42", "-42").correct)
        self.assertFalse(score_convfinqa("($42)", "42").correct)

    def test_percent_decimal_equivalence_is_directional_and_precise(self):
        self.assertTrue(score_finqa("4.74%", "0.0474").correct)
        self.assertTrue(score_convfinqa("0.0474", "4.74%").correct)
        self.assertFalse(score_finqa("47.4%", "0.0474").correct)

    def test_fraction_and_ratio(self):
        parsed = parse_numeric_answer("1/4")
        self.assertIsNotNone(parsed)
        self.assertEqual(str(parsed.value), "0.25")
        self.assertTrue(score_finqa("1/4", "0.25").correct)

    def test_ambiguous_derivation_does_not_match_any_mentioned_number(self):
        result = score_finqa("100 - 60 = 40", "40")
        self.assertFalse(result.correct)
        self.assertIsNone(parse_numeric_answer("100 - 60 = 40"))
        self.assertTrue(score_finqa("100 - 60 = 40. Final answer: 40", "40").correct)

    def test_five_decimal_execution_convention(self):
        self.assertTrue(score_finqa("0.333334", "0.33333").correct)
        self.assertFalse(score_finqa("0.33335", "0.33333").correct)

    def test_text_requires_exact_normalized_answer(self):
        self.assertTrue(score_finqa("Yes, because the ratio increased.", "yes").correct)
        self.assertFalse(score_finqa("no", "yes").correct)
        self.assertTrue(score_finqa("YUM! Brands", "YUM Brands").correct)


class TatQAScoringTests(unittest.TestCase):
    def test_scale_is_inferred_only_from_prediction(self):
        self.assertEqual(infer_predicted_scale("$1.2 million"), "million")
        self.assertEqual(infer_predicted_scale("12.5%"), "percent")
        self.assertEqual(infer_predicted_scale("1200000"), "")

    def test_percent_scale_and_base_value(self):
        result = score_tatqa(
            "12.5%", "12.5", gold_scale="percent", answer_type="arithmetic"
        )
        self.assertTrue(result.correct)
        self.assertEqual(result.predicted_scale, "percent")
        self.assertEqual(result.gold_scale, "percent")
        self.assertTrue(
            score_tatqa("0.125", "12.5", gold_scale="percent", answer_type="arithmetic").correct
        )
        self.assertFalse(
            score_tatqa("12.5", "12.5", gold_scale="percent", answer_type="arithmetic").correct
        )

    def test_million_scale_accepts_explicit_or_base_units(self):
        self.assertTrue(
            score_tatqa("$1.2 million", "1.2", gold_scale="million", answer_type="arithmetic").correct
        )
        self.assertTrue(
            score_tatqa("1200000", "1.2", gold_scale="million", answer_type="arithmetic").correct
        )
        self.assertFalse(
            score_tatqa("1.2", "1.2", gold_scale="million", answer_type="arithmetic").correct
        )
        # Official TAT-QA rendering rounds the raw number to two decimals
        # before applying the word scale.
        self.assertTrue(
            score_tatqa(
                "1.23 million", "1.23456", gold_scale="million", answer_type="arithmetic"
            ).correct
        )

    def test_count_requires_exact_integer(self):
        self.assertTrue(score_tatqa("3", "3", answer_type="count").correct)
        self.assertFalse(score_tatqa("3.1", "3", answer_type="count").correct)
        self.assertFalse(score_tatqa("-3", "3", answer_type="count").correct)

    def test_span_em_and_f1(self):
        exact = score_tatqa("The net income", "net income", answer_type="span")
        self.assertEqual(exact.exact_match, 1.0)
        partial = score_tatqa("income", "net income", answer_type="span")
        self.assertEqual(partial.exact_match, 0.0)
        self.assertEqual(partial.f1, 0.67)
        numeric_span = score_tatqa("the year 2020", "2020", answer_type="span")
        self.assertEqual(numeric_span.exact_match, 0.0)
        self.assertGreater(numeric_span.f1, 0.0)

    def test_multi_span_is_order_invariant(self):
        result = score_tatqa("debt; cash", ["cash", "debt"], answer_type="multi-span")
        self.assertEqual(result.exact_match, 1.0)
        self.assertEqual(result.f1, 1.0)

    def test_dispatch_uses_scorer_side_gold_scale(self):
        result = score_dataset(
            "tat-qa", "3 billion", "3", gold_scale="billion", answer_type="arithmetic"
        )
        self.assertTrue(result.correct)
        with self.assertRaises(ValueError):
            score_tatqa("1", "1", gold_scale="trillion")


class FinanceBenchScoringTests(unittest.TestCase):
    def test_conservative_exact_and_numeric(self):
        self.assertTrue(score_financebench("$1,250 million", "1250000000").correct)
        self.assertFalse(score_financebench("1250000000", "-1250000000").correct)
        self.assertFalse(
            score_financebench(
                "Revenue increased due to favorable pricing.",
                "Revenue increased.",
            ).correct
        )
        self.assertFalse(
            score_financebench(
                "2023",
                "In 2023, revenue increased because pricing was favorable.",
            ).correct
        )


class SemanticJudgeSchemaTests(unittest.TestCase):
    def test_request_is_framework_blind(self):
        request = build_semantic_judge_request(
            example_id="fb-17",
            question="Why did revenue increase?",
            reference_answer="Higher prices.",
            candidate_answer="Revenue increased because prices were higher.",
            evidence=["The filing attributes growth to higher prices."],
            salt="frozen-protocol-salt",
        )
        payload = request.to_dict()
        self.assertNotIn("framework", payload)
        self.assertNotIn("model", payload)
        self.assertEqual(len(request.blind_id), 24)
        prompt = render_semantic_judge_prompt(request)
        self.assertNotIn("nexus", prompt.lower())
        self.assertNotIn("react", prompt.lower())
        self.assertFalse(
            {"framework", "route", "model_under_test"}
            & set(SEMANTIC_JUDGE_REQUEST_SCHEMA["properties"])
        )

    def test_response_validation(self):
        response = SemanticJudgeResponse.from_dict(
            {
                "schema_version": "1.0",
                "blind_id": "abc12345",
                "judge_model": "judge-a",
                "response_correctness": 0.75,
                "faithfulness": 1.0,
                "rationale": "One minor numerical omission.",
                "claims_total": 2,
                "claims_supported": 2,
                "claims_unsupported": 0,
                "status": "success",
            }
        )
        self.assertEqual(response.response_correctness, 0.75)
        with self.assertRaises(ValueError):
            SemanticJudgeResponse(
                "1.0", "id", "judge", 1.1, 1.0, "", 1, 1, 0
            )
        with self.assertRaises(ValueError):
            SemanticJudgeResponse(
                "1.0", "id", "judge", 1.0, 1.0, "", 1, 1, 1
            )


if __name__ == "__main__":
    unittest.main()
