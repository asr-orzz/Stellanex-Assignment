"""Presentation layer for desktop UI and future view models."""

from stellanex_telemetry.presentation.shell import (
    DesktopShellContext,
    TelemetryDesktopShell,
    create_desktop_shell,
    launch_desktop_shell,
)
from stellanex_telemetry.presentation.theme import DesktopTheme, build_desktop_theme
from stellanex_telemetry.presentation.view_models import (
    AlertItemViewModel,
    KeyValueRowViewModel,
    MetricCardViewModel,
    StationDetailViewModel,
    StationHeaderViewModel,
    TelemetryPointViewModel,
    build_station_detail_view_model,
)

__all__ = [
    "AlertItemViewModel",
    "DesktopShellContext",
    "DesktopTheme",
    "KeyValueRowViewModel",
    "MetricCardViewModel",
    "StationDetailViewModel",
    "StationHeaderViewModel",
    "TelemetryDesktopShell",
    "TelemetryPointViewModel",
    "build_desktop_theme",
    "build_station_detail_view_model",
    "create_desktop_shell",
    "launch_desktop_shell",
]
