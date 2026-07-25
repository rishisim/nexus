"""Dataset catalog helpers for the finance Nexus lane."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml


CATALOG_PATH = Path(__file__).with_name("datasets.yaml")


@dataclass(frozen=True)
class FinanceDataset:
    id: str
    name: str
    task_type: str
    first_pass_priority: int
    metadata: Dict


def load_catalog(path: Path = CATALOG_PATH) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def primary_datasets(path: Path = CATALOG_PATH) -> List[FinanceDataset]:
    catalog = load_catalog(path)
    datasets = []
    for item in catalog.get("primary", []):
        datasets.append(
            FinanceDataset(
                id=item["id"],
                name=item["name"],
                task_type=item.get("task_type", ""),
                first_pass_priority=int(item.get("first_pass_priority", 999)),
                metadata=item,
            )
        )
    return sorted(datasets, key=lambda dataset: dataset.first_pass_priority)


def get_dataset(dataset_id: str, path: Path = CATALOG_PATH) -> FinanceDataset:
    for dataset in primary_datasets(path):
        if dataset.id == dataset_id:
            return dataset
    raise KeyError(f"Unknown finance dataset: {dataset_id}")
