"""Lazy offline dataset adapters that never dereference excluded final rows."""

from __future__ import annotations

import bisect
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .finance_env import (
    EvidencePacketEnv,
    _extract_context_from_query,
    _extract_question_from_query,
    _render_table,
    _stringify_answer,
    _unsearched_evidence_stats,
)


os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")


def _load(name: str, split: str):
    from datasets import load_dataset

    return load_dataset(name, split=split, download_mode="reuse_dataset_if_exists")


class DirectRows(Sequence[Mapping[str, Any]]):
    def __init__(self, dataset_id: str):
        self.dataset_id = dataset_id
        if dataset_id == "finqa":
            self.raw = _load("ChanceFocus/flare-finqa", "valid")
        elif dataset_id == "convfinqa":
            self.raw = _load("ChanceFocus/flare-convfinqa", "valid")
        else:
            raise ValueError(dataset_id)

    def __len__(self) -> int:
        return len(self.raw)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return [self[i] for i in range(*idx.indices(len(self)))]
        row = self.raw[int(idx)]
        if self.dataset_id == "finqa":
            return {
                "question": _extract_question_from_query(row["query"], row.get("text", "")),
                "answer": row["answer"],
                "evidence": [_extract_context_from_query(row["query"])],
                "source_id": row.get("id", ""),
                "question_type": "numerical_financial_qa",
            }
        return {
            "question": _extract_question_from_query(row["query"], row.get("query", "")),
            "answer": row["answer"],
            "evidence": [_extract_context_from_query(row["query"])],
            "source_id": row.get("id", ""),
            "question_type": "conversational_financial_qa",
            "turn": row.get("turn", ""),
            "dialogue_id": row.get("dialogue_id", ""),
        }


class TatqaRows(Sequence[Mapping[str, Any]]):
    """Flatten TAT-QA lazily; context offsets are read without question content."""

    def __init__(self):
        self.raw = _load("next-tat/TAT-QA", "validation")
        import pyarrow.compute as pc

        questions = self.raw.data.column("questions")
        counts = []
        for chunk in questions.chunks:
            counts.extend(int(value or 0) for value in pc.list_value_length(chunk).to_pylist())
        self.offsets = [0]
        for count in counts:
            self.offsets.append(self.offsets[-1] + count)

    def __len__(self) -> int:
        return self.offsets[-1]

    def context_for_index(self, idx: int) -> int:
        idx = int(idx)
        if idx < 0 or idx >= len(self):
            raise IndexError(idx)
        return bisect.bisect_right(self.offsets, idx) - 1

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return [self[i] for i in range(*idx.indices(len(self)))]
        flat = int(idx)
        context_idx = self.context_for_index(flat)
        question_idx = flat - self.offsets[context_idx]
        row = self.raw[context_idx]
        question = row["questions"][question_idx]
        table_text = _render_table(row.get("table"))
        paragraph_text = "\n".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in (row.get("paragraphs") or [])
        )
        return {
            "question": question.get("question", ""),
            "answer": _stringify_answer(question.get("answer")),
            "evidence": [f"Table:\n{table_text}", f"Paragraphs:\n{paragraph_text}"],
            "source_id": question.get("uid", f"{context_idx}-{question.get('order', '')}"),
            "question_type": question.get("answer_type", ""),
            "answer_from": question.get("answer_from", ""),
            "gold_scale": question.get("scale", ""),
        }


class LazyFinanceSource:
    def __init__(self, dataset_id: str):
        self.dataset_id = dataset_id
        self.rows = TatqaRows() if dataset_id == "tatqa" else DirectRows(dataset_id)


def make_lazy_env(dataset_id: str, rows: Sequence[Mapping[str, Any]]) -> EvidencePacketEnv:
    env = object.__new__(EvidencePacketEnv)
    env.dataset_id = dataset_id
    env.split = "frozen-offline-cache"
    env.rows = rows
    env.current_idx = None
    env.current_row = None
    env.current_passages = []
    env.lookup_keyword = None
    env.lookup_results = []
    env.lookup_count = 0
    env.answer = None
    env.obs = None
    env.steps = 0
    env.evidence_stats = _unsearched_evidence_stats([])
    return env


class HarmonizedEnvFactory:
    def __init__(self):
        self.sources: Dict[str, LazyFinanceSource] = {}
        self.envs: Dict[str, EvidencePacketEnv] = {}

    def source(self, dataset_id: str) -> LazyFinanceSource:
        if dataset_id not in self.sources:
            self.sources[dataset_id] = LazyFinanceSource(dataset_id)
        return self.sources[dataset_id]

    def __call__(self, dataset_id: str) -> EvidencePacketEnv:
        if dataset_id not in self.envs:
            source = self.source(dataset_id)
            self.envs[dataset_id] = make_lazy_env(dataset_id, source.rows)
        return self.envs[dataset_id]
