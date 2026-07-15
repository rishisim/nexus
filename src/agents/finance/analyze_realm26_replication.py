"""Reproduce the frozen REALM 2026 second-family replication analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Mapping, Optional, Sequence

from .finance_statistics import cost_latency_summary, exact_mcnemar, paired_bootstrap_ci
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_replication_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    FRAMEWORKS,
    load_replication_manifest,
    load_replication_protocol,
)


def _load_rows(root: Path, dataset: str, framework: str):
    path = root / dataset / framework / "results.json"
    if not path.exists():
        raise ProtocolError(f"Missing frozen results: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if len(rows) != 25:
        raise ProtocolError(f"{dataset}/{framework}: expected exactly 25 rows")
    if any(row.get("status") != "success" for row in rows):
        raise ProtocolError(f"{dataset}/{framework}: failed rows prevent frozen analysis")
    return rows


def _metric(row: Mapping[str, Any], name: str) -> float:
    value = (row.get("native_scores") or {}).get(name)
    if value is None:
        raise ProtocolError(f"Missing frozen metric {name!r}")
    return float(value)


def analyze(
    protocol_path: str | Path,
    results_root: Path,
    *,
    pre_result_commit: Optional[str] = None,
) -> Dict[str, Any]:
    protocol = load_replication_protocol(protocol_path)
    manifest = load_replication_manifest(protocol)
    model_id = protocol["inference"]["model_id"]
    bootstrap_seed = int(protocol["analysis"]["bootstrap_seed"])
    n_resamples = int(protocol["analysis"]["bootstrap_resamples"])
    dataset_metrics = protocol["analysis"]["dataset_quality_metrics"]
    result: Dict[str, Any] = {
        "analysis_plan": protocol["analysis"],
        "datasets": {},
        "frameworks": {},
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "model_id": model_id,
        "pre_result_commit": pre_result_commit,
        "protocol_id": protocol["protocol_id"],
        "sample_items": 75,
        "schema_version": "realm26-replication-analysis-v1",
    }
    all_rows = {framework: [] for framework in FRAMEWORKS}
    all_binary = {framework: [] for framework in FRAMEWORKS}
    macro_values = {framework: [] for framework in FRAMEWORKS}

    for dataset in DATASETS:
        rows = {framework: _load_rows(results_root, dataset, framework) for framework in FRAMEWORKS}
        indexed = {
            framework: {str(row["example_id"]): row for row in framework_rows}
            for framework, framework_rows in rows.items()
        }
        expected_ids = [
            str(item["example_id"]) for item in manifest["datasets"][dataset]["examples"]
        ]
        for framework in FRAMEWORKS:
            if set(indexed[framework]) != set(expected_ids):
                raise ProtocolError(f"{dataset}/{framework}: result IDs differ from frozen manifest")
            if any(
                row.get("requested_model") != model_id or row.get("resolved_model") != model_id
                for row in rows[framework]
            ):
                raise ProtocolError(f"{dataset}/{framework}: model binding mismatch")
            all_rows[framework].extend(rows[framework])

        metric_name = dataset_metrics[dataset]
        quality = {
            framework: [_metric(indexed[framework][identifier], metric_name) for identifier in expected_ids]
            for framework in FRAMEWORKS
        }
        binary = {
            framework: [
                _metric(indexed[framework][identifier], "exact_match")
                for identifier in expected_ids
            ]
            for framework in FRAMEWORKS
        }
        for framework in FRAMEWORKS:
            macro_values[framework].append(mean(quality[framework]))
            all_binary[framework].extend(binary[framework])
        result["datasets"][dataset] = {
            "bootstrap_react_minus_nexus": paired_bootstrap_ci(
                quality["nexus"],
                quality["react"],
                n_resamples=n_resamples,
                seed=bootstrap_seed,
            ).to_dict(),
            "complementarity_exact": exact_mcnemar(
                binary["nexus"], binary["react"]
            ).to_dict(),
            "efficiency": {
                framework: cost_latency_summary(rows[framework]) for framework in FRAMEWORKS
            },
            "metric": metric_name,
            "quality": {framework: mean(quality[framework]) for framework in FRAMEWORKS},
        }

    overall_bootstrap = paired_bootstrap_ci(
        [
            _metric(row, dataset_metrics[row["dataset"]])
            for row in all_rows["nexus"]
        ],
        [
            _metric(row, dataset_metrics[row["dataset"]])
            for row in all_rows["react"]
        ],
        n_resamples=n_resamples,
        seed=bootstrap_seed,
    ).to_dict()
    complementarity = exact_mcnemar(all_binary["nexus"], all_binary["react"]).to_dict()
    efficiency = {
        framework: cost_latency_summary(all_rows[framework]) for framework in FRAMEWORKS
    }
    macro = {framework: mean(macro_values[framework]) for framework in FRAMEWORKS}
    transfer_checks = {
        "cost": efficiency["nexus"]["mean_cost_usd"] <= efficiency["react"]["mean_cost_usd"],
        "quality": macro["nexus"] >= macro["react"],
        "unique_successes": complementarity["left_only_correct"]
        >= complementarity["right_only_correct"],
        "workflow_calls": efficiency["nexus"]["mean_llm_calls"]
        < efficiency["react"]["mean_llm_calls"],
    }
    ledger = json.loads((results_root / "spend_ledger.json").read_text(encoding="utf-8"))
    result["frameworks"] = efficiency
    result["overall"] = {
        "bootstrap_react_minus_nexus": overall_bootstrap,
        "complementarity_exact": complementarity,
        "macro_quality": macro,
        "transfer_checks": transfer_checks,
        "transfer_criterion_met": all(transfer_checks.values()),
    }
    result["provider_spend_usd"] = float(ledger["actual_spend_usd"])
    result["resolved_model_ids"] = sorted(
        {row["resolved_model"] for framework in FRAMEWORKS for row in all_rows[framework]}
    )
    result["analysis_fingerprint"] = fingerprint(result)
    return result


def render_memo(analysis: Mapping[str, Any]) -> str:
    macro = analysis["overall"]["macro_quality"]
    comp = analysis["overall"]["complementarity_exact"]
    checks = analysis["overall"]["transfer_checks"]
    criterion = analysis["overall"]["transfer_criterion_met"]
    nexus = analysis["frameworks"]["nexus"]
    react = analysis["frameworks"]["react"]
    conclusion = (
        "The prospectively frozen qualitative transfer criterion was met."
        if criterion
        else "The prospectively frozen qualitative transfer criterion was not met."
    )
    return f"""# REALM 2026 second-family replication memo

This is a prospectively frozen, publicly timestamped replication of the Static
Nexus versus bounded-ReAct branch comparison. It is not a preregistration and
does not tune or reevaluate the failed selector. The prior study remains
prespecified/protocol-locked.

## Frozen design

- Model: `{analysis['model_id']}` through the OpenAI endpoint on OpenRouter,
  with provider fallback disabled, temperature 0, and exact binding checks.
- Sample: 75 new development-evidence items (25 each from FinQA, TAT-QA, and
  ConvFinQA), disjoint from both the older 250-item development sample and the
  sealed 900-item final partition.
- Systems: Static Nexus and seven-step bounded ReAct only.
- Public pre-result commit: `{analysis.get('pre_result_commit') or 'not recorded'}`.
- Total provider spend: USD {analysis['provider_spend_usd']:.6f} under the USD
  15 hard cap.

## Result

Static Nexus macro quality was {macro['nexus']:.4f}; bounded ReAct was
{macro['react']:.4f}. Static-only exact successes numbered
{comp['left_only_correct']}, versus {comp['right_only_correct']} ReAct-only
successes. Static Nexus averaged {nexus['mean_llm_calls']:.3f} calls and USD
{nexus['mean_cost_usd']:.6f} per item; bounded ReAct averaged
{react['mean_llm_calls']:.3f} calls and USD {react['mean_cost_usd']:.6f}.

{conclusion} The four locked checks were: quality={str(checks['quality']).lower()},
unique-success ordering={str(checks['unique_successes']).lower()},
call ordering={str(checks['workflow_calls']).lower()}, and
cost ordering={str(checks['cost']).lower()}.

These 75 examples remain development evidence. They do not unseal or estimate
performance on the 900-example final partition, and they do not support a
universal claim about agentic reasoning.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--memo", required=True)
    parser.add_argument("--pre-result-commit", default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    analysis = analyze(
        args.protocol,
        Path(args.results_root).resolve(),
        pre_result_commit=args.pre_result_commit,
    )
    write_stable_json(Path(args.output), analysis)
    Path(args.memo).parent.mkdir(parents=True, exist_ok=True)
    Path(args.memo).write_text(render_memo(analysis), encoding="utf-8")
    print(
        json.dumps(
            {
                "analysis_fingerprint": analysis["analysis_fingerprint"],
                "provider_spend_usd": analysis["provider_spend_usd"],
                "transfer_criterion_met": analysis["overall"]["transfer_criterion_met"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
