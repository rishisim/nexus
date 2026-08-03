"""Audit headroom uncertainty and same-manifest seed stability.

The analysis is deliberately blocked until both the original capability study
and the post-hoc different-seed replication have complete process records.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .analyze_realm26_capability_ladder import _nested, _paired_rows
from .finance_statistics import _percentile, exact_mcnemar
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_capability_protocol import DATASETS, FRAMEWORKS, TIERS, load_manifest, load_protocol
from .run_realm26_capability_stability import (
    DEFAULT_STABILITY_SPEC,
    STABILITY_PROTOCOL_ID,
    load_stability_protocol,
)


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    p = float(probability)
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0
    return sum(
        math.comb(n, index) * (p ** index) * ((1 - p) ** (n - index))
        for index in range(k + 1)
    )


def clopper_pearson_interval(
    successes: int,
    trials: int,
    *,
    confidence: float = 0.95,
) -> Dict[str, float | int]:
    """Two-sided exact binomial interval without a SciPy dependency."""

    k, n = int(successes), int(trials)
    if n <= 0 or k < 0 or k > n or not 0 < confidence < 1:
        raise ValueError("Invalid exact-binomial interval inputs")
    alpha_tail = (1 - confidence) / 2
    lower = 0.0
    if k:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            survival = 1 - _binomial_cdf(k - 1, n, mid)
            if survival < alpha_tail:
                lo = mid
            else:
                hi = mid
        lower = (lo + hi) / 2
    upper = 1.0
    if k < n:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            cdf = _binomial_cdf(k, n, mid)
            if cdf > alpha_tail:
                lo = mid
            else:
                hi = mid
        upper = (lo + hi) / 2
    return {
        "confidence": confidence,
        "estimate": k / n,
        "lower": lower,
        "successes": k,
        "trials": n,
        "upper": upper,
    }


def continuous_oracle_headroom(
    static_by_dataset: Mapping[str, Sequence[float]],
    react_by_dataset: Mapping[str, Sequence[float]],
    *,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int = 20260804,
) -> Dict[str, Any]:
    """Dataset-macro per-item oracle gain over the better single arm."""

    if set(static_by_dataset) != set(DATASETS) or set(react_by_dataset) != set(DATASETS):
        raise ValueError("Continuous headroom requires every frozen dataset")
    prepared: Dict[str, Tuple[List[float], List[float]]] = {}
    for dataset in DATASETS:
        static = [float(value) for value in static_by_dataset[dataset]]
        react = [float(value) for value in react_by_dataset[dataset]]
        if not static or len(static) != len(react):
            raise ValueError(f"Unpaired or empty quality rows for {dataset}")
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in static + react):
            raise ValueError(f"Out-of-range quality value for {dataset}")
        prepared[dataset] = (static, react)

    static_macro = mean(mean(values[0]) for values in prepared.values())
    react_macro = mean(mean(values[1]) for values in prepared.values())
    oracle_macro = mean(
        mean(max(left, right) for left, right in zip(*values))
        for values in prepared.values()
    )
    estimate = oracle_macro - max(static_macro, react_macro)
    rng = random.Random(seed)
    samples: List[float] = []
    for _ in range(n_resamples):
        static_means: List[float] = []
        react_means: List[float] = []
        oracle_means: List[float] = []
        for dataset in sorted(prepared):
            static, react = prepared[dataset]
            indices = [rng.randrange(len(static)) for _ in static]
            static_means.append(mean(static[index] for index in indices))
            react_means.append(mean(react[index] for index in indices))
            oracle_means.append(mean(max(static[index], react[index]) for index in indices))
        samples.append(mean(oracle_means) - max(mean(static_means), mean(react_means)))
    samples.sort()
    alpha = 1 - confidence
    return {
        "better_single_arm": "static" if static_macro >= react_macro else "react",
        "confidence": confidence,
        "estimate": estimate,
        "lower": _percentile(samples, alpha / 2),
        "n_pairs": sum(len(values[0]) for values in prepared.values()),
        "n_resamples": n_resamples,
        "oracle_macro_quality": oracle_macro,
        "react_macro_quality": react_macro,
        "seed": seed,
        "static_macro_quality": static_macro,
        "upper": _percentile(samples, 1 - alpha / 2),
    }


def _validate_complete_run(root: Path, expected_protocol_id: str, expected_seed: int) -> None:
    completion_path = root / "study_complete.json"
    if not completion_path.exists():
        raise ProtocolError(f"Analysis is blocked until the run completes: {root}")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if (
        completion.get("status") != "complete"
        or completion.get("process_checks_passed") is not True
        or completion.get("tier_episode_counts") != {tier: 300 for tier in TIERS}
    ):
        raise ProtocolError(f"Incomplete three-tier process record: {root}")
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if config.get("protocol_id") != expected_protocol_id:
        raise ProtocolError(f"Run protocol identity mismatch: {root}")
    for tier in TIERS:
        for dataset in DATASETS:
            for framework in FRAMEWORKS:
                rows = json.loads((root / tier / dataset / framework / "results.json").read_text(encoding="utf-8"))
                if len(rows) != 50 or any(
                    row.get("protocol_id") != expected_protocol_id
                    or int(row.get("seed", -1)) != expected_seed
                    or row.get("status") != "success"
                    for row in rows
                ):
                    raise ProtocolError(f"Run seed, protocol, status, or row count drift: {tier}/{dataset}/{framework}")


def _sanitized_pairs(
    run_label: str,
    protocol: Mapping[str, Any],
    manifest: Mapping[str, Any],
    root: Path,
) -> List[Dict[str, Any]]:
    metric_paths = protocol["analysis"]["dataset_quality_metrics"]
    output: List[Dict[str, Any]] = []
    for tier in TIERS:
        paired = _paired_rows(protocol, manifest, root / tier, tier)
        for dataset in DATASETS:
            for slot, (static, react) in enumerate(zip(paired[dataset]["static"], paired[dataset]["react"])):
                output.append({
                    "dataset": dataset,
                    "item_slot": slot,
                    "react_exact": _nested(react, "native_scores.exact_match"),
                    "react_quality": _nested(react, metric_paths[dataset]),
                    "run": run_label,
                    "static_exact": _nested(static, "native_scores.exact_match"),
                    "static_quality": _nested(static, metric_paths[dataset]),
                    "tier": tier,
                })
    return output


def _analyze_pairs(
    rows: Sequence[Mapping[str, Any]],
    *,
    n_resamples: int,
    seed: int,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for tier in TIERS:
        tier_rows = [row for row in rows if row["tier"] == tier]
        static_by_dataset: Dict[str, List[float]] = defaultdict(list)
        react_by_dataset: Dict[str, List[float]] = defaultdict(list)
        static_exact: List[float] = []
        react_exact: List[float] = []
        per_dataset: Dict[str, Any] = {}
        for dataset in DATASETS:
            dataset_rows = [row for row in tier_rows if row["dataset"] == dataset]
            if len(dataset_rows) != 50:
                raise ProtocolError(f"Sanitized audit rows are incomplete: {tier}/{dataset}")
            static = [float(row["static_quality"]) for row in dataset_rows]
            react = [float(row["react_quality"]) for row in dataset_rows]
            static_by_dataset[dataset].extend(static)
            react_by_dataset[dataset].extend(react)
            per_dataset[dataset] = {
                "continuous_headroom": mean(max(left, right) for left, right in zip(static, react))
                - max(mean(static), mean(react)),
                "react_quality": mean(react),
                "static_quality": mean(static),
            }
            static_exact.extend(float(row["static_exact"]) for row in dataset_rows)
            react_exact.extend(float(row["react_exact"]) for row in dataset_rows)
        matrix = exact_mcnemar(static_exact, react_exact).to_dict()
        union = matrix["both_correct"] + matrix["left_only_correct"] + matrix["right_only_correct"]
        static_correct = matrix["both_correct"] + matrix["left_only_correct"]
        react_correct = matrix["both_correct"] + matrix["right_only_correct"]
        rare = union - max(static_correct, react_correct)
        result[tier] = {
            "continuous_headroom": continuous_oracle_headroom(
                static_by_dataset,
                react_by_dataset,
                n_resamples=n_resamples,
                seed=seed,
            ),
            "exact_headroom": {
                "better_single_arm": "static" if static_correct >= react_correct else "react",
                **clopper_pearson_interval(rare, len(static_exact)),
            },
            "exact_matrix": matrix,
            "per_dataset": per_dataset,
        }
    return result


def analyze(
    original_root: str | Path,
    replication_root: str | Path,
    *,
    base_protocol_path: str | Path,
    stability_spec_path: str | Path,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    base = load_protocol(base_protocol_path)
    stability, stability_base, spec = load_stability_protocol(stability_spec_path)
    if fingerprint({key: value for key, value in base.items() if key != "_path"}) != fingerprint(
        {key: value for key, value in stability_base.items() if key != "_path"}
    ):
        raise ProtocolError("Stability overlay does not derive from the analyzed base protocol")
    manifest = load_manifest(base)
    original_path, replication_path = Path(original_root).resolve(), Path(replication_root).resolve()
    _validate_complete_run(
        original_path,
        base["protocol_id"],
        int(base["inference"]["request_seed"]),
    )
    _validate_complete_run(
        replication_path,
        STABILITY_PROTOCOL_ID,
        int(stability["inference"]["request_seed"]),
    )
    original_pairs = _sanitized_pairs("original", base, manifest, original_path)
    replication_pairs = _sanitized_pairs("replication", stability, manifest, replication_path)
    pairs = original_pairs + replication_pairs
    analysis_spec = spec["analysis"]
    runs = {
        label: _analyze_pairs(
            [row for row in pairs if row["run"] == label],
            n_resamples=int(analysis_spec["bootstrap_resamples"]),
            seed=int(analysis_spec["bootstrap_seed"]),
        )
        for label in ("original", "replication")
    }
    comparison = {
        tier: {
            "continuous_headroom_change": (
                runs["replication"][tier]["continuous_headroom"]["estimate"]
                - runs["original"][tier]["continuous_headroom"]["estimate"]
            ),
            "exact_headroom_count_change": (
                runs["replication"][tier]["exact_headroom"]["successes"]
                - runs["original"][tier]["exact_headroom"]["successes"]
            ),
            "original_better_arm": runs["original"][tier]["continuous_headroom"]["better_single_arm"],
            "replication_better_arm": runs["replication"][tier]["continuous_headroom"]["better_single_arm"],
        }
        for tier in TIERS
    }
    result: Dict[str, Any] = {
        "analysis_plan": analysis_spec,
        "claims_scope": spec["claims_scope"],
        "comparison": comparison,
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "runs": runs,
        "schema_version": "realm26-capability-audit-v1",
    }
    result["analysis_fingerprint"] = fingerprint(result)
    return result, pairs


def render_memo(result: Mapping[str, Any]) -> str:
    lines = [
        "# REALM capability headroom and seed-stability audit",
        "",
        str(result["claims_scope"]),
        "",
    ]
    for tier in TIERS:
        lines.extend([f"## {tier.title()}", ""])
        for run in ("original", "replication"):
            row = result["runs"][run][tier]
            continuous = row["continuous_headroom"]
            exact = row["exact_headroom"]
            matrix = row["exact_matrix"]
            lines.append(
                f"- {run}: continuous headroom {continuous['estimate']:.4f} "
                f"(95% CI [{continuous['lower']:.4f}, {continuous['upper']:.4f}]); "
                f"exact headroom {exact['estimate']:.4f} "
                f"(95% CI [{exact['lower']:.4f}, {exact['upper']:.4f}]); "
                f"B/S/R/N={matrix['both_correct']}/{matrix['left_only_correct']}/"
                f"{matrix['right_only_correct']}/{matrix['both_wrong']}."
            )
        lines.append("")
    lines.extend([
        "The replication uses the same frozen development items and a different request seed. ",
        "It measures generation stability conditional on this sample and is not an independent fresh-sample confirmation.",
        "",
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-protocol", default=str(Path(__file__).with_name("protocols") / "realm26_capability_ladder.json"))
    parser.add_argument("--stability-spec", default=str(DEFAULT_STABILITY_SPEC))
    parser.add_argument("--original-root", required=True)
    parser.add_argument("--replication-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--memo", required=True)
    parser.add_argument("--pairs-output", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    result, pairs = analyze(
        args.original_root,
        args.replication_root,
        base_protocol_path=args.base_protocol,
        stability_spec_path=args.stability_spec,
    )
    write_stable_json(Path(args.output), result)
    Path(args.memo).write_text(render_memo(result), encoding="utf-8")
    Path(args.pairs_output).write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in pairs),
        encoding="utf-8",
    )
    print(json.dumps({
        "analysis_fingerprint": result["analysis_fingerprint"],
        "sanitized_pair_rows": len(pairs),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
