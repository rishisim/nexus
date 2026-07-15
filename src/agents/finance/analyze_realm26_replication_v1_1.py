"""Post-result mechanical correction for the frozen REALM analysis executable.

The frozen plan names FinQA and ConvFinQA's dataset-native binary endpoint
``execution_accuracy``.  ``finance_scoring.ScoreResult.to_dict()`` serializes
that same endpoint as ``exact_match``.  The prospectively frozen v1 executable
looked up the plan label literally and therefore stopped before writing any
analysis artifact.  This wrapper changes only that key lookup; it imports and
reuses the frozen analysis implementation for every computation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from . import analyze_realm26_replication as frozen
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_replication_protocol import DEFAULT_PROTOCOL_PATH


def corrected_metric(row: Mapping[str, Any], name: str) -> float:
    serialized_name = "exact_match" if name == "execution_accuracy" else name
    value = (row.get("native_scores") or {}).get(serialized_name)
    if value is None:
        raise ProtocolError(f"Missing serialized metric {serialized_name!r}")
    return float(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--memo", required=True)
    parser.add_argument("--pre-result-commit", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    frozen._metric = corrected_metric
    analysis = frozen.analyze(
        args.protocol,
        Path(args.results_root).resolve(),
        pre_result_commit=args.pre_result_commit,
    )
    analysis["analysis_implementation_correction"] = {
        "changed_computation": False,
        "corrected_executable": "analyze_realm26_replication_v1_1.py",
        "frozen_executable_failure": (
            "The planned execution_accuracy label was looked up literally, but the "
            "existing scorer serializes that binary endpoint as exact_match."
        ),
        "mapping": {"execution_accuracy": "exact_match"},
        "provider_calls_after_correction": 0,
    }
    analysis.pop("analysis_fingerprint", None)
    analysis["analysis_fingerprint"] = fingerprint(analysis)
    write_stable_json(Path(args.output), analysis)
    memo = frozen.render_memo(analysis)
    memo += """

## Analysis implementation correction

The prospectively frozen v1 analysis executable stopped before producing an
artifact because it treated the planned `execution_accuracy` label as a literal
serialized key. The existing scorer serializes that same FinQA/ConvFinQA binary
endpoint as `exact_match`. Version 1.1 applies only this mechanical alias and
reuses the frozen computations unchanged. No provider call, result, sample,
metric definition, hypothesis, threshold, or stopping rule changed.
"""
    Path(args.memo).parent.mkdir(parents=True, exist_ok=True)
    Path(args.memo).write_text(memo, encoding="utf-8")
    print(
        f"analysis_fingerprint={analysis['analysis_fingerprint']} "
        f"spend_usd={analysis['provider_spend_usd']:.6f} "
        f"transfer={analysis['overall']['transfer_criterion_met']}"
    )


if __name__ == "__main__":
    main()
