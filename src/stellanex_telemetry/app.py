from __future__ import annotations

from stellanex_telemetry.config import AppConfig, load_config


def build_bootstrap_message(config: AppConfig) -> str:
    """Return a simple status message until the desktop shell lands."""
    return (
        f"{config.app_name}\n"
        "Repository bootstrap complete.\n"
        f"Demo datasets: {config.paths.demo_data_dir}\n"
        f"Import drop zone: {config.paths.imports_dir}\n"
        f"Runtime workspace: {config.paths.runtime_dir}\n"
        "Next milestones: domain modeling, ingestion, analytics, and desktop UI."
    )


def main() -> None:
    config = load_config()
    config.paths.ensure_runtime_directories()
    print(build_bootstrap_message(config))

