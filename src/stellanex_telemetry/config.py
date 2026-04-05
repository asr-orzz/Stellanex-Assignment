from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Stellanex Grid Telemetry Console"
DEFAULT_TIMEZONE = "UTC"


def _resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_env_path(variable_name: str) -> Path | None:
    raw_value = os.environ.get(variable_name)
    if not raw_value:
        return None
    return Path(raw_value).expanduser().resolve()


@dataclass(frozen=True)
class AppPaths:
    repo_root: Path
    data_dir: Path
    demo_data_dir: Path
    imports_dir: Path
    runtime_dir: Path
    cache_dir: Path
    exports_dir: Path
    logs_dir: Path

    def ensure_runtime_directories(self) -> None:
        """Create the writable directories used by the application."""
        for path in (self.imports_dir, self.runtime_dir, self.cache_dir, self.exports_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    timezone: str
    paths: AppPaths


def load_config() -> AppConfig:
    repo_root = _resolve_repo_root()
    data_dir = _resolve_env_path("STELLANEX_DATA_DIR") or (repo_root / "data")
    runtime_dir = _resolve_env_path("STELLANEX_RUNTIME_DIR") or (data_dir / "runtime")
    paths = AppPaths(
        repo_root=repo_root,
        data_dir=data_dir,
        demo_data_dir=data_dir / "demo",
        imports_dir=data_dir / "imports",
        runtime_dir=runtime_dir,
        cache_dir=runtime_dir / "cache",
        exports_dir=runtime_dir / "exports",
        logs_dir=runtime_dir / "logs",
    )
    return AppConfig(app_name=APP_NAME, timezone=DEFAULT_TIMEZONE, paths=paths)

