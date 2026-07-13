"""Build frozen development summaries and fit the ICAIF selective router.

This script consumes only completed development-partition results.  FinDER is
summarized for cost and operational behavior but is deliberately excluded from
the binary router target because the study has no human-validated objective
correctness label for that dataset.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from .finance_env import make_finance_env
from .protocol_v2 import DATASETS, stable_json_text
from .selective_router import (
    DevelopmentExample,
    extract_router_features,
    train_selective_router,
)


FRAMEWORKS = ("direct", "cot", "react", "nexus", "selective")
OBJECTIVE_ROUTER_DATASETS = ("financebench", "finqa", "tatqa", "convfinqa")
PRIMARY_DATASETS = ("finqa", "tatqa", "convfinqa")


def _slug(model_id: str) -> str:
    return model_id.replace("/", "-").replace(":", "-")


def _effective_cost(row: Mapping[str, Any]) -> float:
    provider = row.get("provider_cost_usd")
    if provider is not None:
        return float(provider)
    return float(row.get("estimated_cost_usd") or 0.0)


def _score(row: Mapping[str, Any], metric: str) -> float | None:
    value = (row.get("native_scores") or {}).get(metric)
    return None if value is None else float(value)


def _percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _load_framework(run_dir: Path, framework: str) -> list[Dict[str, Any]]:
    path = run_dir / framework / "results.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if len(rows) != 50:
        raise ValueError(f"{path}: expected 50 development rows, found {len(rows)}")
    identifiers = [str(row["example_id"]) for row in rows]
    if len(set(identifiers)) != 50:
        raise ValueError(f"{path}: duplicate development example IDs")
    failed = [row for row in rows if row.get("status") != "success"]
    if failed:
        raise ValueError(f"{path}: {len(failed)} non-success rows must be resolved first")
    return rows


def _framework_summary(dataset: str, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    exact = [value for row in rows if (value := _score(row, "exact_match")) is not None]
    f1 = [value for row in rows if (value := _score(row, "f1")) is not None]
    costs = [_effective_cost(row) for row in rows]
    latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
    calls = [int(row.get("llm_call_count") or 0) for row in rows]
    primary_value = f1 if dataset == "tatqa" else exact
    return {
        "count": len(rows),
        "exact_match": statistics.mean(exact) if exact else None,
        "f1": statistics.mean(f1) if f1 else None,
        "primary_value": statistics.mean(primary_value) if primary_value else None,
        "calls_total": sum(calls),
        "calls_per_example": statistics.mean(calls),
        "cost_total_usd": sum(costs),
        "cost_per_example_usd": statistics.mean(costs),
        "latency_median_ms": statistics.median(latencies),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "telemetry_complete": sum(
            row.get("resolved_model")
            and row.get("total_tokens") is not None
            and row.get("latency_ms") is not None
            and (
                row.get("provider_cost_usd") is not None
                or row.get("estimated_cost_usd") is not None
            )
            for row in rows
        ),
    }


def _index(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    return {str(row["example_id"]): row for row in rows}


def analyze(
    results_root: Path,
    model_id: str,
    results_tag: str,
    artifact_dir: Path,
    router_path: Path,
    figure_dir: Path,
) -> Dict[str, Any]:
    runs: Dict[str, Dict[str, list[Dict[str, Any]]]] = {}
    summary: Dict[str, Any] = {
        "schema_version": "finance-development-analysis-v1",
        "model_id": model_id,
        "results_tag": results_tag,
        "partition": "development",
        "datasets": {},
        "router_label_policy": {
            "included": list(OBJECTIVE_ROUTER_DATASETS),
            "excluded": {"finder": "no objective human-validated correctness label"},
            "positive": "react exact-correct and static-nexus exact-incorrect",
        },
    }
    for dataset in DATASETS:
        run_dir = (
            results_root
            / dataset
            / f"finance_icaif26_v2_development_{_slug(model_id)}_{results_tag}"
        )
        framework_rows = {
            framework: _load_framework(run_dir, framework) for framework in FRAMEWORKS
        }
        expected_ids = set(_index(framework_rows[FRAMEWORKS[0]]))
        if any(set(_index(rows)) != expected_ids for rows in framework_rows.values()):
            raise ValueError(f"{dataset}: frameworks are not paired on identical examples")
        runs[dataset] = framework_rows
        summary["datasets"][dataset] = {
            framework: _framework_summary(dataset, rows)
            for framework, rows in framework_rows.items()
        }

    examples: list[DevelopmentExample] = []
    disagreement: Dict[str, Dict[str, int]] = {}
    for dataset in OBJECTIVE_ROUTER_DATASETS:
        env = make_finance_env(dataset)
        direct = _index(runs[dataset]["direct"])
        static = _index(runs[dataset]["nexus"])
        react = _index(runs[dataset]["react"])
        counts = {"static_only": 0, "react_only": 0, "both": 0, "neither": 0}
        for example_id in sorted(direct):
            direct_row = direct[example_id]
            static_row = static[example_id]
            react_row = react[example_id]
            static_correct = _score(static_row, "exact_match") == 1.0
            react_correct = _score(react_row, "exact_match") == 1.0
            if static_correct and react_correct:
                counts["both"] += 1
            elif static_correct:
                counts["static_only"] += 1
            elif react_correct:
                counts["react_only"] += 1
            else:
                counts["neither"] += 1
            question = str(env.reset(idx=int(direct_row["question_idx"])))
            observation, _, _, search_info = env.step(f"Search[{question}]")
            features = extract_router_features(
                question,
                [str(observation)],
                evidence_stats=(search_info or {}).get("evidence_stats") or {},
            )
            examples.append(
                DevelopmentExample(
                    features=features,
                    static_correct=static_correct,
                    react_correct=react_correct,
                    static_cost=_effective_cost(static_row),
                    react_cost=_effective_cost(react_row),
                )
            )
        disagreement[dataset] = counts

    report = train_selective_router(examples)
    router_path.parent.mkdir(parents=True, exist_ok=True)
    report.router.save(router_path)
    summary["router_disagreement"] = disagreement
    summary["router_training"] = report.to_dict()
    observed_selective = [
        row
        for dataset in OBJECTIVE_ROUTER_DATASETS
        for row in runs[dataset]["selective"]
    ]
    observed_exact = [
        value
        for row in observed_selective
        if (value := _score(row, "exact_match")) is not None
    ]
    summary["router_observed_rerun"] = {
        "count": len(observed_selective),
        "exact_accuracy": statistics.mean(observed_exact),
        "cost_per_example_usd": statistics.mean(
            _effective_cost(row) for row in observed_selective
        ),
        "escalation_rate": statistics.mean(
            row.get("route_selected") == "react" for row in observed_selective
        ),
        "note": "Fresh deployable selective rerun; differs from the offline saved-branch simulation used to select the fallback.",
    }

    primary_macro: Dict[str, float] = {}
    primary_cost: Dict[str, float] = {}
    for framework in FRAMEWORKS:
        values = [
            summary["datasets"][dataset][framework]["primary_value"]
            for dataset in PRIMARY_DATASETS
        ]
        primary_macro[framework] = statistics.mean(values)
        primary_cost[framework] = statistics.mean(
            summary["datasets"][dataset][framework]["cost_per_example_usd"]
            for dataset in PRIMARY_DATASETS
        )
    summary["primary_macro"] = primary_macro
    summary["primary_cost_per_example_usd"] = primary_cost

    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "development_summary.json").write_text(
        stable_json_text(summary), encoding="utf-8"
    )
    (artifact_dir / "router_training_report.json").write_text(
        stable_json_text(report.to_dict()), encoding="utf-8"
    )
    _write_quality_cost_figure(summary, figure_dir)
    (artifact_dir / "development_quality_cost_contract.md").write_text(
        """# Development quality-cost figure contract

- **Question:** Which systems lie on the development quality-cost frontier?
- **Takeaway:** Direct and CoT/PoT form the observed frontier; Static Nexus,
  Selective Nexus, and ReAct are dominated at the frozen development point.
- **Form:** Labeled scatter with a dashed empirical frontier.
- **Grain:** Five systems, 150 objectively scored primary-dataset examples per
  system (50 each from FinQA, TAT-QA, and ConvFinQA).
- **Axes:** Unweighted primary macro (%) versus measured US$ per 1,000 examples.
- **Palette:** Blue/gold frontier; orange Selective; neutral dominated methods.
  Marker shape and direct labels duplicate color distinctions.
- **Exports:** `paper/icaif2026/figures/development_quality_cost.{pdf,png}`.
""",
        encoding="utf-8",
    )
    return summary


def _write_quality_cost_figure(summary: Mapping[str, Any], figure_dir: Path) -> None:
    """Export the development Pareto diagnostic in paper-ready dimensions."""

    import matplotlib.pyplot as plt

    labels = {
        "direct": "Direct",
        "cot": "CoT/PoT",
        "nexus": "Static Nexus",
        "react": "ReAct",
        "selective": "Selective",
    }
    styles = {
        "direct": ("#2F6BFF", "o"),
        "cot": ("#B7791F", "o"),
        "nexus": ("#6B7280", "s"),
        "react": ("#9CA3AF", "^"),
        "selective": ("#D97706", "X"),
    }
    offsets = {
        "direct": (4, -12),
        "cot": (-32, 7),
        "nexus": (5, -12),
        "react": (5, -2),
        "selective": (5, 5),
    }
    costs = summary["primary_cost_per_example_usd"]
    quality = summary["primary_macro"]

    fig, ax = plt.subplots(figsize=(3.35, 2.45), dpi=200)
    ax.set_facecolor("white")
    frontier_x = [1000 * costs["direct"], 1000 * costs["cot"]]
    frontier_y = [100 * quality["direct"], 100 * quality["cot"]]
    ax.plot(
        frontier_x,
        frontier_y,
        color="#2F6BFF",
        linewidth=1.0,
        linestyle=(0, (3, 2)),
        zorder=1,
    )
    for framework in ("direct", "cot", "nexus", "selective", "react"):
        color, marker = styles[framework]
        x = 1000 * costs[framework]
        y = 100 * quality[framework]
        ax.scatter(
            [x],
            [y],
            s=34,
            marker=marker,
            facecolor=color if framework != "react" else "white",
            edgecolor="#374151",
            linewidth=0.7,
            zorder=3,
        )
        ax.annotate(
            labels[framework],
            (x, y),
            xytext=offsets[framework],
            textcoords="offset points",
            fontsize=7,
            color="#1F2937",
        )
    ax.text(
        0.02,
        0.04,
        "Dashed line: observed frontier",
        transform=ax.transAxes,
        fontsize=6.2,
        color="#4B5563",
    )
    ax.set_title("Development quality-cost frontier", loc="left", fontsize=8.5, weight="bold")
    ax.set_xlabel("Measured US$ per 1,000 examples", fontsize=7)
    ax.set_ylabel("Primary macro (%)", fontsize=7)
    ax.tick_params(axis="both", labelsize=6.5, length=2.5, color="#6B7280")
    ax.grid(axis="both", color="#E5E7EB", linewidth=0.5, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#6B7280")
    ax.set_xlim(0.25, 1.58)
    ax.set_ylim(27, 46)
    fig.tight_layout(pad=0.5)
    figure_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_dir / "development_quality_cost.pdf", bbox_inches="tight")
    fig.savefig(figure_dir / "development_quality_cost.png", bbox_inches="tight", dpi=300)
    plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("results/finance"))
    parser.add_argument("--model-id", default="google/gemini-2.5-flash")
    parser.add_argument("--results-tag", default="dev-20260709")
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path("paper/icaif2026/artifacts")
    )
    parser.add_argument(
        "--router-path",
        type=Path,
        default=Path("src/agents/finance/protocols/artifacts/selective_router.json"),
    )
    parser.add_argument(
        "--figure-dir", type=Path, default=Path("paper/icaif2026/figures")
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = analyze(
        args.results_root,
        args.model_id,
        args.results_tag,
        args.artifact_dir,
        args.router_path,
        args.figure_dir,
    )
    print(stable_json_text({
        "primary_macro": summary["primary_macro"],
        "router_training": summary["router_training"],
    }))


if __name__ == "__main__":
    main()
