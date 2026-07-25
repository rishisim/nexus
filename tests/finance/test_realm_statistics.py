import unittest

from src.agents.finance.analyze_realm_statistics import (
    AnalysisError,
    _paired_rows,
    _validate_framework_rows,
)


def _row(example_id, *, dataset="finqa", framework="direct"):
    return {
        "example_id": example_id,
        "dataset": dataset,
        "framework": framework,
        "native_scores": {"exact_match": 1.0},
    }


class DevelopmentPairValidationTests(unittest.TestCase):
    def test_duplicate_example_ids_fail_loudly(self):
        with self.assertRaises(AnalysisError):
            _validate_framework_rows(
                "finqa",
                "direct",
                [_row("a"), _row("a")],
                expected_count=2,
            )

    def test_dataset_or_framework_mismatch_fails_loudly(self):
        with self.assertRaises(AnalysisError):
            _validate_framework_rows(
                "finqa",
                "direct",
                [_row("a", dataset="tatqa")],
                expected_count=1,
            )
        with self.assertRaises(AnalysisError):
            _validate_framework_rows(
                "finqa",
                "direct",
                [_row("a", framework="react")],
                expected_count=1,
            )

    def test_pair_join_rejects_missing_ids(self):
        with self.assertRaises(AnalysisError):
            _paired_rows([_row("a")], [_row("b")])


if __name__ == "__main__":
    unittest.main()
