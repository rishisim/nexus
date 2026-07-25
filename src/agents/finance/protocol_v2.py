"""Deterministic protocol and manifest utilities for the ICAIF 2026 study.

The manifest generator deliberately operates on adapter rows rather than
downloading datasets itself.  This keeps generation testable and makes the
adapter's exact, model-visible row ordering part of the frozen protocol.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Sequence


SCHEMA_VERSION = "finance-protocol-v2"
MANIFEST_SCHEMA_VERSION = "finance-manifest-v2"
DEFAULT_SEED = 20260709
DATASETS = ("financebench", "finder", "finqa", "tatqa", "convfinqa")
DEFAULT_PROTOCOL_PATH = Path(__file__).with_name("protocols") / "finance_icaif26_v2.json"


class ProtocolError(ValueError):
    """Raised when a protocol or generated split violates a frozen invariant."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return the single canonical encoding used for fingerprints."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def stable_json_text(value: Any) -> str:
    """Pretty, byte-stable JSON for committed protocol artifacts."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"


def write_stable_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = stable_json_text(value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def resolve_protocol_path(value: str | Path | None) -> Path:
    if value is None:
        return DEFAULT_PROTOCOL_PATH
    candidate = Path(value)
    if candidate.exists():
        return candidate.resolve()
    protocol_dir = DEFAULT_PROTOCOL_PATH.parent
    named = protocol_dir / str(value)
    if named.suffix != ".json":
        named = named.with_suffix(".json")
    if named.exists():
        return named.resolve()
    raise FileNotFoundError(f"Protocol not found: {value}")


def load_protocol(value: str | Path | Mapping[str, Any] | None = None) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        protocol = dict(value)
    else:
        path = resolve_protocol_path(value)
        protocol = json.loads(path.read_text(encoding="utf-8"))
        protocol["_path"] = str(path)
    validate_protocol(protocol)
    return protocol


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError(f"Expected schema_version={SCHEMA_VERSION!r}")
    if not protocol.get("protocol_id"):
        raise ProtocolError("protocol_id is required")
    if int(protocol.get("seed", -1)) < 0:
        raise ProtocolError("seed must be a non-negative integer")
    datasets = protocol.get("datasets")
    if not isinstance(datasets, Mapping) or set(datasets) != set(DATASETS):
        raise ProtocolError(f"datasets must contain exactly {DATASETS}")
    for dataset_id, spec in datasets.items():
        dev = spec.get("development_indices")
        if not isinstance(dev, list) or len(dev) != 50 or len(set(dev)) != 50:
            raise ProtocolError(f"{dataset_id}: exactly 50 unique development indices required")
        target = int(spec.get("final_count", -1))
        expected = 100 if dataset_id == "financebench" else 200
        if target != expected:
            raise ProtocolError(f"{dataset_id}: final_count must be {expected}")


def _seed_for(seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _sample(indices: Iterable[int], count: int, seed: int, label: str) -> List[int]:
    candidates = sorted(set(indices))
    if len(candidates) < count:
        raise ProtocolError(f"{label}: requested {count} examples from {len(candidates)} candidates")
    random.Random(_seed_for(seed, label)).shuffle(candidates)
    return sorted(candidates[:count])


def _stratum_key(parts: Sequence[Any]) -> str:
    normalized = [str(part if part not in (None, "") else "<missing>") for part in parts]
    return " | ".join(normalized)


def stratified_sample(
    indices: Iterable[int],
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    count: int,
    seed: int,
    label: str,
) -> List[int]:
    """Proportionally sample stable strata using largest-remainder allocation."""
    groups: MutableMapping[str, List[int]] = defaultdict(list)
    for idx in sorted(set(indices)):
        groups[_stratum_key([rows[idx].get(field) for field in fields])].append(idx)
    total = sum(len(group) for group in groups.values())
    if total < count:
        raise ProtocolError(f"{label}: requested {count} examples from {total} candidates")

    exact = {key: count * len(group) / total for key, group in groups.items()}
    allocations = {key: min(len(groups[key]), math.floor(value)) for key, value in exact.items()}
    remainder = count - sum(allocations.values())
    order = sorted(groups, key=lambda key: (-(exact[key] - math.floor(exact[key])), key))
    while remainder:
        progressed = False
        for key in order:
            if allocations[key] < len(groups[key]):
                allocations[key] += 1
                remainder -= 1
                progressed = True
                if remainder == 0:
                    break
        if not progressed:
            raise ProtocolError(f"{label}: unable to allocate complete stratified sample")

    selected: List[int] = []
    for key in sorted(groups):
        candidates = list(groups[key])
        random.Random(_seed_for(seed, f"{label}:{key}")).shuffle(candidates)
        selected.extend(candidates[: allocations[key]])
    return sorted(selected)


def _example_id(dataset_id: str, row: Mapping[str, Any], idx: int) -> str:
    if dataset_id == "financebench":
        value = row.get("financebench_id") or row.get("domain_question_num")
    else:
        value = row.get("source_id")
    return str(value if value not in (None, "") else f"{dataset_id}:{idx}")


def _example_record(dataset_id: str, rows: Sequence[Mapping[str, Any]], idx: int) -> Dict[str, Any]:
    row = rows[idx]
    record: Dict[str, Any] = {"example_id": _example_id(dataset_id, row, idx), "index": idx}
    if dataset_id == "convfinqa":
        record["dialogue_id"] = str(row.get("dialogue_id", ""))
    if dataset_id == "finder":
        record["stratum"] = _stratum_key([row.get("category"), row.get("question_type")])
    if dataset_id == "tatqa":
        record["stratum"] = _stratum_key([row.get("question_type"), row.get("answer_from")])
    return record


def build_manifest(
    protocol: Mapping[str, Any], dataset_id: str, rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Build one development/final manifest and assert all split invariants."""
    validate_protocol(protocol)
    if dataset_id not in DATASETS:
        raise ProtocolError(f"Unknown dataset: {dataset_id}")
    spec = protocol["datasets"][dataset_id]
    seed = int(protocol["seed"])
    dev = sorted(int(idx) for idx in spec["development_indices"])
    if not rows:
        raise ProtocolError(f"{dataset_id}: adapter returned no rows")
    if dev and (dev[0] < 0 or dev[-1] >= len(rows)):
        raise ProtocolError(f"{dataset_id}: development index outside adapter range")
    candidates = sorted(set(range(len(rows))) - set(dev))
    target = int(spec["final_count"])

    if dataset_id == "financebench":
        if len(candidates) != target:
            raise ProtocolError(
                f"financebench: expected all {target} non-development examples, found {len(candidates)}"
            )
        final = candidates
        policy = "all rows not in development"
    elif dataset_id == "finder":
        final = stratified_sample(
            candidates, rows, ("category", "question_type"), target, seed, dataset_id
        )
        policy = "proportional strata: category x question_type"
    elif dataset_id == "tatqa":
        final = stratified_sample(
            candidates, rows, ("question_type", "answer_from"), target, seed, dataset_id
        )
        policy = "proportional strata: answer_type x answer_source"
    elif dataset_id == "convfinqa":
        dev_dialogues = {str(rows[idx].get("dialogue_id", "")) for idx in dev}
        eligible = [
            idx for idx in candidates if str(rows[idx].get("dialogue_id", "")) not in dev_dialogues
        ]
        final = _sample(eligible, target, seed, dataset_id)
        policy = "seeded sample from dialogue IDs absent from development"
        final_dialogues = {str(rows[idx].get("dialogue_id", "")) for idx in final}
        if dev_dialogues & final_dialogues:
            raise ProtocolError("convfinqa: development/final dialogue overlap")
    else:
        final = _sample(candidates, target, seed, dataset_id)
        policy = "seeded sample excluding development indices"

    if set(dev) & set(final):
        raise ProtocolError(f"{dataset_id}: development/final index overlap")
    if len(final) != target or len(set(final)) != target:
        raise ProtocolError(f"{dataset_id}: final split must contain {target} unique examples")
    dataset_digest = fingerprint(list(rows))
    body: Dict[str, Any] = {
        "dataset": dataset_id,
        "dataset_fingerprint": dataset_digest,
        "dataset_size": len(rows),
        "development": {
            "count": len(dev),
            "examples": [_example_record(dataset_id, rows, idx) for idx in dev],
            "indices": dev,
        },
        "final": {
            "count": len(final),
            "examples": [_example_record(dataset_id, rows, idx) for idx in final],
            "indices": final,
        },
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "protocol_id": protocol["protocol_id"],
        "seed": seed,
        "selection_policy": policy,
    }
    body["manifest_fingerprint"] = fingerprint(body)
    return body


def generate_manifests(
    protocol: str | Path | Mapping[str, Any] | None,
    env_factory: Callable[[str], Any],
    output_dir: str | Path | None = None,
) -> Dict[str, Dict[str, Any]]:
    loaded = load_protocol(protocol)
    target_dir = Path(output_dir or DEFAULT_PROTOCOL_PATH.parent / "manifests")
    generated: Dict[str, Dict[str, Any]] = {}
    for dataset_id in DATASETS:
        env = env_factory(dataset_id)
        rows = list(env.rows)
        manifest = build_manifest(loaded, dataset_id, rows)
        write_stable_json(target_dir / f"{dataset_id}.json", manifest)
        generated[dataset_id] = manifest
    return generated


def load_manifest(protocol: Mapping[str, Any], dataset_id: str) -> Dict[str, Any]:
    protocol_path = Path(protocol.get("_path", DEFAULT_PROTOCOL_PATH))
    configured = protocol["datasets"][dataset_id].get("manifest")
    path = Path(configured) if configured else Path("manifests") / f"{dataset_id}.json"
    if not path.is_absolute():
        path = protocol_path.parent / path
    manifest = json.loads(path.read_text(encoding="utf-8"))
    supplied = manifest.pop("manifest_fingerprint", None)
    actual = fingerprint(manifest)
    manifest["manifest_fingerprint"] = supplied
    if supplied != actual:
        raise ProtocolError(f"{dataset_id}: manifest fingerprint mismatch")
    if manifest.get("protocol_id") != protocol.get("protocol_id"):
        raise ProtocolError(f"{dataset_id}: manifest/protocol ID mismatch")
    return manifest

