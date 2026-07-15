#!/usr/bin/env python3
"""Assemble the tracked, provider-free REALM review artifact.

This script only reads committed development/protocol/source files.  It never
opens datasets, final examples, result rows, or provider clients.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = Path(__file__).resolve().parent


def stable(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    snapshots = ARTIFACT / "snapshots"
    manifests = ARTIFACT / "development_manifests"
    snapshots.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)

    source_files = {
        "protocol": ROOT / "src/agents/finance/protocols/finance_icaif26_v2.json",
        "prompts": ROOT / "src/agents/finance/finance_prompts.py",
        "method_prompts": ROOT / "src/agents/finance/method_prompts.py",
        "scorer": ROOT / "src/agents/finance/finance_scoring.py",
        "price_table": ROOT / "src/shared/llm_telemetry.py",
        "router": ROOT / "src/agents/finance/protocols/artifacts/selective_router.json",
        "model_snapshot": ROOT / "results/finance/finqa/finance_icaif26_v2_development_google-gemini-2.5-flash_dev-20260709/model_snapshot.json",
        "development_aggregation": ROOT / "paper/icaif2026/artifacts/development_summary.json",
    }
    for name, source in source_files.items():
        if not source.is_file():
            raise SystemExit(f"missing source: {source}")
        target = snapshots / source.name
        shutil.copyfile(source, target)

    for source in sorted((ROOT / "src/agents/finance/protocols/manifests").glob("*.json")):
        payload = json.loads(source.read_text(encoding="utf-8"))
        dev_only = dict(payload)
        dev_only.pop("final", None)
        dev_only["artifact_partition"] = "development_only"
        dev_only["final_partition"] = "excluded"
        target = manifests / source.name
        target.write_text(stable(dev_only), encoding="utf-8")

    entries = []
    for path in sorted(ARTIFACT.rglob("*")):
        if path.is_file() and path.name not in {"checksums.sha256", "manifest.json"}:
            entries.append({"path": path.relative_to(ARTIFACT).as_posix(), "sha256": sha256(path)})
    manifest = {
        "schema": "realm-anonymous-artifact-v1",
        "purpose": "provider-free reproduction of development aggregation and protocol inspection",
        "partition": "development_only",
        "sealed_final_partition": "excluded",
        "provider_calls": False,
        "entries": entries,
        "source_commit": "c08d0ae",
    }
    (ARTIFACT / "manifest.json").write_text(stable(manifest), encoding="utf-8")

    # Recompute after manifest creation; checksums excludes itself by design.
    entries = []
    for path in sorted(ARTIFACT.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            entries.append(f"{sha256(path)}  {path.relative_to(ARTIFACT).as_posix()}")
    (ARTIFACT / "checksums.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
