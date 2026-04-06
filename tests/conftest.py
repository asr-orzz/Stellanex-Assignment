from __future__ import annotations

from pathlib import Path

import pytest

from stellanex_telemetry.config import load_config
from stellanex_telemetry.infrastructure import RuntimeDatasetWorkspace


@pytest.fixture()
def demo_data_dir() -> Path:
    return load_config().paths.demo_data_dir


@pytest.fixture()
def isolated_workspace(tmp_path: Path, demo_data_dir: Path) -> RuntimeDatasetWorkspace:
    imports_dir = tmp_path / "imports"
    runtime_dir = tmp_path / "runtime"
    imports_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return RuntimeDatasetWorkspace(
        demo_data_dir=demo_data_dir,
        imports_dir=imports_dir,
        runtime_dir=runtime_dir,
    )


@pytest.fixture()
def demo_runtime(isolated_workspace: RuntimeDatasetWorkspace):
    return isolated_workspace.load_dataset("demo")


@pytest.fixture()
def isolated_cli_runtime_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("STELLANEX_RUNTIME_DIR", str(runtime_dir))
    return runtime_dir
