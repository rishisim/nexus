import unittest

from src.agents.finance.finance_statistics import (
    cost_latency_summary,
    dual_judge_summary,
    exact_mcnemar,
    holm_correction,
    macro_summary,
    paired_bootstrap_ci,
    stratified_paired_bootstrap_ci,
)


class PairedInferenceTests(unittest.TestCase):
    def test_paired_bootstrap_estimates_right_minus_left(self):
        result = paired_bootstrap_ci(
            [0, 0, 1, 0],
            [1, 1, 1, 1],
            n_resamples=500,
            seed=7,
        )
        self.assertEqual(result.estimate, 0.75)
        self.assertGreaterEqual(result.lower, 0.0)
        self.assertLessEqual(result.upper, 1.0)
        self.assertEqual(
            result,
            paired_bootstrap_ci(
                [0, 0, 1, 0], [1, 1, 1, 1], n_resamples=500, seed=7
            ),
        )

    def test_bootstrap_rejects_unpaired_or_nonfinite_data(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_ci([1], [1, 0])
        with self.assertRaises(ValueError):
            paired_bootstrap_ci([float("nan")], [1])

    def test_stratified_bootstrap_uses_unweighted_stratum_means(self):
        result = stratified_paired_bootstrap_ci(
            {"small": [0, 1], "large": [0, 0, 0, 0]},
            {"small": [1, 1], "large": [0, 0, 1, 1]},
            n_resamples=500,
            seed=11,
        )
        self.assertEqual(result.estimate, 0.5)
        self.assertEqual(result.n_pairs, 6)
        self.assertGreaterEqual(result.lower, 0.0)
        self.assertLessEqual(result.upper, 1.0)
        self.assertEqual(
            result,
            stratified_paired_bootstrap_ci(
                {"small": [0, 1], "large": [0, 0, 0, 0]},
                {"small": [1, 1], "large": [0, 0, 1, 1]},
                n_resamples=500,
                seed=11,
            ),
        )

    def test_stratified_bootstrap_rejects_missing_or_misaligned_strata(self):
        with self.assertRaises(ValueError):
            stratified_paired_bootstrap_ci({"a": [0]}, {"b": [1]})
        with self.assertRaises(ValueError):
            stratified_paired_bootstrap_ci({"a": [0, 1]}, {"a": [1]})

    def test_exact_mcnemar_counts_and_p_value(self):
        # one left-only and four right-only outcomes -> exact p = 0.375
        result = exact_mcnemar(
            [1, 0, 0, 0, 0, 1, 0],
            [0, 1, 1, 1, 1, 1, 0],
        )
        self.assertEqual(result.left_only_correct, 1)
        self.assertEqual(result.right_only_correct, 4)
        self.assertEqual(result.both_correct, 1)
        self.assertEqual(result.both_wrong, 1)
        self.assertAlmostEqual(result.p_value, 0.375)

    def test_mcnemar_all_concordant(self):
        result = exact_mcnemar([1, 0], [1, 0])
        self.assertEqual(result.discordant_pairs, 0)
        self.assertEqual(result.p_value, 1.0)

    def test_holm_correction_is_monotone_and_preserves_names(self):
        corrected = holm_correction({"finqa": 0.01, "tatqa": 0.03, "convfinqa": 0.04})
        self.assertAlmostEqual(corrected["finqa"]["adjusted_p_value"], 0.03)
        self.assertAlmostEqual(corrected["tatqa"]["adjusted_p_value"], 0.06)
        self.assertAlmostEqual(corrected["convfinqa"]["adjusted_p_value"], 0.06)
        self.assertTrue(corrected["finqa"]["reject"])
        self.assertFalse(corrected["tatqa"]["reject"])
        self.assertFalse(corrected["convfinqa"]["reject"])


class AggregationTests(unittest.TestCase):
    def test_macro_summary_is_unweighted(self):
        summary = macro_summary(
            {
                "finqa": {"nexus": {"accuracy": 0.8}, "react": {"accuracy": 0.7}},
                "tatqa": {"nexus": {"accuracy": 0.6}, "react": {"accuracy": 0.5}},
                "convfinqa": {"nexus": {"accuracy": 1.0}, "react": {"accuracy": 0.6}},
            },
            datasets=["finqa", "tatqa", "convfinqa"],
        )
        self.assertAlmostEqual(summary["frameworks"]["nexus"]["macro_mean"], 0.8)
        self.assertAlmostEqual(summary["frameworks"]["react"]["macro_mean"], 0.6)
        self.assertEqual(summary["dataset_count"], 3)

    def test_macro_summary_reports_missing_framework_dataset(self):
        summary = macro_summary(
            {
                "finqa": {"nexus": 0.8},
                "tatqa": {"react": 0.5},
            }
        )
        self.assertEqual(summary["frameworks"]["nexus"]["missing_datasets"], ["tatqa"])
        self.assertEqual(summary["frameworks"]["react"]["missing_datasets"], ["finqa"])

    def test_cost_latency_summary_flat_and_nested_telemetry(self):
        summary = cost_latency_summary(
            [
                {
                    "status": "success",
                    "input_tokens": 100,
                    "cached_tokens": 0,
                    "reasoning_tokens": 0,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "provider_cost_usd": 0.01,
                    "latency_ms": 100,
                    "n_calls": 1,
                    "retrieval_calls": 2,
                },
                {
                    "status": "success",
                    "telemetry": {
                        "input_tokens": 200,
                        "cached_tokens": 50,
                        "reasoning_tokens": 10,
                        "output_tokens": 30,
                        "total_tokens": 240,
                        "estimated_cost_usd": 0.02,
                        "latency_ms": 200,
                        "llm_call_count": 2,
                        "retrieval_call_count": 3,
                    },
                },
                {"status": "failed", "total_tokens": 999, "cost_usd": 1.0},
            ]
        )
        self.assertEqual(summary["included_examples"], 2)
        self.assertEqual(summary["telemetry_completeness"], 1.0)
        self.assertEqual(summary["token_totals"]["total_tokens"], 360)
        self.assertAlmostEqual(summary["total_cost_usd"], 0.03)
        self.assertEqual(summary["latency_median_ms"], 150)
        self.assertEqual(summary["latency_p95_ms"], 195)
        self.assertEqual(summary["total_llm_calls"], 3)
        self.assertEqual(summary["total_retrieval_calls"], 5)

    def test_telemetry_completeness_requires_all_primary_fields(self):
        summary = cost_latency_summary(
            [{"status": "success", "total_tokens": 10, "latency_ms": 5}]
        )
        self.assertEqual(summary["telemetry_completeness"], 0.0)
        self.assertIsNone(summary["mean_cost_usd"])

    def test_dual_judge_summary_keeps_judges_separate(self):
        left = [
            {
                "blind_id": "a",
                "status": "success",
                "response_correctness": 1.0,
                "faithfulness": 0.75,
            },
            {
                "blind_id": "b",
                "status": "success",
                "response_correctness": 0.25,
                "faithfulness": 0.5,
            },
        ]
        right = [
            {
                "blind_id": "a",
                "status": "success",
                "response_correctness": 0.75,
                "faithfulness": 0.75,
            },
            {
                "blind_id": "b",
                "status": "success",
                "response_correctness": 0.75,
                "faithfulness": 0.25,
            },
        ]
        summary = dual_judge_summary(left, right, disagreement_threshold=0.25)
        correctness = summary["metrics"]["response_correctness"]
        self.assertEqual(summary["paired_examples"], 2)
        self.assertEqual(correctness["left_mean"], 0.625)
        self.assertEqual(correctness["right_mean"], 0.75)
        self.assertEqual(correctness["disagreement_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
