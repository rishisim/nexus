"""Reproducible statistics and efficiency summaries for finance experiments."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


Number = Union[int, float]


@dataclass(frozen=True)
class ConfidenceInterval:
    """Point estimate and percentile interval for ``right - left``."""

    estimate: float
    lower: float
    upper: float
    confidence: float
    n_pairs: int
    n_resamples: int
    seed: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McNemarResult:
    """Exact two-sided McNemar result for paired binary outcomes."""

    both_correct: int
    left_only_correct: int
    right_only_correct: int
    both_wrong: int
    discordant_pairs: int
    statistic: float
    p_value: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _finite_values(values: Iterable[Number], *, name: str) -> List[float]:
    output = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must contain only numeric values")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name} must contain only finite values")
        output.append(number)
    return output


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("Cannot compute a percentile of an empty sequence")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0, 1]")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * (len(sorted_values) - 1)
    lower_idx = int(math.floor(position))
    upper_idx = int(math.ceil(position))
    if lower_idx == upper_idx:
        return sorted_values[lower_idx]
    fraction = position - lower_idx
    return sorted_values[lower_idx] + fraction * (
        sorted_values[upper_idx] - sorted_values[lower_idx]
    )


def paired_bootstrap_ci(
    left: Sequence[Number],
    right: Sequence[Number],
    *,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int = 20260709,
) -> ConfidenceInterval:
    """Percentile bootstrap CI for paired mean difference ``right - left``."""

    left_values = _finite_values(left, name="left")
    right_values = _finite_values(right, name="right")
    if len(left_values) != len(right_values):
        raise ValueError("Paired inputs must have the same length")
    if not left_values:
        raise ValueError("At least one pair is required")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if n_resamples < 1:
        raise ValueError("n_resamples must be positive")

    differences = [right_value - left_value for left_value, right_value in zip(left_values, right_values)]
    estimate = mean(differences)
    rng = random.Random(seed)
    n_pairs = len(differences)
    samples = []
    for _ in range(n_resamples):
        samples.append(mean(differences[rng.randrange(n_pairs)] for _ in range(n_pairs)))
    samples.sort()
    alpha = 1 - confidence
    return ConfidenceInterval(
        estimate=estimate,
        lower=_percentile(samples, alpha / 2),
        upper=_percentile(samples, 1 - alpha / 2),
        confidence=confidence,
        n_pairs=n_pairs,
        n_resamples=n_resamples,
        seed=seed,
    )


def exact_mcnemar(left: Sequence[Number], right: Sequence[Number]) -> McNemarResult:
    """Run the exact two-sided McNemar/binomial test.

    Values must be binary (0/1 or bool).  The continuity-corrected chi-square
    statistic is included descriptively; inference uses the exact binomial
    p-value, including the all-concordant edge case ``p=1``.
    """

    if len(left) != len(right):
        raise ValueError("Paired inputs must have the same length")
    if not left:
        raise ValueError("At least one pair is required")
    counts = {
        "both_correct": 0,
        "left_only_correct": 0,
        "right_only_correct": 0,
        "both_wrong": 0,
    }
    for left_value, right_value in zip(left, right):
        if left_value not in (0, 1, False, True) or right_value not in (0, 1, False, True):
            raise ValueError("McNemar inputs must be binary")
        l_value, r_value = bool(left_value), bool(right_value)
        if l_value and r_value:
            counts["both_correct"] += 1
        elif l_value:
            counts["left_only_correct"] += 1
        elif r_value:
            counts["right_only_correct"] += 1
        else:
            counts["both_wrong"] += 1

    left_only = counts["left_only_correct"]
    right_only = counts["right_only_correct"]
    discordant = left_only + right_only
    if discordant == 0:
        statistic = 0.0
        p_value = 1.0
    else:
        statistic = (max(abs(left_only - right_only) - 1, 0) ** 2) / discordant
        tail = min(left_only, right_only)
        cumulative = sum(math.comb(discordant, k) for k in range(tail + 1)) / (2 ** discordant)
        p_value = min(1.0, 2 * cumulative)

    return McNemarResult(
        **counts,
        discordant_pairs=discordant,
        statistic=statistic,
        p_value=p_value,
    )


def holm_correction(
    p_values: Union[Sequence[Number], Mapping[str, Number]],
    *,
    alpha: float = 0.05,
) -> Union[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Holm step-down family-wise error correction.

    The output reports monotone adjusted p-values and sequential reject flags.
    A mapping input preserves hypothesis names; a sequence returns ordered rows.
    """

    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    is_mapping = isinstance(p_values, Mapping)
    items = list(p_values.items()) if is_mapping else list(enumerate(p_values))
    checked: List[Tuple[Any, float]] = []
    for key, value in items:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("p-values must be numeric")
        number = float(value)
        if not math.isfinite(number) or not 0 <= number <= 1:
            raise ValueError("p-values must be finite and in [0, 1]")
        checked.append((key, number))
    if not checked:
        return {} if is_mapping else []

    ordered = sorted(checked, key=lambda item: item[1])
    family_size = len(ordered)
    running_adjusted = 0.0
    rejection_open = True
    rows: Dict[Any, Dict[str, Any]] = {}
    for rank, (key, p_value) in enumerate(ordered, 1):
        multiplier = family_size - rank + 1
        running_adjusted = max(running_adjusted, min(1.0, multiplier * p_value))
        critical = alpha / multiplier
        reject = rejection_open and p_value <= critical
        if not reject:
            rejection_open = False
        rows[key] = {
            "p_value": p_value,
            "adjusted_p_value": running_adjusted,
            "critical_value": critical,
            "reject": reject,
            "rank": rank,
        }
    if is_mapping:
        return {key: rows[key] for key, _ in checked}
    return [rows[index] for index, _ in checked]


def macro_summary(
    dataset_metrics: Mapping[str, Mapping[str, Any]],
    *,
    metric: str = "accuracy",
    datasets: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Compute unweighted per-framework macro means across datasets.

    Expected input shape is ``{dataset: {framework: {metric: value}}}``.  A
    framework value may also be the scalar metric itself.  Missing values are
    reported and excluded rather than silently treated as zero.
    """

    selected = list(datasets) if datasets is not None else list(dataset_metrics)
    if not selected:
        raise ValueError("At least one dataset is required")
    missing_datasets = [dataset for dataset in selected if dataset not in dataset_metrics]
    if missing_datasets:
        raise KeyError(f"Missing dataset summaries: {missing_datasets}")

    frameworks = sorted(
        {
            framework
            for dataset in selected
            for framework in dataset_metrics[dataset]
        }
    )
    output: Dict[str, Any] = {
        "metric": metric,
        "datasets": selected,
        "dataset_count": len(selected),
        "frameworks": {},
    }
    for framework in frameworks:
        values: List[float] = []
        missing: List[str] = []
        per_dataset: Dict[str, float] = {}
        for dataset in selected:
            framework_metrics = dataset_metrics[dataset].get(framework)
            if framework_metrics is None:
                missing.append(dataset)
                continue
            value = (
                framework_metrics.get(metric)
                if isinstance(framework_metrics, Mapping)
                else framework_metrics
            )
            if value is None:
                missing.append(dataset)
                continue
            checked = _finite_values([value], name=f"{dataset}.{framework}.{metric}")[0]
            values.append(checked)
            per_dataset[dataset] = checked
        output["frameworks"][framework] = {
            "macro_mean": mean(values) if values else None,
            "included_dataset_count": len(values),
            "missing_datasets": missing,
            "per_dataset": per_dataset,
        }
    return output


def _first_numeric(row: Mapping[str, Any], *names: str) -> Optional[float]:
    for name in names:
        value: Any = row
        found = True
        for part in name.split("."):
            if not isinstance(value, Mapping) or part not in value:
                found = False
                break
            value = value[part]
        if found and value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            number = float(value)
            if math.isfinite(number):
                return number
    return None


def cost_latency_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    successful_only: bool = True,
) -> Dict[str, Any]:
    """Summarize calls, token categories, dollars, and end-to-end latency.

    Both flat result fields and fields nested below ``telemetry`` are accepted.
    Telemetry completeness is the share of included examples containing cost,
    total tokens, and latency.  Zero is valid and is not treated as missing.
    """

    included = [
        row
        for row in rows
        if not successful_only or row.get("status", "success") == "success"
    ]
    token_fields = {
        "input_tokens": ("input_tokens", "telemetry.input_tokens"),
        "cached_tokens": ("cached_tokens", "telemetry.cached_tokens"),
        "reasoning_tokens": ("reasoning_tokens", "telemetry.reasoning_tokens"),
        "output_tokens": ("output_tokens", "telemetry.output_tokens"),
        "total_tokens": ("total_tokens", "telemetry.total_tokens"),
    }
    token_totals = {field: 0.0 for field in token_fields}
    token_coverage = {field: 0 for field in token_fields}
    costs: List[float] = []
    latencies: List[float] = []
    calls: List[float] = []
    retrievals: List[float] = []
    complete = 0

    for row in included:
        values = {
            field: _first_numeric(row, *aliases)
            for field, aliases in token_fields.items()
        }
        for field, value in values.items():
            if value is not None:
                token_totals[field] += value
                token_coverage[field] += 1
        cost = _first_numeric(
            row,
            "provider_cost_usd",
            "estimated_cost_usd",
            "cost_usd",
            "telemetry.provider_cost_usd",
            "telemetry.estimated_cost_usd",
        )
        latency = _first_numeric(row, "latency_ms", "telemetry.latency_ms")
        call_count = _first_numeric(row, "llm_call_count", "n_calls", "telemetry.llm_call_count")
        retrieval_count = _first_numeric(
            row, "retrieval_call_count", "retrieval_calls", "telemetry.retrieval_call_count"
        )
        if cost is not None:
            costs.append(cost)
        if latency is not None:
            latencies.append(latency)
        if call_count is not None:
            calls.append(call_count)
        if retrieval_count is not None:
            retrievals.append(retrieval_count)
        if cost is not None and values["total_tokens"] is not None and latency is not None:
            complete += 1

    n = len(included)
    sorted_latencies = sorted(latencies)
    return {
        "input_rows": len(rows),
        "included_examples": n,
        "excluded_examples": len(rows) - n,
        "telemetry_complete_examples": complete,
        "telemetry_completeness": complete / n if n else None,
        "total_llm_calls": sum(calls),
        "mean_llm_calls": mean(calls) if calls else None,
        "total_retrieval_calls": sum(retrievals),
        "mean_retrieval_calls": mean(retrievals) if retrievals else None,
        "token_totals": token_totals,
        "token_coverage": token_coverage,
        "total_cost_usd": sum(costs),
        "mean_cost_usd": mean(costs) if costs else None,
        "cost_coverage": len(costs) / n if n else None,
        "latency_median_ms": median(latencies) if latencies else None,
        "latency_p95_ms": _percentile(sorted_latencies, 0.95) if latencies else None,
        "latency_coverage": len(latencies) / n if n else None,
    }


def _response_mapping(response: Any) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        return response
    if hasattr(response, "to_dict"):
        payload = response.to_dict()
        if isinstance(payload, Mapping):
            return payload
    raise TypeError("Judge responses must be mappings or expose to_dict()")


def _pearson(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) < 2:
        return None
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_ss = sum((value - left_mean) ** 2 for value in left)
    right_ss = sum((value - right_mean) ** 2 for value in right)
    if left_ss == 0 or right_ss == 0:
        return None
    return numerator / math.sqrt(left_ss * right_ss)


def dual_judge_summary(
    left_responses: Sequence[Any],
    right_responses: Sequence[Any],
    *,
    disagreement_threshold: float = 0.25,
) -> Dict[str, Any]:
    """Summarize blinded agreement between two semantic judges.

    Only successful responses sharing a ``blind_id`` are paired.  The function
    reports each judge separately; it never silently averages them into one
    semantic score.
    """

    if not 0 <= disagreement_threshold <= 1:
        raise ValueError("disagreement_threshold must be in [0, 1]")

    def index(responses: Sequence[Any]) -> Dict[str, Mapping[str, Any]]:
        indexed: Dict[str, Mapping[str, Any]] = {}
        for response in responses:
            payload = _response_mapping(response)
            if payload.get("status", "success") != "success":
                continue
            blind_id = str(payload.get("blind_id", ""))
            if not blind_id:
                raise ValueError("Every successful judge response requires a blind_id")
            if blind_id in indexed:
                raise ValueError(f"Duplicate judge response for blind_id {blind_id!r}")
            indexed[blind_id] = payload
        return indexed

    left_by_id, right_by_id = index(left_responses), index(right_responses)
    paired_ids = sorted(set(left_by_id) & set(right_by_id))
    output: Dict[str, Any] = {
        "paired_examples": len(paired_ids),
        "left_only_examples": len(set(left_by_id) - set(right_by_id)),
        "right_only_examples": len(set(right_by_id) - set(left_by_id)),
        "disagreement_threshold": disagreement_threshold,
        "metrics": {},
    }
    for metric in ("response_correctness", "faithfulness"):
        left_values = _finite_values(
            [left_by_id[item][metric] for item in paired_ids], name=f"left.{metric}"
        )
        right_values = _finite_values(
            [right_by_id[item][metric] for item in paired_ids], name=f"right.{metric}"
        )
        differences = [abs(left - right) for left, right in zip(left_values, right_values)]
        disagreement_count = sum(value >= disagreement_threshold for value in differences)
        output["metrics"][metric] = {
            "left_mean": mean(left_values) if left_values else None,
            "right_mean": mean(right_values) if right_values else None,
            "pearson_correlation": _pearson(left_values, right_values),
            "mean_absolute_difference": mean(differences) if differences else None,
            "disagreement_count": disagreement_count,
            "disagreement_rate": disagreement_count / len(differences) if differences else None,
        }
    return output


summarize_efficiency = cost_latency_summary


__all__ = [
    "ConfidenceInterval",
    "McNemarResult",
    "cost_latency_summary",
    "dual_judge_summary",
    "exact_mcnemar",
    "holm_correction",
    "macro_summary",
    "paired_bootstrap_ci",
    "summarize_efficiency",
]
