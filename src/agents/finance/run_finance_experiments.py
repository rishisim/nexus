"""Protocol-driven runner for controlled-evidence financial QA experiments.

The v2 runner treats a ``(dataset, example_id, framework)`` result as the
atomic resume unit.  Valid model outputs are immutable; only typed
infrastructure failures may be retried, and only when explicitly requested.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:  # Package import during tests; script import for historical CLI usage.
    from .dataset_catalog import get_dataset
    from .protocol_v2 import (
        DATASETS,
        ProtocolError,
        fingerprint,
        load_manifest,
        load_protocol,
        write_stable_json,
    )
except ImportError:  # pragma: no cover - exercised by direct CLI invocation
    from dataset_catalog import get_dataset
    from protocol_v2 import (
        DATASETS,
        ProtocolError,
        fingerprint,
        load_manifest,
        load_protocol,
        write_stable_json,
    )


RESULT_SCHEMA_VERSION = "finance-result-v2"
FRAMEWORK_CHOICES = ("direct", "cot", "react", "nexus", "selective")
REQUIRED_FREEZE_HASHES = ("prompts", "scorers", "router", "price_snapshot", "manifests")
SUCCESS = "success"
INFRASTRUCTURE_FAILURE = "infrastructure_failure"
MODEL_FAILURE = "model_failure"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _import_finance_module(name: str):
    package = __package__
    if package:
        try:
            return importlib.import_module(f".{name}", package)
        except ImportError:
            pass
    return importlib.import_module(name)


def default_environment_factory(dataset_id: str):
    return _import_finance_module("finance_utils").get_finance_env(dataset_id)


def default_dataset_setter(dataset_id: str) -> None:
    _import_finance_module("finance_utils").set_active_dataset(dataset_id)


def default_framework_registry() -> Dict[str, Callable[..., Any]]:
    """Load the method layer late so runner tests never import provider clients."""
    registry: Dict[str, Callable[..., Any]] = {}
    try:
        module = _import_finance_module("finance_methods")
    except ImportError:
        module = None
    if module is not None:
        supplied = getattr(module, "FRAMEWORKS", None)
        if isinstance(supplied, Mapping):
            registry.update(supplied)
        for framework in FRAMEWORK_CHOICES:
            function = getattr(module, f"run_{framework}", None)
            if callable(function):
                registry[framework] = function

    # Narrow compatibility fallback while finance_methods is being integrated.
    if "react" not in registry:
        try:
            registry["react"] = _import_finance_module("react_agent").run_react
        except (ImportError, AttributeError):
            pass
    if "nexus" not in registry:
        try:
            registry["nexus"] = _import_finance_module("nexus_wrapper").run_nexus
        except (ImportError, AttributeError):
            pass
    return registry


def callable_accepts_model_id(method: Callable[..., Any]) -> bool:
    signature = inspect.signature(method)
    parameter = signature.parameters.get("model_id")
    if parameter and parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    ):
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())


def classify_exception(exc: BaseException) -> str:
    """Honor typed status, then conservatively recognize raw transport errors."""
    metadata = failed_call_metadata(exc)
    status = metadata.get("status")
    if status:
        return INFRASTRUCTURE_FAILURE if status == "infrastructure_error" else MODEL_FAILURE
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code in {408, 409, 429} or isinstance(status_code, int) and status_code >= 500:
        return INFRASTRUCTURE_FAILURE
    if isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError)):
        return INFRASTRUCTURE_FAILURE
    return MODEL_FAILURE


def failed_call_metadata(exc: BaseException) -> Dict[str, Any]:
    """Extract the LLMResult-shaped metadata carried by method-layer errors."""
    metadata = getattr(exc, "llm_metadata", None) or getattr(exc, "metadata", None)
    if not isinstance(metadata, Mapping) and hasattr(exc, "to_dict"):
        serialized = exc.to_dict()
        if isinstance(serialized, Mapping):
            metadata = serialized.get("llm_metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    result = dict(metadata)
    status = result.get("status") or getattr(exc, "status", None)
    if status:
        result["status"] = str(status)
    return result


def _number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _call_dict(call: Any) -> Dict[str, Any]:
    if hasattr(call, "to_dict"):
        call = call.to_dict()
    if isinstance(call, Mapping):
        return dict(call)
    return {}


def collect_call_records(method_result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Normalize telemetry emitted either as one call, a list, or nested metadata."""
    candidates: Any = None
    for key in ("call_records", "llm_telemetry", "llm_results", "llm_calls"):
        if method_result.get(key) is not None:
            candidates = method_result[key]
            break
    telemetry = method_result.get("telemetry")
    if candidates is None and isinstance(telemetry, Mapping):
        candidates = telemetry.get("call_records") or telemetry.get("calls")
        if candidates is None and ("input_tokens" in telemetry or "total_tokens" in telemetry):
            candidates = telemetry
    if candidates is None:
        return []
    if not isinstance(candidates, (list, tuple)):
        candidates = [candidates]
    normalized = [_call_dict(call) for call in candidates]
    return [call for call in normalized if call]


def aggregate_telemetry(method_result: Mapping[str, Any], requested_model: str) -> Dict[str, Any]:
    calls = collect_call_records(method_result)
    additive_ints = (
        "input_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "output_tokens",
        "total_tokens",
        "retry_count",
    )
    additive_floats = ("latency_ms", "provider_cost_usd", "estimated_cost_usd")
    aggregate: Dict[str, Any] = {key: sum(_integer(c.get(key)) for c in calls) for key in additive_ints}
    aggregate.update({key: sum(_number(c.get(key)) for c in calls) for key in additive_floats})
    resolved = [str(c.get("resolved_model")) for c in calls if c.get("resolved_model")]
    backends = [str(c.get("backend")) for c in calls if c.get("backend")]
    aggregate["resolved_model"] = resolved[-1] if resolved else str(
        method_result.get("resolved_model") or requested_model
    )
    aggregate["backend"] = backends[-1] if backends else method_result.get("backend")
    aggregate["call_records"] = calls
    aggregate["llm_call_count"] = len(calls) if calls else _integer(
        method_result.get("llm_call_count", method_result.get("n_calls", 0))
    )
    aggregate["llm_attempt_count"] = sum(
        _integer(call.get("retry_count"), 0) + 1 for call in calls
    ) if calls else _integer(method_result.get("llm_attempt_count", aggregate["llm_call_count"]))
    # Some methods aggregate telemetry themselves. Use those totals only when
    # no individual call records are available to avoid double-counting.
    if not calls:
        telemetry = method_result.get("telemetry")
        sources = [telemetry, method_result] if isinstance(telemetry, Mapping) else [method_result]
        for key in additive_ints:
            aggregate[key] = next((_integer(source.get(key)) for source in sources if source.get(key) is not None), 0)
        for key in additive_floats:
            aggregate[key] = next((_number(source.get(key)) for source in sources if source.get(key) is not None), 0.0)
    return aggregate


def default_model_snapshotter(model_ids: Sequence[str]) -> Dict[str, Any]:
    """Fetch OpenRouter's catalog once and fail closed on absent model IDs."""
    from src.shared.llm import fetch_openrouter_model_snapshot

    return fetch_openrouter_model_snapshot(model_ids, timeout=30.0)


class FinanceExperimentRunner:
    def __init__(
        self,
        dataset_id: str = "financebench",
        model_id: Optional[str] = None,
        model: Optional[str] = None,
        num_examples: Optional[int] = None,
        frameworks: Optional[List[str]] = None,
        results_base_dir: str | Path = "../../../results/finance",
        results_tag: Optional[str] = None,
        seed: Optional[int] = None,
        protocol: str | Path | Mapping[str, Any] | None = None,
        partition: str = "final",
        resume: bool = False,
        retry_infrastructure_failures: bool = False,
        retry_failed: bool = False,
        method_registry: Optional[Mapping[str, Callable[..., Any]]] = None,
        env_factory: Optional[Callable[[str], Any]] = None,
        dataset_setter: Optional[Callable[[str], None]] = None,
        model_snapshotter: Optional[Callable[[Sequence[str]], Dict[str, Any]]] = None,
    ):
        self.protocol = load_protocol(protocol)
        self.protocol_id = str(self.protocol["protocol_id"])
        if dataset_id not in self.protocol["datasets"]:
            raise ProtocolError(f"Dataset {dataset_id!r} is not in protocol {self.protocol_id}")
        if partition not in {"development", "smoke", "final"}:
            raise ProtocolError("partition must be 'development', 'smoke', or 'final'")
        self.dataset_id = dataset_id
        self.dataset = get_dataset(dataset_id)
        configured_model = self.protocol["inference"]["primary"]["model_id"]
        self.model_id = str(model_id or model or configured_model)
        self.num_examples = num_examples
        self.frameworks = frameworks or list(self.protocol["frameworks"])
        invalid = sorted(set(self.frameworks) - set(FRAMEWORK_CHOICES))
        if invalid:
            raise ProtocolError(f"Unsupported frameworks: {invalid}")
        self.results_tag = results_tag
        protocol_seed = int(self.protocol["seed"])
        if seed is not None and int(seed) != protocol_seed:
            raise ProtocolError(
                f"Frozen manifest seed is {protocol_seed}; refusing seed override {seed}"
            )
        self.seed = protocol_seed
        self.partition = partition
        self.resume = resume
        self.retry_infrastructure_failures = retry_infrastructure_failures or retry_failed
        self.env_factory = env_factory or default_environment_factory
        self.dataset_setter = dataset_setter or default_dataset_setter
        self._registry_was_injected = method_registry is not None
        self._method_registry = dict(method_registry) if method_registry is not None else None
        self.model_snapshotter = model_snapshotter or default_model_snapshotter
        self.manifest = load_manifest(self.protocol, dataset_id)

        root = Path(results_base_dir)
        if not root.is_absolute():
            root = (SCRIPT_DIR / root).resolve()
        model_slug = self.model_id.replace("/", "-").replace(":", "-")
        run_name = f"{self.protocol_id}_{partition}_{model_slug}"
        if results_tag:
            run_name += f"_{results_tag}"
        self.run_id = run_name
        self.results_dir = root / dataset_id / run_name
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.results_dir / "config.json"
        self.model_snapshot_path = self.results_dir / "model_snapshot.json"
        self.run_history_path = self.results_dir / "run_history.json"
        self.summary_path = self.results_dir / "summary.json"
        self.results: Dict[str, List[Dict[str, Any]]] = {
            framework: self._load_framework_results(framework) for framework in self.frameworks
        }

    @property
    def method_registry(self) -> Dict[str, Callable[..., Any]]:
        if self._method_registry is None:
            self._method_registry = default_framework_registry()
        return self._method_registry

    def _result_path(self, framework: str) -> Path:
        return self.results_dir / framework / "results.json"

    def _load_framework_results(self, framework: str) -> List[Dict[str, Any]]:
        path = self._result_path(framework)
        legacy = self.results_dir / f"{framework}.json"
        if not path.exists() and legacy.exists():
            path = legacy
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ProtocolError(f"Expected a result list in {path}")
        return payload

    def selected_examples(self) -> List[Dict[str, Any]]:
        manifest_partition = "development" if self.partition == "smoke" else self.partition
        examples = list(self.manifest[manifest_partition]["examples"])
        if self.num_examples is not None:
            if self.num_examples < 0:
                raise ProtocolError("num_examples cannot be negative")
            examples = examples[: self.num_examples]
        return examples

    def _existing_by_id(self, framework: str) -> Dict[str, Dict[str, Any]]:
        rows: Dict[str, Dict[str, Any]] = {}
        for result in self.results[framework]:
            identifier = str(result.get("example_id", result.get("question_idx", "")))
            if identifier in rows:
                raise ProtocolError(f"Duplicate saved pair: {framework}/{identifier}")
            rows[identifier] = result
        return rows

    def _pending(self, framework: str, example: Mapping[str, Any]) -> bool:
        identifier = str(example["example_id"])
        existing = self._existing_by_id(framework).get(identifier)
        if existing is None:
            return True
        if not self.resume:
            raise ProtocolError(
                f"Result already exists for {framework}/{identifier}; use --resume to continue safely"
            )
        return bool(
            self.retry_infrastructure_failures
            and existing.get("status") == INFRASTRUCTURE_FAILURE
        )

    def pending_pairs(self) -> List[tuple[Dict[str, Any], str]]:
        return [
            (example, framework)
            for example in self.selected_examples()
            for framework in self.frameworks
            if self._pending(framework, example)
        ]

    def _validate_methods(self, pairs: Iterable[tuple[Mapping[str, Any], str]]) -> None:
        required = sorted({framework for _, framework in pairs})
        for framework in required:
            method = self.method_registry.get(framework)
            if not callable(method):
                raise ProtocolError(f"No callable registered for framework {framework!r}")
            if not callable_accepts_model_id(method):
                raise ProtocolError(
                    f"{framework} callable must accept model_id; refusing a label-only model override"
                )

    def _write_config(self) -> None:
        protocol_body = {key: value for key, value in self.protocol.items() if key != "_path"}
        write_stable_json(
            self.config_path,
            {
                "created_or_updated": utc_now(),
                "dataset": self.dataset_id,
                "dataset_fingerprint": self.manifest["dataset_fingerprint"],
                "frameworks": self.frameworks,
                "manifest_fingerprint": self.manifest["manifest_fingerprint"],
                "model_id": self.model_id,
                "num_examples": self.num_examples,
                "partition": self.partition,
                "protocol_fingerprint": fingerprint(protocol_body),
                "protocol_id": self.protocol_id,
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "results_tag": self.results_tag,
                "retry_infrastructure_failures": self.retry_infrastructure_failures,
                "run_id": self.run_id,
                "seed": self.seed,
            },
        )

    def _validate_final_freeze(self) -> None:
        if self.partition != "final":
            return
        if self.protocol.get("freeze_state") != "frozen":
            raise ProtocolError("Final evaluation requires protocol freeze_state='frozen'")
        hashes = self.protocol.get("artifact_hashes") or {}
        missing = [name for name in REQUIRED_FREEZE_HASHES if not hashes.get(name)]
        if missing:
            raise ProtocolError(f"Final evaluation requires frozen artifact hashes: {missing}")
        manifest_hashes = hashes["manifests"]
        if not isinstance(manifest_hashes, Mapping):
            raise ProtocolError("artifact_hashes.manifests must map dataset IDs to fingerprints")
        expected = manifest_hashes.get(self.dataset_id)
        actual = self.manifest["manifest_fingerprint"]
        if expected != actual:
            raise ProtocolError(
                f"{self.dataset_id}: frozen manifest hash mismatch ({actual} != {expected})"
            )

    def _verify_dataset_revision(self) -> None:
        env = self.env_factory(self.dataset_id)
        rows = getattr(env, "rows", None)
        if rows is None:
            raise ProtocolError(f"{self.dataset_id}: environment does not expose adapter rows")
        actual = fingerprint(list(rows))
        expected = self.manifest["dataset_fingerprint"]
        if actual != expected:
            raise ProtocolError(
                f"{self.dataset_id}: adapter content differs from frozen manifest "
                f"({actual} != {expected}); regenerate before freezing, never during a final run"
            )

    def prepare(self) -> List[Dict[str, Any]]:
        self._validate_final_freeze()
        self._verify_dataset_revision()
        self._write_config()
        self.write_summary()
        return self.selected_examples()

    def _snapshot_models(self) -> None:
        if self.model_snapshot_path.exists():
            snapshot = json.loads(self.model_snapshot_path.read_text(encoding="utf-8"))
        else:
            snapshot = self.model_snapshotter([self.model_id])
            write_stable_json(self.model_snapshot_path, snapshot)
        missing = list(snapshot.get("missing_model_ids") or [])
        if self.model_id not in snapshot.get("models", {}) and self.model_id not in missing:
            missing.append(self.model_id)
        if missing:
            raise ProtocolError(f"Configured model IDs absent from OpenRouter catalog: {sorted(missing)}")

    def _configure_selective_router(self, pairs: Sequence[tuple[Mapping[str, Any], str]]) -> None:
        if self._registry_was_injected or not any(framework == "selective" for _, framework in pairs):
            return
        router_spec = self.protocol.get("router") or {}
        configured = router_spec.get("path")
        if not configured:
            raise ProtocolError(
                "Selective framework requires protocol.router.path after development fitting"
            )
        protocol_path = Path(self.protocol.get("_path", ""))
        router_path = Path(configured)
        if not router_path.is_absolute():
            router_path = protocol_path.parent / router_path
        if not router_path.is_file():
            raise ProtocolError(f"Frozen selective router not found: {router_path}")
        digest = "sha256:" + hashlib.sha256(router_path.read_bytes()).hexdigest()
        expected = router_spec.get("sha256") or self.protocol.get("artifact_hashes", {}).get("router")
        if expected and expected != digest:
            raise ProtocolError(f"Frozen selective router hash mismatch: {digest} != {expected}")
        methods = _import_finance_module("finance_methods")
        router_module = _import_finance_module("selective_router")
        methods.configure_selective_router(router_module.SelectiveRouter.load(router_path))

    def _invoke(self, framework: str, idx: int) -> Mapping[str, Any]:
        output = self.method_registry[framework](idx=idx, model_id=self.model_id, to_print=False)
        if isinstance(output, tuple) and len(output) == 2:
            output = output[1]
        if not isinstance(output, Mapping):
            raise TypeError(f"{framework} returned {type(output).__name__}, expected result mapping")
        return output

    def _success_record(
        self, framework: str, example: Mapping[str, Any], method_result: Mapping[str, Any]
    ) -> Dict[str, Any]:
        telemetry = aggregate_telemetry(method_result, self.model_id)
        llm_status = method_result.get("llm_status")
        model_failed = llm_status not in (None, "ok", "success")
        ground_truth = method_result.get("gt_answer", method_result.get("ground_truth"))
        native_scores: Mapping[str, Any] = {}
        if not model_failed and self.dataset_id != "finder":
            scoring = _import_finance_module("finance_scoring")
            score = scoring.score_dataset(
                self.dataset_id,
                method_result.get("answer", ""),
                ground_truth,
                gold_scale=method_result.get("gold_scale", method_result.get("scale", "")),
                question_type=method_result.get("question_type", ""),
            )
            native_scores = score.to_dict()
        record = {
            "answer": method_result.get("answer", ""),
            "backend": telemetry["backend"],
            "cached_tokens": telemetry["cached_tokens"],
            "call_records": telemetry["call_records"],
            "dataset": self.dataset_id,
            "error": "One or more model calls did not produce a valid response" if model_failed else None,
            "error_type": "ModelOutputFailure" if model_failed else None,
            "estimated_cost_usd": telemetry["estimated_cost_usd"],
            "evidence_hash": method_result.get("evidence_hash"),
            "example_id": str(example["example_id"]),
            "framework": framework,
            "ground_truth": ground_truth,
            "input_tokens": telemetry["input_tokens"],
            "latency_ms": telemetry["latency_ms"],
            "llm_attempt_count": telemetry["llm_attempt_count"],
            "llm_call_count": telemetry["llm_call_count"],
            "native_scores": dict(native_scores),
            "output_tokens": telemetry["output_tokens"],
            "prompt_hash": method_result.get("prompt_hash"),
            "protocol_id": self.protocol_id,
            "provider_cost_usd": telemetry["provider_cost_usd"],
            "question_idx": int(example["index"]),
            "raw_trace": method_result.get("raw_trace", method_result.get("trace")),
            "reasoning_tokens": telemetry["reasoning_tokens"],
            "requested_model": self.model_id,
            "resolved_model": telemetry["resolved_model"],
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "retrieval_operation_count": _integer(
                method_result.get("retrieval_operation_count", method_result.get("retrieval_calls", 0))
            ),
            "retry_count": telemetry["retry_count"],
            "route_selected": method_result.get("route_selected", method_result.get("route")),
            "router_features": method_result.get("router_features"),
            "run_id": self.run_id,
            "status": MODEL_FAILURE if model_failed else SUCCESS,
            "total_tokens": telemetry["total_tokens"],
        }
        # Compatibility keys used by the existing audit script.
        record["em"] = native_scores.get("exact_match")
        record["f1"] = native_scores.get("f1")
        record["gt_answer"] = record["ground_truth"]
        record["n_calls"] = record["llm_call_count"]
        return record

    def _failure_record(
        self, framework: str, example: Mapping[str, Any], exc: BaseException
    ) -> Dict[str, Any]:
        metadata = failed_call_metadata(exc)
        telemetry = aggregate_telemetry({"call_records": [metadata]} if metadata else {}, self.model_id)
        retry_count = _integer(metadata.get("retry_count"), 0)
        return {
            "answer": "",
            "backend": telemetry["backend"],
            "cached_tokens": telemetry["cached_tokens"],
            "call_records": telemetry["call_records"],
            "dataset": self.dataset_id,
            "error": metadata.get("error_message") or str(exc),
            "error_type": metadata.get("error_type") or type(exc).__name__,
            "estimated_cost_usd": telemetry["estimated_cost_usd"],
            "evidence_hash": None,
            "example_id": str(example["example_id"]),
            "framework": framework,
            "ground_truth": None,
            "input_tokens": telemetry["input_tokens"],
            "latency_ms": telemetry["latency_ms"],
            "llm_attempt_count": retry_count + 1 if metadata else 0,
            "llm_call_count": 0,
            "native_scores": {},
            "output_tokens": telemetry["output_tokens"],
            "prompt_hash": None,
            "protocol_id": self.protocol_id,
            "provider_cost_usd": telemetry["provider_cost_usd"],
            "question_idx": int(example["index"]),
            "raw_trace": None,
            "reasoning_tokens": telemetry["reasoning_tokens"],
            "requested_model": self.model_id,
            "resolved_model": metadata.get("resolved_model"),
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "retrieval_operation_count": 0,
            "retry_count": retry_count,
            "route_selected": None,
            "router_features": None,
            "run_id": self.run_id,
            "status": classify_exception(exc),
            "total_tokens": telemetry["total_tokens"],
        }

    def _upsert(self, framework: str, record: Dict[str, Any]) -> None:
        identifier = str(record["example_id"])
        retained = [
            saved
            for saved in self.results[framework]
            if str(saved.get("example_id", saved.get("question_idx", ""))) != identifier
        ]
        retained.append(record)
        retained.sort(key=lambda item: (int(item.get("question_idx", -1)), str(item.get("example_id", ""))))
        self.results[framework] = retained
        write_stable_json(self._result_path(framework), retained)

    def run_all(self) -> None:
        self.prepare()
        pairs = self.pending_pairs()
        if not pairs:
            print("[COMPLETE] No pending framework/example pairs.")
            return
        self._validate_methods(pairs)
        self._configure_selective_router(pairs)
        self._snapshot_models()
        start = utc_now()
        counts = {SUCCESS: 0, INFRASTRUCTURE_FAILURE: 0, MODEL_FAILURE: 0}
        for ordinal, (example, framework) in enumerate(pairs, 1):
            self.dataset_setter(self.dataset_id)
            print(
                f"[{ordinal}/{len(pairs)}] {self.dataset_id}/{example['example_id']}/{framework}",
                flush=True,
            )
            try:
                method_result = self._invoke(framework, int(example["index"]))
            except Exception as exc:  # Persist typed failure before continuing the batch.
                record = self._failure_record(framework, example, exc)
            else:
                # Scoring/schema bugs are experiment-integrity failures, not
                # model failures; let them abort instead of mislabelling them.
                record = self._success_record(framework, example, method_result)
            counts[record["status"]] += 1
            self._upsert(framework, record)
        self._append_run_history(start, utc_now(), len(pairs), counts)
        self.write_summary()

    def _append_run_history(
        self, start: str, end: str, attempted: int, counts: Mapping[str, int]
    ) -> None:
        history = []
        if self.run_history_path.exists():
            history = json.loads(self.run_history_path.read_text(encoding="utf-8"))
        history.append(
            {
                "attempted_pairs": attempted,
                "counts": dict(counts),
                "end_time": end,
                "frameworks": self.frameworks,
                "run_id": len(history) + 1,
                "start_time": start,
            }
        )
        write_stable_json(self.run_history_path, history)

    @staticmethod
    def _framework_stats(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        valid = [row for row in results if row.get("status") == SUCCESS]
        exact = [
            _number((row.get("native_scores") or {}).get("exact_match", row.get("em")))
            for row in valid
            if (row.get("native_scores") or {}).get("exact_match", row.get("em")) is not None
        ]
        calls = sum(_integer(row.get("llm_call_count", row.get("n_calls"))) for row in valid)
        return {
            "accuracy_em": sum(exact) / len(exact) if exact else None,
            "estimated_cost_usd": sum(_number(row.get("estimated_cost_usd")) for row in valid),
            "infrastructure_failure_count": sum(
                row.get("status") == INFRASTRUCTURE_FAILURE for row in results
            ),
            "model_failure_count": sum(row.get("status") == MODEL_FAILURE for row in results),
            "total_examples": len(results),
            "total_llm_calls": calls,
            "valid_examples": len(valid),
        }

    def write_summary(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            framework: self._framework_stats(self.results[framework]) for framework in self.frameworks
        }
        summary["_experiment"] = {
            "dataset": self.dataset_id,
            "manifest_fingerprint": self.manifest["manifest_fingerprint"],
            "model_id": self.model_id,
            "partition": self.partition,
            "protocol_id": self.protocol_id,
            "selected_examples": len(self.selected_examples()),
        }
        write_stable_json(self.summary_path, summary)
        return summary


def prepare_all(args: argparse.Namespace) -> List[tuple[str, Path, List[Dict[str, Any]]]]:
    prepared = []
    protocol = load_protocol(args.protocol)
    for dataset_id in DATASETS:
        runner = FinanceExperimentRunner(
            dataset_id=dataset_id,
            model_id=args.model_id,
            num_examples=args.num_examples,
            frameworks=args.frameworks,
            results_tag=args.results_tag,
            seed=args.seed,
            protocol=protocol,
            partition=args.partition,
            resume=args.resume,
            retry_infrastructure_failures=args.retry_infrastructure_failures,
        )
        prepared.append((dataset_id, runner.results_dir, runner.prepare()))
    return prepared


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run frozen finance protocol v2 experiments")
    parser.add_argument("--protocol", default=None, help="Protocol ID or JSON path")
    parser.add_argument(
        "--dataset", default="financebench", choices=list(DATASETS) + ["all"]
    )
    parser.add_argument("--model-id", dest="model_id", default=None)
    parser.add_argument("--model", dest="model_id", help=argparse.SUPPRESS)
    parser.add_argument("--num-examples", type=int, default=None, help="Deterministic prefix for smoke runs")
    parser.add_argument(
        "--frameworks", nargs="+", default=list(FRAMEWORK_CHOICES), choices=FRAMEWORK_CHOICES
    )
    parser.add_argument("--partition", choices=("development", "smoke", "final"), default="final")
    parser.add_argument("--results-tag", default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-infrastructure-failures", action="store_true")
    parser.add_argument("--retry-failed", dest="retry_infrastructure_failures", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.retry_infrastructure_failures and not args.resume:
        raise SystemExit("--retry-infrastructure-failures requires --resume")
    if args.dataset == "all":
        if not args.prepare_only:
            raise SystemExit("--dataset all is preparation-only; run one process per dataset")
        for dataset_id, results_dir, selected in prepare_all(args):
            print(f"[PREPARED] {dataset_id}: {results_dir} ({len(selected)} examples)")
        return
    runner = FinanceExperimentRunner(
        dataset_id=args.dataset,
        model_id=args.model_id,
        num_examples=args.num_examples,
        frameworks=args.frameworks,
        results_tag=args.results_tag,
        seed=args.seed,
        protocol=args.protocol,
        partition=args.partition,
        resume=args.resume,
        retry_infrastructure_failures=args.retry_infrastructure_failures,
    )
    if args.prepare_only:
        selected = runner.prepare()
        print(f"[PREPARED] {args.dataset}: {runner.results_dir} ({len(selected)} examples)")
    elif args.summarize_only:
        print(json.dumps(runner.write_summary(), indent=2))
    else:
        runner.run_all()


if __name__ == "__main__":
    main()
