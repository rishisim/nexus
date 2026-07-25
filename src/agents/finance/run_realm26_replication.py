"""Run the prospectively frozen REALM 2026 second-family replication.

The smoke and full run share one immutable result store and one spend ledger.
The smoke executes both frozen workflows on the first frozen item, validates
only binding/telemetry/integrity, and those rows then become the first completed
pairs of the full run.  Outcome metrics are intentionally not printed while the
experiment is in progress.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.shared.llm import llm_with_metadata
from src.shared.llm_telemetry import LLMResult

from . import finance_methods, finance_scoring
from .finance_utils import get_finance_env, set_active_dataset
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_replication_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    FRAMEWORKS,
    load_replication_manifest,
    load_replication_protocol,
    resolve_path,
    validate_manifest_against_sources,
)
from .run_finance_experiments import aggregate_telemetry


RESULT_SCHEMA_VERSION = "realm26-finance-replication-result-v1"
SUCCESS = "success"
PROVIDER_FAILURE = "provider_failure"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


class StopExperiment(ProtocolError):
    """A frozen stop condition fired; no further provider call is permitted."""


class SpendLedger:
    """Persistent fail-closed ledger with a conservative pre-call reservation."""

    def __init__(self, path: Path, protocol_fingerprint: str, cap_usd: float):
        self.path = path
        self.protocol_fingerprint = protocol_fingerprint
        self.cap_usd = float(cap_usd)
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            if self.data.get("protocol_fingerprint") != protocol_fingerprint:
                raise StopExperiment("Spend ledger belongs to a different frozen protocol")
            if float(self.data.get("hard_cap_usd", -1)) != self.cap_usd:
                raise StopExperiment("Spend ledger hard cap differs from the frozen protocol")
        else:
            self.data = {
                "actual_spend_usd": 0.0,
                "calls": [],
                "hard_cap_usd": self.cap_usd,
                "pending_reservations": [],
                "protocol_fingerprint": protocol_fingerprint,
                "schema_version": "realm26-spend-ledger-v1",
            }
            self._write()
        if self.data.get("pending_reservations"):
            raise StopExperiment(
                "Unresolved pre-call reservation found after interruption; fail closed before resume"
            )

    @property
    def actual_spend(self) -> float:
        return float(self.data.get("actual_spend_usd", 0.0))

    def _write(self) -> None:
        write_stable_json(self.path, self.data)

    def reserve(self, *, call_key: str, maximum_cost_usd: float) -> None:
        maximum = float(maximum_cost_usd)
        if maximum <= 0:
            raise StopExperiment("Per-call reservation must be positive")
        if self.actual_spend + maximum > self.cap_usd + 1e-12:
            raise StopExperiment(
                f"USD {self.cap_usd:.2f} hard cap would be exceeded by the next call"
            )
        self.data["pending_reservations"].append(
            {"call_key": call_key, "maximum_cost_usd": maximum, "reserved_at": utc_now()}
        )
        self._write()

    def complete(
        self,
        *,
        call_key: str,
        actual_cost_usd: Optional[float],
        status: str,
        requested_model: str,
        resolved_model: str,
        reservation_fallback: bool = False,
    ) -> None:
        pending = self.data.get("pending_reservations") or []
        matches = [item for item in pending if item.get("call_key") == call_key]
        if len(matches) != 1:
            raise StopExperiment("Spend ledger reservation identity mismatch")
        reservation = float(matches[0]["maximum_cost_usd"])
        charge = reservation if actual_cost_usd is None else float(actual_cost_usd)
        if charge < 0 or charge > reservation + 1e-9:
            raise StopExperiment("Provider charge exceeded the conservative frozen reservation")
        new_total = self.actual_spend + charge
        if new_total > self.cap_usd + 1e-12:
            raise StopExperiment("Provider spend breached the USD 15 hard cap")
        self.data["pending_reservations"] = [
            item for item in pending if item.get("call_key") != call_key
        ]
        self.data["actual_spend_usd"] = new_total
        self.data["calls"].append(
            {
                "actual_cost_usd": charge,
                "call_key": call_key,
                "completed_at": utc_now(),
                "requested_model": requested_model,
                "reservation_fallback": bool(reservation_fallback or actual_cost_usd is None),
                "reserved_maximum_cost_usd": reservation,
                "resolved_model": resolved_model,
                "status": status,
            }
        )
        self._write()


class BudgetedModel:
    """Injected LLM callable enforcing model binding and cap per logical call."""

    def __init__(
        self,
        protocol: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        ledger: SpendLedger,
        pair_key: str,
    ):
        self.protocol = protocol
        self.snapshot = snapshot
        self.ledger = ledger
        self.pair_key = pair_key
        self.call_index = 0
        endpoint = snapshot["endpoint"]
        self.input_rate = float(endpoint["pricing"]["prompt"])
        self.output_rate = float(endpoint["pricing"]["completion"])
        self.multiplier = float(protocol["budget"]["reservation_multiplier"])

    def _estimate(self, result: LLMResult) -> float:
        cached = min(result.cached_tokens, result.input_tokens)
        cache_rate = float(
            self.snapshot["endpoint"]["pricing"].get("input_cache_read", self.input_rate)
        )
        return (
            (result.input_tokens - cached) * self.input_rate
            + cached * cache_rate
            + result.output_tokens * self.output_rate
        )

    def __call__(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        num_traces: int = 1,
        max_tokens: int = 512,
        model_id: Optional[str] = None,
        return_metadata: bool = True,
        **_: Any,
    ) -> LLMResult:
        inference = self.protocol["inference"]
        expected_model = str(inference["model_id"])
        if model_id != expected_model:
            raise StopExperiment(f"Requested model {model_id!r} differs from frozen binding")
        if temperature not in (None, 0, 0.0) or num_traces != 1:
            raise StopExperiment("Sampling configuration differs from the frozen protocol")
        self.call_index += 1
        call_key = f"{self.pair_key}/call-{self.call_index}"
        # UTF-8 bytes are a conservative upper bound on text tokens for this
        # endpoint; max_tokens is an API-enforced output ceiling.
        maximum = (
            len(str(prompt).encode("utf-8")) * self.input_rate
            + int(max_tokens) * self.output_rate
        ) * self.multiplier
        self.ledger.reserve(call_key=call_key, maximum_cost_usd=maximum)
        result = llm_with_metadata(
            str(prompt),
            stop=[] if stop is None else stop,
            temperature=float(inference["temperature"]),
            num_traces=1,
            max_tokens=int(max_tokens),
            model_id=expected_model,
            backend=str(inference["backend"]),
            max_retries=int(self.protocol["retry_policy"]["max_attempts_per_call"]),
        )
        estimated = self._estimate(result)
        if result.estimated_cost_usd is None:
            result = replace(result, estimated_cost_usd=estimated)
        actual = result.provider_cost_usd
        if actual is None and result.total_tokens > 0:
            actual = estimated
        self.ledger.complete(
            call_key=call_key,
            actual_cost_usd=actual,
            status=result.status,
            requested_model=result.requested_model,
            resolved_model=result.resolved_model,
        )
        if result.requested_model != expected_model:
            raise StopExperiment("Provider telemetry changed the requested model binding")
        if result.resolved_model != expected_model:
            raise StopExperiment(
                f"Resolved model {result.resolved_model!r} differs from frozen binding"
            )
        return result


class LeakageGuardEnv:
    """Runtime contract guard: target metadata may appear only after Finish."""

    FORBIDDEN_UNFINISHED_KEYS = {
        "answer_from",
        "gold_scale",
        "gt_answer",
        "question_type",
        "scale",
    }

    def __init__(self, env: Any):
        self._env = env

    def __getattr__(self, name: str) -> Any:
        return getattr(self._env, name)

    def reset(self, idx: int) -> str:
        return self._env.reset(idx=idx)

    def step(self, action: str):
        output = self._env.step(action)
        observation, reward, done, info = output
        if not done:
            leaked = self.FORBIDDEN_UNFINISHED_KEYS & set(info or {})
            if leaked:
                raise StopExperiment(f"Runtime target-metadata leakage detected: {sorted(leaked)}")
        return observation, reward, done, info


class ReplicationRunner:
    def __init__(
        self,
        protocol_path: str | Path = DEFAULT_PROTOCOL_PATH,
        *,
        results_root: Optional[str | Path] = None,
        env_factory=None,
        llm_factory=BudgetedModel,
    ):
        self.protocol = load_replication_protocol(protocol_path)
        self.protocol_path = Path(self.protocol["_path"])
        self.manifest = load_replication_manifest(self.protocol)
        self.env_factory = env_factory or get_finance_env
        validate_manifest_against_sources(self.protocol, self.manifest, self.env_factory)
        snapshot_path = resolve_path(self.protocol_path, str(self.protocol["model_snapshot"]))
        self.snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        configured_root = results_root or self.protocol["results"]["root"]
        root = Path(configured_root)
        if not root.is_absolute():
            root = (self.protocol_path.parents[4] / root).resolve()
        self.results_root = root
        self.results_root.mkdir(parents=True, exist_ok=True)
        protocol_body = {key: value for key, value in self.protocol.items() if key != "_path"}
        self.protocol_fingerprint = fingerprint(protocol_body)
        self.config_path = self.results_root / "config.json"
        self.smoke_path = self.results_root / "smoke_complete.json"
        self.run_history_path = self.results_root / "run_history.json"
        self._write_or_validate_config()
        self.ledger = SpendLedger(
            self.results_root / "spend_ledger.json",
            self.protocol_fingerprint,
            float(self.protocol["budget"]["hard_cap_usd"]),
        )
        self.llm_factory = llm_factory

    def _frozen_config(self) -> Dict[str, Any]:
        return {
            "frameworks": list(FRAMEWORKS),
            "manifest_fingerprint": self.manifest["manifest_fingerprint"],
            "model_id": self.protocol["inference"]["model_id"],
            "protocol_fingerprint": self.protocol_fingerprint,
            "protocol_id": self.protocol["protocol_id"],
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "sample_count": sum(
                len(self.manifest["datasets"][dataset]["examples"]) for dataset in DATASETS
            ),
            "seed": self.protocol["seed"],
        }

    def _write_or_validate_config(self) -> None:
        expected = self._frozen_config()
        if self.config_path.exists():
            existing = json.loads(self.config_path.read_text(encoding="utf-8"))
            if existing != expected:
                raise StopExperiment("Resume configuration differs from the frozen run")
        else:
            write_stable_json(self.config_path, expected)

    def _result_path(self, dataset_id: str, framework: str) -> Path:
        return self.results_root / dataset_id / framework / "results.json"

    def _load_results(self, dataset_id: str, framework: str) -> List[Dict[str, Any]]:
        path = self._result_path(dataset_id, framework)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise StopExperiment(f"Malformed result file: {path}")
        ids = [str(row.get("example_id")) for row in payload]
        if len(ids) != len(set(ids)):
            raise StopExperiment(f"Duplicate immutable result pairs in {path}")
        return payload

    def _save_result(self, dataset_id: str, framework: str, row: Dict[str, Any]) -> None:
        path = self._result_path(dataset_id, framework)
        saved = self._load_results(dataset_id, framework)
        if any(str(item["example_id"]) == str(row["example_id"]) for item in saved):
            raise StopExperiment("Attempted to overwrite an immutable completed pair")
        saved.append(row)
        selected_order = {
            str(item["example_id"]): ordinal
            for ordinal, item in enumerate(self.manifest["datasets"][dataset_id]["examples"])
        }
        saved.sort(key=lambda item: selected_order[str(item["example_id"])])
        write_stable_json(path, saved)

    def _pairs(self, phase: str) -> List[Tuple[str, Mapping[str, Any], str]]:
        if phase == "smoke":
            spec = self.protocol["smoke"]
            dataset_id = str(spec["dataset"])
            example = self.manifest["datasets"][dataset_id]["examples"][int(spec["item_ordinal"])]
            return [(dataset_id, example, framework) for framework in FRAMEWORKS]
        return [
            (dataset_id, example, framework)
            for dataset_id in DATASETS
            for example in self.manifest["datasets"][dataset_id]["examples"]
            for framework in FRAMEWORKS
        ]

    def _pending_pairs(self, phase: str) -> List[Tuple[str, Mapping[str, Any], str]]:
        pending = []
        for dataset_id, example, framework in self._pairs(phase):
            existing = self._load_results(dataset_id, framework)
            if not any(str(row["example_id"]) == str(example["example_id"]) for row in existing):
                pending.append((dataset_id, example, framework))
        return pending

    def _success_row(
        self,
        dataset_id: str,
        example: Mapping[str, Any],
        framework: str,
        method_result: Mapping[str, Any],
    ) -> Dict[str, Any]:
        telemetry = aggregate_telemetry(method_result, self.protocol["inference"]["model_id"])
        calls = telemetry["call_records"]
        expected = self.protocol["inference"]["model_id"]
        if not calls:
            raise StopExperiment("Successful pair lacks per-call telemetry")
        for call in calls:
            if call.get("requested_model") != expected or call.get("resolved_model") != expected:
                raise StopExperiment("Saved call telemetry violates the frozen model binding")
            if call.get("status") != "ok":
                raise StopExperiment("Successful pair contains a failed model call")
        if telemetry["total_tokens"] <= 0 or telemetry["latency_ms"] <= 0:
            raise StopExperiment("Successful pair has incomplete token/latency telemetry")
        ground_truth = method_result.get("gt_answer", method_result.get("ground_truth"))
        score = finance_scoring.score_dataset(
            dataset_id,
            method_result.get("answer", ""),
            ground_truth,
            gold_scale=method_result.get("gold_scale", method_result.get("scale", "")),
            question_type=method_result.get("question_type", ""),
        ).to_dict()
        trace = str(method_result.get("raw_trace", method_result.get("trace", "")))
        provider_cost = telemetry["provider_cost_usd"]
        estimated_cost = telemetry["estimated_cost_usd"]
        return {
            "answer": method_result.get("answer", ""),
            "backend": telemetry["backend"],
            "cached_tokens": telemetry["cached_tokens"],
            "call_records": calls,
            "dataset": dataset_id,
            "effective_cost_usd": provider_cost if provider_cost else estimated_cost,
            "estimated_cost_usd": estimated_cost,
            "evidence_hash": method_result.get("evidence_hash"),
            "example_id": str(example["example_id"]),
            "framework": framework,
            "ground_truth": ground_truth,
            "input_tokens": telemetry["input_tokens"],
            "item_hash": example["item_hash"],
            "latency_ms": telemetry["latency_ms"],
            "llm_attempt_count": telemetry["llm_attempt_count"],
            "llm_call_count": telemetry["llm_call_count"],
            "native_scores": score,
            "output_tokens": telemetry["output_tokens"],
            "prompt_hash": method_result.get("prompt_hash"),
            "protocol_id": self.protocol["protocol_id"],
            "provider_cost_usd": provider_cost,
            "question_idx": int(example["index"]),
            "raw_trace": trace,
            "reasoning_tokens": telemetry["reasoning_tokens"],
            "requested_model": expected,
            "resolved_model": telemetry["resolved_model"],
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "retrieval_operation_count": int(method_result.get("retrieval_calls", 0)),
            "retry_count": telemetry["retry_count"],
            "status": SUCCESS,
            "total_tokens": telemetry["total_tokens"],
            "trace_hash": "sha256:" + hashlib.sha256(trace.encode("utf-8")).hexdigest(),
        }

    def _failure_row(
        self,
        dataset_id: str,
        example: Mapping[str, Any],
        framework: str,
        exc: BaseException,
    ) -> Dict[str, Any]:
        metadata = dict(getattr(exc, "metadata", {}) or {})
        return {
            "dataset": dataset_id,
            "error": str(exc)[:500],
            "error_type": type(exc).__name__,
            "example_id": str(example["example_id"]),
            "framework": framework,
            "item_hash": example["item_hash"],
            "protocol_id": self.protocol["protocol_id"],
            "question_idx": int(example["index"]),
            "requested_model": self.protocol["inference"]["model_id"],
            "resolved_model": metadata.get("resolved_model"),
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "status": PROVIDER_FAILURE,
        }

    def _run_pair(self, dataset_id: str, example: Mapping[str, Any], framework: str) -> Dict[str, Any]:
        set_active_dataset(dataset_id)
        env = LeakageGuardEnv(self.env_factory(dataset_id))
        pair_key = f"{dataset_id}/{example['example_id']}/{framework}"
        model = self.llm_factory(self.protocol, self.snapshot, self.ledger, pair_key)
        method = finance_methods.FRAMEWORKS[framework]
        _, result = method(
            idx=int(example["index"]),
            model_id=self.protocol["inference"]["model_id"],
            to_print=False,
            env=env,
            llm_func=model,
            evidence_token_budget=int(self.protocol["workflows"]["evidence_token_budget"]),
            **(
                {"max_steps": int(self.protocol["workflows"]["react_max_steps"])}
                if framework == "react"
                else {}
            ),
        )
        return self._success_row(dataset_id, example, framework, result)

    def _append_history(self, phase: str, attempted: int, successes: int, failures: int) -> None:
        history = []
        if self.run_history_path.exists():
            history = json.loads(self.run_history_path.read_text(encoding="utf-8"))
        history.append(
            {
                "attempted_pairs": attempted,
                "failures": failures,
                "finished_at": utc_now(),
                "phase": phase,
                "spend_usd": self.ledger.actual_spend,
                "successes": successes,
            }
        )
        write_stable_json(self.run_history_path, history)

    def run(self, phase: str) -> None:
        if phase not in {"smoke", "full"}:
            raise ValueError("phase must be smoke or full")
        if phase == "full" and not self.smoke_path.exists():
            raise StopExperiment("Full run requires the frozen one-item binding/telemetry smoke")
        if phase == "smoke" and self.smoke_path.exists():
            print("[COMPLETE] Frozen smoke already validated; no provider calls made.")
            return
        pending = self._pending_pairs(phase)
        if not pending:
            if phase == "full":
                print("[COMPLETE] No pending frozen pairs; no provider calls made.")
                return
            raise StopExperiment("Smoke rows exist without a validated smoke marker")

        consecutive_failures = 0
        successes = failures = attempted = 0
        for ordinal, (dataset_id, example, framework) in enumerate(pending, 1):
            print(
                f"[{ordinal}/{len(pending)}] {dataset_id}/{example['example_id']}/{framework}",
                flush=True,
            )
            attempted += 1
            try:
                row = self._run_pair(dataset_id, example, framework)
            except StopExperiment:
                self._append_history(phase, attempted - 1, successes, failures)
                raise
            except Exception as exc:
                row = self._failure_row(dataset_id, example, framework, exc)
                failures += 1
                consecutive_failures += 1
            else:
                successes += 1
                consecutive_failures = 0
            self._save_result(dataset_id, framework, row)
            if consecutive_failures >= int(
                self.protocol["stopping_rule"]["consecutive_provider_failures"]
            ):
                self._append_history(phase, attempted, successes, failures)
                raise StopExperiment("Repeated provider failure stopping rule fired")

        self._append_history(phase, attempted, successes, failures)
        if failures:
            raise StopExperiment("Phase completed with a provider failure; frozen plan forbids repair")
        if phase == "smoke":
            smoke_rows = self._pairs("smoke")
            write_stable_json(
                self.smoke_path,
                {
                    "binding": self.protocol["inference"]["model_id"],
                    "completed_at": utc_now(),
                    "pair_count": len(smoke_rows),
                    "protocol_fingerprint": self.protocol_fingerprint,
                    "spend_usd": self.ledger.actual_spend,
                    "telemetry_complete": True,
                },
            )
            print(
                f"[SMOKE PASS] binding and telemetry validated; cumulative spend "
                f"USD {self.ledger.actual_spend:.6f}. Outcomes were not summarized."
            )
        else:
            print(
                f"[RUN COMPLETE] all frozen pairs persisted; cumulative spend "
                f"USD {self.ledger.actual_spend:.6f}."
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--phase", required=True, choices=("smoke", "full"))
    parser.add_argument(
        "--dotenv",
        default=None,
        help="Optional credential file outside the worktree; values are never persisted",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.dotenv:
        from dotenv import load_dotenv

        load_dotenv(args.dotenv, override=False)
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is unavailable; no provider calls made")
    runner = ReplicationRunner(args.protocol)
    runner.run(args.phase)


if __name__ == "__main__":
    main()
