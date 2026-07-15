import json
from pathlib import Path

import pytest

from scripts.realm26_blinded_adjudication import (
    FORBIDDEN_PUBLIC_TERMS,
    SEED,
    build_packet,
    write_outputs,
)


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "paper/realm2026/artifacts/fairness_audit.json"


def test_packet_is_exactly_frozen_queue_and_is_order_deterministic():
    audit = json.loads(AUDIT.read_text())
    rows_a, key_a = build_packet(audit)
    rows_b, key_b = build_packet(audit)
    assert len(rows_a) == 51
    assert rows_a == rows_b
    assert key_a == key_b
    assert set(key_a["items"]) == {row["case_id"] for row in rows_a}
    assert all("System A" not in json.dumps(key_a["items"][case]) for case in key_a["items"])


def test_public_packet_has_no_identity_or_codex_labels(tmp_path):
    audit = json.loads(AUDIT.read_text())
    rows, key = build_packet(audit, SEED)
    csv_path, md_path, key_path = (tmp_path / name for name in ("packet.csv", "packet.md", "private.json"))
    write_outputs(rows, key, csv_path, md_path, key_path)
    public = csv_path.read_text() + md_path.read_text()
    assert not FORBIDDEN_PUBLIC_TERMS.search(public)
    assert "reviewer_1_a_correctness" in public
    assert "reviewer_2_b_notes" in public
    assert "reference_answer" in csv_path.read_text()
    assert "static_nexus" not in public.lower()
    assert "react" not in public.lower()


@pytest.mark.parametrize("name", ["final", "sealed-final", "results", "outcomes", "traces"])
def test_paths_that_could_touch_execution_artifacts_are_refused(tmp_path, name):
    audit = json.loads(AUDIT.read_text())
    rows, key = build_packet(audit)
    with pytest.raises(ValueError):
        write_outputs(rows, key, tmp_path / name / "packet.csv", tmp_path / "packet.md", tmp_path / "key.json")
