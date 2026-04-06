"""Infrastructure adapters for datasets and persistence."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "DemoDataset",
    "DemoDatasetSpec",
    "build_demo_dataset",
    "build_demo_readings",
    "build_demo_stations",
    "write_demo_dataset",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        module = import_module("stellanex_telemetry.infrastructure.demo_dataset")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
